"""
arc/agents/session_controller.py
─────────────────────────────────
SessionController — owns all workers, wires them together.

Handoff flow (A2A, immediate, no LLM roundtrip)
─────────────────────────────────────────────────
  1. Agent A finishes speaking and its full transcript contains a handoff phrase.
  2. LiveAgentWorker.handoff_requested(peer_name) fires.
  3. SessionController._on_handoff_requested() runs immediately:
       a. Interrupt agent A's audio buffer.
       b. Read last 5 entries from the SharedConversationLog (mmap).
       c. Build a one-sentence context prompt for agent B.
       d. deliver_text(context) → agent B.
       e. Switch microphone to agent B.
  4. Agent B starts speaking within ~1 audio RTT.

No CrewAI. No intermediate LLM roundtrip. Total handoff latency ≈ 50 ms.
"""

from __future__ import annotations

import logging
import random

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

from .live_agent   import LiveAgentWorker
from .orchestrator import OrchestratorWorker
from .mark.agent   import MarkWorker
from ..core.config import AGENT_PERSONAS
from ..core.shared_memory import SharedConversationLog

logger = logging.getLogger(__name__)


class SessionController(QObject):
    """
    Signals forwarded to the UI
    ────────────────────────────
        agent_speaking(agent_id, bool)
        output_transcription(agent_id, text, finished)
        input_transcription(text, finished)
        text_received(agent_id, text, partial)
        turn_complete(agent_id)
        interrupted(agent_id)
        agent_status(agent_id, status)
        agent_error(agent_id, msg)
        event_logged(agent_id, raw_event)
        active_agent_changed(agent_id)
        routing_note(str)
    """

    agent_speaking       = pyqtSignal(str, bool)
    output_transcription = pyqtSignal(str, str, bool)
    input_transcription  = pyqtSignal(str, bool)
    text_received        = pyqtSignal(str, str, bool)
    turn_complete        = pyqtSignal(str)
    interrupted          = pyqtSignal(str)
    agent_status         = pyqtSignal(str, str)
    agent_error          = pyqtSignal(str, str)
    event_logged         = pyqtSignal(str, dict)
    active_agent_changed = pyqtSignal(str)
    routing_note         = pyqtSignal(str)
    # Mark-specific: emitted when Image Generation completes
    image_ready          = pyqtSignal(str)  # absolute path to generated image

    # WebSocket bridge signals
    audio_chunk_generated = pyqtSignal(str, bytes)  # agent_id, raw pcm bytes

    def __init__(
        self,
        proactivity: bool = False,
        affective_dialog: bool = False,
        enable_lookahead: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.proactivity      = proactivity
        self.affective_dialog = affective_dialog
        self.enable_lookahead = enable_lookahead

        # One SharedConversationLog shared by all workers + orchestrator.
        # Lives in an anonymous mmap — all threads read the same memory pages.
        self._log = SharedConversationLog()

        self._agents:       dict[str, LiveAgentWorker]  = {}
        self._orchestrator: OrchestratorWorker | None   = None
        self._active_id:    str  = AGENT_PERSONAS[0]["id"]
        self._recording:    bool = False
        self._mic_owner_id: str  = AGENT_PERSONAS[0]["id"]

        # Look-ahead handoff: (from_id, to_id) while current speaker is still
        # playing audio.  None means no pending handoff is outstanding.
        self._pending_handoff: tuple[str, str] | None = None

        # Deferred A2A: when an agent whose audio is held completes its LLM
        # turn, we cannot run A2A detection immediately (it would start
        # preparing the NEXT reply before the current one even plays).
        # We store the agent_id here and run A2A when the hold is released.
        self._deferred_a2a: str | None = None

        # Timer that polls the current speaker's audio buffer every 50 ms.
        # When the buffer drains, releases the incoming agent and immediately
        # runs any deferred A2A so the next look-ahead can begin right away.
        self._handoff_poll_timer = QTimer(self)
        self._handoff_poll_timer.setInterval(50)
        self._handoff_poll_timer.timeout.connect(self._check_pending_handoff)

        # Delayed release: after the poll detects buffer drain, a random
        # 3-5 s pause fires before the incoming agent is actually released.
        # Stores the to_id so it can be cancelled if a new route supersedes.
        self._pending_release_to_id: str | None = None
        self._MIN_PAUSE_MS = 500
        self._MAX_PAUSE_MS = 3000

        # Name → id lookup built from personas
        self._name_to_id: dict[str, str] = {
            p["name"]: p["id"] for p in AGENT_PERSONAS
        }

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self):
        personas = AGENT_PERSONAS

        for i, p in enumerate(personas):
            # Mark gets its own MarkWorker subclass; all others use LiveAgentWorker.
            if p["id"] == "mark":
                worker = MarkWorker(
                    persona=p,
                    shared_log=self._log,
                    proactivity=self.proactivity,
                    affective_dialog=self.affective_dialog,
                    startup_delay=i * 1.5,
                )
                # Forward Mark's image_ready signal to the UI layer
                worker.image_ready.connect(self.image_ready)
            else:
                worker = LiveAgentWorker(
                    persona=p,
                    shared_log=self._log,
                    proactivity=self.proactivity,
                    affective_dialog=self.affective_dialog,
                    startup_delay=i * 1.5,
                )
            self._wire_agent(worker)
            self._agents[p["id"]] = worker
            worker.start()

        self._orchestrator = OrchestratorWorker(
            personas=personas,
            shared_log=self._log,
        )
        self._orchestrator.route_to.connect(self._on_route_to)
        self._orchestrator.routing_note.connect(self.routing_note)
        self._orchestrator.error_occurred.connect(
            lambda e: self.agent_error.emit("orchestrator", e))
        self._orchestrator.start()

    def stop(self):
        if self._recording:
            self.stop_recording()
        if self._orchestrator:
            self._orchestrator.shutdown()
            self._orchestrator.wait(3000)
            self._orchestrator = None
        for w in self._agents.values():
            w.shutdown()
            w.wait(3000)
        self._agents.clear()
        self._log.clear()

    # ── Public API ────────────────────────────────────────────────────────────

    def send_text(self, text: str, force_agent_id: str | None = None):
        if self._orchestrator:
            self._orchestrator.route(text, force_agent_id=force_agent_id)

    def send_image(self, jpeg_bytes: bytes):
        if self._active_id in self._agents:
            self._agents[self._active_id].deliver_image(jpeg_bytes)

    def inject_audio(self, pcm_bytes: bytes):
        """Web client has sent speech. Route directly to the active agent."""
        if self._active_id in self._agents:
            # We bypass the local sounddevice microphone
            self._agents[self._active_id].deliver_audio(pcm_bytes)

    def add_agent_live(self, persona: dict):
        """Dynamically add a new agent while the session is running."""
        # Add to global personas list
        self._name_to_id[persona["name"]] = persona["id"]
        
        # Instantiate worker
        worker = LiveAgentWorker(
            persona=persona,
            shared_log=self._log,
            proactivity=self.proactivity,
            affective_dialog=self.affective_dialog,
            startup_delay=0.0,
        )
        self._wire_agent(worker)
        self._agents[persona["id"]] = worker
        worker.start()

        # Update orchestrator
        if self._orchestrator:
            self._orchestrator.add_persona(persona)
            
        # Optional: Log event internally if needed
        logger.info(f"Dynamically added agent {persona['name']} ({persona['id']})")

    def remove_agent_live(self, agent_id: str):
        """Dynamically remove an active agent from the session."""
        worker = self._agents.get(agent_id)
        if not worker:
            return
            
        # 1. Gracefully shutdown the worker thread
        worker.shutdown()
        worker.wait(2000)
        
        # 2. Cleanup state tracking
        self._agents.pop(agent_id, None)
        
        # 3. Inform the orchestrator to drop the agent
        if self._orchestrator:
            self._orchestrator.remove_persona(agent_id)
            
        # If the removed agent was the mic owner/active, fall back to someone else
        if self._active_id == agent_id:
            fallback = next(iter(self._agents.keys())) if self._agents else None
            if fallback:
                self._active_id = fallback
                self.active_agent_changed.emit(fallback)
                if self._recording and self._mic_owner_id == agent_id:
                    self.switch_mic_to(fallback)
                    
        # Optional: Log removal internally
        logger.info(f"Dynamically removed agent {agent_id}")

    def start_recording(self):
        if self._recording:
            return
        self._recording     = True
        self._mic_owner_id  = self._active_id
        if self._active_id in self._agents:
            self._agents[self._active_id].start_recording()

    def stop_recording(self):
        self._recording = False
        for w in self._agents.values():
            if w._recording:
                w.stop_recording()

    def switch_mic_to(self, agent_id: str):
        if agent_id == self._mic_owner_id:
            return
        old = self._agents.get(self._mic_owner_id)
        if old and old._recording:
            old.stop_recording()
        new = self._agents.get(agent_id)
        if new and self._recording:
            new.start_recording()
        self._mic_owner_id = agent_id

    @property
    def active_agent_id(self) -> str:
        return self._active_id

    # ── Internal wiring ───────────────────────────────────────────────────────

    def _wire_agent(self, worker: LiveAgentWorker):
        aid = worker.agent_id
        worker.text_received.connect(
            lambda t, p, _id=aid: self.text_received.emit(_id, t, p))
        worker.input_transcription.connect(self.input_transcription)
        worker.output_transcription.connect(
            lambda t, f, _id=aid: self.output_transcription.emit(_id, t, f))
        worker.turn_complete.connect(
            lambda _id=aid: self.turn_complete.emit(_id))
        # Transcript-Watcher A2A: on turn completion, feed the finalized
        # transcript to the orchestrator for peer-invite detection.
        worker.turn_complete.connect(
            lambda _id=aid: self._on_agent_turn_complete(_id))
        worker.interrupted.connect(
            lambda _id=aid: self.interrupted.emit(_id))
        worker.agent_speaking.connect(
            lambda v, _id=aid: self._on_agent_speaking(_id, v))
        worker.event_logged.connect(
            lambda ev, _id=aid: self.event_logged.emit(_id, ev))
        worker.status_changed.connect(
            lambda s, _id=aid: self.agent_status.emit(_id, s))
        worker.error_occurred.connect(
            lambda e, _id=aid: self.agent_error.emit(_id, e))
        
        # Audio bridging to WS
        if hasattr(worker, 'audio_chunk'):
            worker.audio_chunk.connect(
                lambda pcm, _id=aid: self.audio_chunk_generated.emit(_id, pcm))

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_agent_speaking(self, agent_id: str, speaking: bool):
        self.agent_speaking.emit(agent_id, speaking)
        if speaking and agent_id != self._active_id:
            self._active_id = agent_id
            self.active_agent_changed.emit(agent_id)
            if self._orchestrator:
                self._orchestrator.set_last_active(agent_id)

    def _on_route_to(self, agent_id: str, enriched_text: str):
        """
        Orchestrator chose an agent.  Deliver the enriched message to it.

        Look-ahead handoff
        ──────────────────
        If a *different* agent is being routed to while the current speaker is
        still mid-turn, we apply the look-ahead pattern instead of a hard cut:
          1. Deliver text to the incoming agent immediately so it starts generating.
          2. Put the incoming agent's audio on hold (buffer, don't play yet).
          3. Record the pending handoff — _on_agent_turn_complete will release it.

        The current speaker's audio continues uninterrupted. When its
        turn_complete fires, release() opens the hold gate and playback begins
        with zero perceptible gap.

        If the same agent is chosen, or no agent is currently speaking, the
        original instant-deliver path is used unchanged.
        """
        # Guard: signal may fire after stop() has cleared _agents
        if not self._agents:
            return

        if agent_id not in self._agents:
            agent_id = self._active_id
        # _active_id might also be stale — final safety net
        if agent_id not in self._agents:
            agent_id = next(iter(self._agents))

        current_agent = self._agents.get(self._active_id)
        switching     = agent_id != self._active_id
        current_speaking = switching and current_agent and current_agent.is_speaking and self.enable_lookahead

        if current_speaking:
            # ── Look-ahead path ───────────────────────────────────────────────
            # Cancel any pending timed release (a previous look-ahead resolved
            # or was superseded by this new routing decision).
            if self._pending_release_to_id:
                prev_to = self._pending_release_to_id
                self._pending_release_to_id = None
                prev_worker = self._agents.get(prev_to)
                if prev_worker:
                    prev_worker.release_audio()

            # Cancel any previous pending handoff cleanly.
            if self._pending_handoff:
                _, prev_pending_to = self._pending_handoff
                pending_worker = self._agents.get(prev_pending_to)
                if pending_worker:
                    pending_worker.release_audio()  # let it play if it had received audio

            # Start the incoming agent generating, but hold its audio.
            incoming = self._agents[agent_id]
            incoming.hold_audio()
            incoming.deliver_text(enriched_text)
            self._pending_handoff = (self._active_id, agent_id)
            self._handoff_poll_timer.start()   # begin polling the buffer

            # Emit routing note so the UI shows who is being prepared.
            name = next((p["name"] for p in AGENT_PERSONAS if p["id"] == agent_id), agent_id)
            self.routing_note.emit(f"⏳ {name} preparing (look-ahead)")
        else:
            # ── Instant handoff path (original behaviour) ─────────────────────
            if switching:
                if current_agent:
                    current_agent.interrupt()
                self.interrupted.emit(self._active_id)

            self._active_id = agent_id
            self.active_agent_changed.emit(agent_id)
            self._agents[agent_id].deliver_text(enriched_text)

            if self._recording:
                self.switch_mic_to(agent_id)

    def _check_pending_handoff(self):
        """Polling callback (50 ms interval).

        Waits for the current speaker's audio buffer to drain, then starts a
        random 3-5 s natural pause before releasing the incoming agent.
        The incoming agent's audio is already buffered and ready to play
        instantly when the pause expires — zero LLM wait on release.
        """
        if not self._pending_handoff:
            self._handoff_poll_timer.stop()
            return

        from_id, to_id = self._pending_handoff
        from_worker    = self._agents.get(from_id)

        if from_worker is None or from_worker._audio.buffered_seconds < 0.05:
            # Current speaker exhausted -- schedule the natural pause + release.
            self._pending_handoff = None
            self._handoff_poll_timer.stop()
            self._pending_release_to_id = to_id
            delay_ms = random.randint(self._MIN_PAUSE_MS, self._MAX_PAUSE_MS)
            QTimer.singleShot(delay_ms, self._do_release)

    def _do_release(self):
        """Called after the random pause expires.

        Releases the held agent and triggers deferred A2A immediately so the
        look-ahead chain continues: at release time the buffer is full and
        is_speaking = True, so the next routing takes the look-ahead path too.
        Cancellable: clear _pending_release_to_id before the timer fires.
        """
        to_id = self._pending_release_to_id
        if to_id is None:
            return  # cancelled by a newer routing decision
        self._pending_release_to_id = None

        incoming = self._agents.get(to_id)
        if incoming:
            self._active_id = to_id
            self.active_agent_changed.emit(to_id)
            incoming.release_audio()
            if self._orchestrator:
                self._orchestrator.set_last_active(to_id)
            if self._recording:
                self.switch_mic_to(to_id)

            if self._deferred_a2a == to_id:
                self._deferred_a2a = None
                self._run_a2a_for(to_id)

    def _run_a2a_for(self, agent_id: str):

        """Feed the agent's last transcript to the orchestrator for A2A detection.
        Extracted so it can be called from both _on_agent_turn_complete and
        _check_pending_handoff (deferred path) without duplication.
        """
        if not self._orchestrator:
            return

        all_recs   = self._log.read_all()
        transcript = ""
        agent_name = self._agents[agent_id].agent_name if agent_id in self._agents else ""
        for rec in reversed(all_recs):
            if rec.get("role") == "agent" and rec.get("agent") == agent_name:
                transcript = rec.get("text", "")
                break

        if not transcript:
            return

        self._orchestrator.route(
            transcript,
            source_type="agent",
            from_agent_id=agent_id,
        )

    def _on_agent_turn_complete(self, agent_id: str):
        """
        Transcript-Watcher: called when any agent's LLM turn completes.

        One-ahead enforcement
        ─────────────────────
        If this agent's audio is currently held (it's the *incoming* agent in
        a look-ahead handoff and hasn't started playing yet), running A2A
        detection NOW would start preparing the *next* reply while the current
        one hasn't been heard.  Instead we record the agent ID in _deferred_a2a
        and let _check_pending_handoff run it after the agent finishes playing.

        This enforces the invariant: at most ONE agent is ever being prepared
        ahead of time, regardless of how many agents exist in the system.
        """
        worker = self._agents.get(agent_id)
        if worker and worker._audio.is_held:
            # Agent is still in hold mode — defer A2A until it finishes playing.
            self._deferred_a2a = agent_id
            return

        # Normal path: agent has already started (or finished) playing.
        self._run_a2a_for(agent_id)