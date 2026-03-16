"""
arc/agents/live_agent.py
────────────────────────
LiveAgentWorker — one QThread per live specialist agent.

The agent's only job is to generate content.  All handoff detection has
been moved to OrchestratorWorker (Transcript-Watcher pattern):
  • At turnComplete, SessionController reads the finalized transcript from
    the mmap and calls orchestrator.route(..., source_type="agent").
  • The orchestrator decides whether a peer was invited to speak and emits
    route_to if so — using the same path as user-turn routing.

The agent knows nothing about handoffs.  It simply speaks naturally.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
import uuid

import numpy as np
import sounddevice as sd
from PyQt6.QtCore import QThread, pyqtSignal

from google.adk.agents import Agent
from google.adk.tools import google_search, FunctionTool
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from ..core.audio import AudioOutputManager
from ..core.config import (
    APP_NAME, SR_IN,
    GEMINI_ENV,
    LIVE_MODEL_GEMINI,
)
from ..core.shared_memory import SharedConversationLog
from ..shared.session_bus import SessionBus, SessionBusWatcher
from ..subagents.computer_use.agent import run_computer_use_background
from ..subagents.image_generation.agent import run_image_generation_background

logger = logging.getLogger(__name__)



class LiveAgentWorker(QThread):
    """
    Signals
    ───────
        text_received(str, bool)           text chunk, is_partial
        input_transcription(str, bool)     user speech text, is_finished
        output_transcription(str, bool)    agent speech text, is_finished
        turn_complete()
        interrupted()
        agent_speaking(bool)
        event_logged(dict)
        status_changed(str)
        error_occurred(str)
        audio_chunk(bytes)                 raw pcm bytes
        image_ready(str)                   absolute path to generated image
    """

    text_received        = pyqtSignal(str, bool)
    input_transcription  = pyqtSignal(str, bool)
    output_transcription = pyqtSignal(str, bool)
    turn_complete        = pyqtSignal()
    interrupted          = pyqtSignal()
    agent_speaking       = pyqtSignal(bool)
    event_logged         = pyqtSignal(dict)
    status_changed       = pyqtSignal(str)
    error_occurred       = pyqtSignal(str)
    audio_chunk          = pyqtSignal(bytes)  # Emitted when agent generates an audio frame
    image_ready          = pyqtSignal(str)    # Absolute path to the generated image file
    cu_logged            = pyqtSignal(dict)   # Emitted for Computer Use subagent events
    img_logged           = pyqtSignal(dict)   # Emitted for Image Generation subagent events

    def __init__(
        self,
        persona: dict,
        shared_log: SharedConversationLog,
        startup_delay: float = 0.0,
    ):
        super().__init__()
        self.persona          = persona
        self.agent_id: str    = persona["id"]
        self.agent_name: str  = persona["name"]
        self._startup_delay   = startup_delay

        # Shared mmap log — same object across all workers + orchestrator
        self._log: SharedConversationLog = shared_log

        self.user_id    = "arc-user"
        self.session_id = f"arc-{self.agent_id}-{uuid.uuid4().hex[:6]}"
        self.setObjectName(f"Worker-{self.agent_name}")

        self._loop:      asyncio.AbstractEventLoop | None = None
        self._queue:     asyncio.Queue | None             = None
        self._lrq:       LiveRequestQueue | None          = None
        self._session_ready: asyncio.Event | None         = None
        self._audio      = AudioOutputManager()
        self._mic:       sd.InputStream | None            = None
        self._recording  = False
        self._alive      = False
        
        # ── Mark-like capabilities (All agents now have these) ────────────────
        # Shared action bus — written by background tasks, read by watcher
        self._bus = SessionBus()

        # Mutable refs — FunctionTools write to these before setting their events
        self._cu_task_ref:    list[str] = [""]
        self._img_prompt_ref: list[str] = [""]

        # asyncio.Event gates — set via loop.call_soon_threadsafe from tool callbacks
        self._cu_trigger:  asyncio.Event | None = None
        self._img_trigger: asyncio.Event | None = None

        # asyncio.Task handles — stored for .cancel() on shutdown
        self._cu_bg_task:  asyncio.Task | None = None
        self._img_bg_task: asyncio.Task | None = None

        # Track last img_status so we emit image_ready exactly once
        self._last_img_status: str = "idle"
        
        # Track turns to avoid duplicate history bugs
        self._turns_in_current_session = 0

        # Accumulate the FULL output transcript for the current turn.
        # Reset at each turnComplete / interrupted event.
        self._turn_transcript: str = ""

        # True while this agent is mid-turn (has received audio chunks but
        # turn_complete has not fired yet).  Used by SessionController to
        # decide whether to apply look-ahead hold or immediate handoff.
        self._turn_in_progress: bool = False

        # Wall-clock time (monotonic) of the most recent audio chunk fed to
        # the output buffer.  Used to implement a grace window in is_speaking
        # so that Gemini's streaming audio (which drains in real-time) still
        # triggers look-ahead even when the buffer is momentarily empty.
        self._last_audio_ts: float = 0.0

    # ── Public API ────────────────────────────────────────────────────────────

    def deliver_text(self, text: str):
        self._put({"type": "text", "text": text})

    def deliver_audio(self, raw_pcm: bytes):
        self._put({"type": "audio", "data": raw_pcm})

    def deliver_image(self, jpeg_bytes: bytes):
        self._put({
            "type": "image",
            "data": base64.b64encode(jpeg_bytes).decode(),
            "mime": "image/jpeg",
        })

    def start_recording(self):
        if self._recording:
            return
        self._recording = True

        def _cb(indata, frames, time, status):
            if self._recording and self._loop and self._queue:
                raw = (indata[:, 0] * 32767).astype(np.int16).tobytes()
                self._loop.call_soon_threadsafe(
                    self._queue.put_nowait, {"type": "audio", "data": raw})

        try:
            self._mic = sd.InputStream(
                samplerate=SR_IN, channels=1, dtype="float32",
                blocksize=1024, callback=_cb,
            )
            self._mic.start()
        except Exception as exc:
            self._recording = False
            self.error_occurred.emit(f"Mic [{self.agent_name}]: {exc}")

    def stop_recording(self):
        self._recording = False
        if self._mic:
            self._mic.stop()
            self._mic.close()
            self._mic = None

    def interrupt(self):
        """Hard interrupt: clear audio buffer and reset — peer takes over immediately."""
        self._audio.clear()   # also releases hold if any
        self._reset_turn()
        self.agent_speaking.emit(False)

    def hold_audio(self):
        """Gate this agent's audio output (buffer without playing).

        Called by SessionController on the *incoming* agent so it can
        start generating while the *current* agent finishes speaking.
        """
        self._audio.hold()

    def release_audio(self):
        """Release the hold gate — buffered audio starts playing immediately."""
        self._audio.release()

    @property
    def is_speaking(self) -> bool:
        """True while the agent is generating OR still has audio buffered/recently active.

        The 0.5 s grace window (AUDIO_GRACE_S) covers Gemini's streaming mode
        where audio chunks drain in real-time: by the time the routing signal
        chain reaches _on_route_to, the buffer can already read as 0.
        The grace ensures the look-ahead path fires consistently on both backends.
        """
        AUDIO_GRACE_S = 3.0
        recent_audio  = (time.monotonic() - self._last_audio_ts) < AUDIO_GRACE_S
        return self._turn_in_progress or self._audio.buffered_seconds > 0 or recent_audio

    def shutdown(self):
        logger.info("[%s] Shutdown requested", self.agent_name)
        self._alive = False
        self.stop_recording()
        if self._loop:
            if self._cu_bg_task and not self._cu_bg_task.done():
                self._loop.call_soon_threadsafe(self._cu_bg_task.cancel)
            if self._img_bg_task and not self._img_bg_task.done():
                self._loop.call_soon_threadsafe(self._img_bg_task.cancel)
            if self._queue:
                self._loop.call_soon_threadsafe(
                    self._queue.put_nowait, {"type": "stop"})

    # ── QThread ───────────────────────────────────────────────────────────────

    def run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._alive = True
        try:
            self._loop.run_until_complete(self._main())
        except Exception as exc:
            self.error_occurred.emit(str(exc))
        finally:
            try:
                pending = asyncio.all_tasks(self._loop)
                if pending:
                    for t in pending:
                        t.cancel()
                    self._loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True))
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            except Exception:
                pass
            self._loop.close()
            self._loop = None

    # ── Asyncio main ──────────────────────────────────────────────────────────

    def _put(self, msg: dict):
        if self._loop and self._queue:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, msg)

    async def _main(self):
        MAX_RETRIES  = 6
        BASE_DELAY   = 2.0
        MAX_DELAY    = 30.0

        if self._startup_delay > 0:
            await asyncio.sleep(self._startup_delay)

        self._queue = asyncio.Queue()

        # ── Backend selection ─────────────────────────────────────────────────
        os.environ.update(GEMINI_ENV)
        chosen_model = LIVE_MODEL_GEMINI
        
        # ── Capture the running loop (before tools are defined)
        loop = asyncio.get_running_loop()

        # ── asyncio Events initialised here (inside the loop) ─────────────────
        self._cu_trigger  = asyncio.Event()
        self._img_trigger = asyncio.Event()

        # ── ADK FunctionTools ─────────────────────────────────────────────────
        def trigger_computer_use(task: str) -> str:
            """
            Trigger the Computer Use background agent.
            Call this when the user asks you to interact with a computer,
            open apps, browse websites, fill forms, or automate any desktop task.
            """
            self._cu_task_ref[0] = task
            loop.call_soon_threadsafe(self._cu_trigger.set)
            logger.info("[%s] Triggered Computer Use: %s", self.agent_name, task[:80])
            return f"Computer Use task started: {task[:60]}"

        def trigger_image_generation(prompt: str) -> str:
            """
            Generate an image using the Imagen model.
            Call this when the user asks you to create, generate, or draw an image.
            """
            self._img_prompt_ref[0] = prompt
            loop.call_soon_threadsafe(self._img_trigger.set)
            logger.info("[%s] Triggered Image Generation: %s", self.agent_name, prompt[:80])
            return f"Image generation started for: {prompt[:60]}"

        agent_tools  = [
            google_search,
            FunctionTool(trigger_computer_use),
            FunctionTool(trigger_image_generation),
        ]

        _agent = Agent(
            name=f"arc_{self.agent_id}",
            model=chosen_model,
            tools=agent_tools,
            instruction=self.persona["instruction"],
        )
        svc    = InMemorySessionService()
        runner = Runner(app_name=APP_NAME, agent=_agent, session_service=svc)
        await svc.create_session(
            app_name=APP_NAME, user_id=self.user_id, session_id=self.session_id)

        is_native = "native-audio" in chosen_model.lower() or "live" in chosen_model.lower()
        if is_native:
            # Gemini AI Studio supports session resumption, proactivity, and affective options
            cfg = RunConfig(
                streaming_mode=StreamingMode.BIDI,
                response_modalities=["AUDIO"],
                input_audio_transcription=types.AudioTranscriptionConfig(),
                output_audio_transcription=types.AudioTranscriptionConfig(),
                session_resumption=types.SessionResumptionConfig(),
                # Context window compression — keeps long sessions alive
                context_window_compression=types.ContextWindowCompressionConfig(
                    trigger_tokens=32_000,
                    sliding_window=types.SlidingWindow(
                        target_tokens=16_000,
                    ),
                ),
            )
        else:
            cfg = RunConfig(
                streaming_mode=StreamingMode.BIDI,
                response_modalities=["TEXT"],
                session_resumption=types.SessionResumptionConfig(),
                # Context window compression for text models as well
                context_window_compression=types.ContextWindowCompressionConfig(
                    trigger_tokens=32_000,
                    sliding_window=types.SlidingWindow(
                        target_tokens=16_000,
                    ),
                ),
            )

        attempt = 0
        while self._alive and attempt < MAX_RETRIES:
            self.status_changed.emit("connecting")

            try:
                self._turns_in_current_session = 0
                self._session_ready = asyncio.Event()
                self._lrq = LiveRequestQueue()
                self._audio.start()
                self.status_changed.emit("connected")

                # ── Background tasks — wrapped in create_task for .cancel() ✓
                self._cu_bg_task  = asyncio.create_task(
                    run_computer_use_background(
                        self._bus,
                        self._cu_trigger,
                        self._cu_task_ref,
                        on_event=lambda ev: self.cu_logged.emit(ev)
                    ),
                    name=f"{self.agent_id}-computer-use",
                )
                self._img_bg_task = asyncio.create_task(
                    run_image_generation_background(
                        self._bus,
                        self._img_trigger,
                        self._img_prompt_ref,
                        on_event=lambda ev: self.img_logged.emit(ev)
                    ),
                    name=f"{self.agent_id}-image-gen",
                )

                # ── Bus watcher — inject milestones into LRQ ───────────
                watcher = SessionBusWatcher()
                watcher_task = asyncio.create_task(
                    watcher.run(self._bus, self._lrq),
                    name=f"{self.agent_id}-bus-watcher",
                )

                # ── Image-ready monitor — polls bus for img completion ─────────
                monitor_task = asyncio.create_task(
                    self._monitor_image_completion(),
                    name=f"{self.agent_id}-img-monitor",
                )

                up_task   = asyncio.ensure_future(self._upstream())
                down_task = asyncio.ensure_future(self._downstream(runner, cfg))
                try:
                    done, pending = await asyncio.wait(
                        {up_task, down_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    # Ensure exceptions are propagated to the retry logic
                    for t in done:
                        if not t.cancelled() and t.exception():
                            raise t.exception()
                finally:
                    # Cancel all background tasks on session end
                    for t in (
                        up_task, down_task,
                        self._cu_bg_task, self._img_bg_task,
                        watcher_task, monitor_task,
                    ):
                        if t and not t.done():
                            t.cancel()
                            try:
                                await t
                            except (asyncio.CancelledError, Exception):
                                pass

                # Stream exited cleanly (common for Vertex after turns)
                self._lrq.close()
                self._audio.stop()
                
                if not self._alive:
                    break
                
                # Reconnect seamlessly without killing the agent thread
                await asyncio.sleep(0.2)
                # Reset Events so background tasks can be re-triggered
                self._cu_trigger  = asyncio.Event()
                self._img_trigger = asyncio.Event()
                attempt = 0
                continue

            except asyncio.CancelledError:
                self._lrq.close()
                self._audio.stop()
                break

            except Exception as exc:
                err_str = str(exc)
                self._audio.clear()
                try:
                    self._lrq.close()
                except Exception:
                    pass
                self._audio.stop()

                if not self._alive:
                    break

                is_transient = any(kw in err_str for kw in (
                    "1011", "service is currently unavailable",
                    "503", "UNAVAILABLE", "connection closed",
                    "Connection closed",
                    "no close frame received or sent",
                    "ConnectionClosed", "ConnectionClosedError",
                    "ConnectionResetError", "connection reset",
                    "EOF occurred", "BrokenPipe",
                ))

                attempt += 1
                if is_transient and attempt < MAX_RETRIES:
                    delay = min(BASE_DELAY * (2 ** (attempt - 1)), MAX_DELAY)
                    logger.warning(
                        "[%s] Transient error (attempt %d/%d), retrying in %.1fs: %s",
                        self.agent_name, attempt, MAX_RETRIES, delay, err_str)
                    self.status_changed.emit("reconnecting")
                    await asyncio.sleep(delay)
                else:
                    self.error_occurred.emit(
                        f"[{self.agent_name}] Connection failed after "
                        f"{attempt} attempts: {err_str}")
                    break

        if self._alive:
            self.status_changed.emit("disconnected")

    async def _upstream(self):
        # Prevent deadlock on Vertex AI connecting stream
        if self._session_ready:
            try:
                await asyncio.wait_for(self._session_ready.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass 

        while self._alive:
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            t = msg["type"]
            if t == "stop":
                break
            elif t == "text":
                text_to_send = msg["text"]

                self._turns_in_current_session += 1
                self._lrq.send_content(
                    types.Content(role="user", parts=[types.Part(text=text_to_send)])
                )
            
            elif t == "audio":
                self._turns_in_current_session += 1
                self._lrq.send_realtime(
                    types.Blob(mime_type="audio/pcm;rate=16000", data=msg["data"]))
            
            elif t == "image":
                self._turns_in_current_session += 1
                self._lrq.send_realtime(
                    types.Blob(mime_type=msg["mime"],
                                data=base64.b64decode(msg["data"])))

    async def _downstream(self, runner: Runner, cfg: RunConfig):
        first_event = True
        async for event in runner.run_live(
            user_id=self.user_id,
            session_id=self.session_id,
            live_request_queue=self._lrq,
            run_config=cfg,
        ):
            if first_event:
                first_event = False
                if self._session_ready and not self._session_ready.is_set():
                    self._session_ready.set()
            try:
                if hasattr(event, "model_dump_json"):
                    ev = json.loads(event.model_dump_json(exclude_none=True, by_alias=True))
                elif hasattr(event, "model_dump"):
                    ev = event.model_dump(exclude_none=True, by_alias=True)
                elif isinstance(event, dict):
                    ev = event
                else:
                    ev = json.loads(str(event))
            except Exception:
                continue
                
            self.event_logged.emit(ev)
            self._handle(ev)

    # ── Event handling ────────────────────────────────────────────────────────

    def _handle(self, ev: dict):

        # ── Turn complete ─────────────────────────────────────────────────────
        if ev.get("turnComplete"):
            if self._turn_transcript:
                self._log.append("agent", self.agent_name, self._turn_transcript)
            self._reset_turn()
            self.agent_speaking.emit(False)
            self.turn_complete.emit()
            return

        # ── Interrupted ───────────────────────────────────────────────────────
        if ev.get("interrupted"):
            self._audio.clear()
            self._reset_turn()
            self.agent_speaking.emit(False)
            self.interrupted.emit()
            return

        # ── User speech transcription ─────────────────────────────────────────
        if it := ev.get("inputTranscription"):
            if t := it.get("text"):
                self.input_transcription.emit(t, it.get("finished", False))

        # ── Agent speech transcription — accumulate full turn text ────────────
        if ot := ev.get("outputTranscription"):
            if t := ot.get("text"):
                self.agent_speaking.emit(True)
                self._turn_transcript += t
                self.output_transcription.emit(t, ot.get("finished", False))

        # ── Audio / text content ──────────────────────────────────────────────
        if c := ev.get("content"):
            partial = ev.get("partial", False)
            for part in c.get("parts",[]):

                # ── Audio ─────────────────────────────────────────────────────
                if "inlineData" in part:
                    d = part["inlineData"]
                    if "audio" in d.get("mimeType", "") and "data" in d:
                        b64 = d["data"].replace("-", "+").replace("_", "/")
                        pad = (4 - len(b64) % 4) % 4
                        try:
                            pcm_bytes = base64.b64decode(b64 + "=" * pad)
                            # Emit chunk to WS prior to local feed
                            self.audio_chunk.emit(pcm_bytes)
                            
                            self._audio.feed(pcm_bytes)
                            self._turn_in_progress = True
                            self._last_audio_ts    = time.monotonic()
                            self.agent_speaking.emit(True)
                        except Exception:
                            pass

                # ── Text ──────────────────────────────────────────────────────
                if "text" in part and not part.get("thought"):
                    self.agent_speaking.emit(True)
                    self.text_received.emit(part["text"], partial)

    def _reset_turn(self):
        self._turn_transcript = ""
        self._turn_in_progress = False

    # ── Image completion monitor ───────────────────────────────────────────────

    async def _monitor_image_completion(self):
        """
        Lightweight async loop that watches for img_status == 'completed'
        on the SessionBus and emits the image_ready pyqtSignal.

        Runs inside the agent's asyncio loop. Cancelled automatically when
        the session ends (via the task cancel in _main).
        """
        while True:
            try:
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                return

            current_status = self._bus.get("img_status", "idle")
            if current_status == "completed" and self._last_img_status != "completed":
                path = self._bus.get("img_result", "")
                if path:
                    # Emit on Qt thread via signal — safe even from asyncio loop
                    # because PyQt6 signals are thread-safe at emit time.
                    self.image_ready.emit(path)
                    logger.info("[%s] image_ready emitted: %s", self.agent_name, path)

            self._last_img_status = current_status