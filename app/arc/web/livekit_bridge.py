"""
arc/web/livekit_bridge.py
────────────────────────
LiveKit Bridge for the ARC Application.

FIX HISTORY
───────────
2025-03-16  Root-cause fix (data_received + audio both silent):

  rtc.Room() was constructed in __init__ on the Qt main thread, before the
  background asyncio loop existed.  The LiveKit FFI client binds its event
  queue to the loop that is *running at Room construction time*.  On the main
  thread that loop is Qt's — so every incoming event (data_received,
  track_subscribed, audio frames) was dispatched into Qt and silently dropped.

  Audio send appeared to work only because _on_agent_audio uses
  run_coroutine_threadsafe(audio_source.capture_frame(), self._loop) which
  bypasses the Room's internal FFI queue — but in fact the track was never
  published (publish_track also needs the right loop), so remote participants
  received silence.

  Fixes applied:
    1. rtc.Room() moved inside run() — guarantees FFI queue binds to the
       background asyncio loop.
    2. _loop_ready is set AFTER AudioSource is created — _on_agent_audio
       can't race ahead and hit a None audio_source.
    3. ConnectionState comparison fixed: use .Value("CONN_CONNECTED") which
       is the protobuf-generated accessor, not the plain attribute access
       (.CONN_CONNECTED) that doesn't exist on older SDK versions.
    4. attach() disconnects all signals from the previous controller before
       re-wiring, preventing duplicate event firing across session restarts.
"""

import asyncio
import json
import logging
import os
import threading
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal
from livekit import rtc, api
from ..agents.session_controller import SessionController
from PyQt6 import sip

logger = logging.getLogger(__name__)


class LiveKitBridge(QObject):
    connection_state_changed = pyqtSignal(str)
    _text_received = pyqtSignal(str)

    def __init__(
        self,
        room_name: str = "bidi-demo-room",
        participant_identity: str = "arc-agent",
    ):
        super().__init__()
        self._controller: Optional[SessionController] = None
        self._room_name = room_name
        self._participant_identity = participant_identity

        # NOTE: self._room is created inside run(), NOT here.
        # Creating it here would bind the LiveKit FFI event queue to the Qt
        # main-thread loop, causing all inbound events to be silently dropped.
        self._room: Optional[rtc.Room] = None
        self._audio_source: Optional[rtc.AudioSource] = None
        self._audio_track: Optional[rtc.LocalAudioTrack] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Set only after both self._room AND self._audio_source exist.
        # Guards _on_agent_audio and _broadcast_json from running too early.
        self._loop_ready = threading.Event()

        self._pending_packets: list = []
        self._shutdown_event: Optional[asyncio.Event] = None
        self._audio_queue: Optional[asyncio.Queue[rtc.AudioFrame]] = None

    def _safe_emit(self, signal: pyqtSignal, *args):
        """Emit a signal ONLY if this QObject has not been deleted by C++."""
        try:
            if not sip.isdeleted(self):
                signal.emit(*args)
        except (RuntimeError, ReferenceError):
            # Still might catch the "wrapped C/C++ object has been deleted"
            # if it's deleted between the check and the emit.
            pass

    @property
    def connection_state(self) -> str:
        if self._room is None:
            return "disconnected"
        state_map = {0: "disconnected", 1: "connected", 2: "connecting"}
        return state_map.get(self._room.connection_state, "disconnected")

    # ── attach / detach ────────────────────────────────────────────────────

    def attach(self, controller: SessionController):
        """Wire a (new) SessionController to the bridge.

        Safe to call multiple times — disconnects the previous controller's
        signals first so restarts don't accumulate duplicate connections.
        """
        if self._controller is not None:
            try:
                self._text_received.disconnect(self._controller.send_text)
            except RuntimeError:
                pass
            for sig_name in (
                "audio_chunk_generated",
                "text_received",
                "input_transcription",
                "output_transcription",
                "turn_complete",
                "routing_note",
                "agent_status",
                "image_ready",
            ):
                sig = getattr(self._controller, sig_name, None)
                if sig is not None:
                    try:
                        sig.disconnect()
                    except RuntimeError:
                        pass

        self._controller = controller
        logger.info("[LiveKit] Attached to SessionController")

        # Cross-thread text delivery: asyncio thread → Qt main thread
        self._text_received.connect(controller.send_text)

        # PyQt6 agent audio → LiveKit room → web clients
        if hasattr(controller, "audio_chunk_generated"):
            controller.audio_chunk_generated.connect(self._on_agent_audio)

        # Session events → Data Channel broadcasts to web clients
        c = controller
        c.text_received.connect(
            lambda aid, text, partial: self._broadcast_json(
                {"type": "text_chunk", "agent_id": aid, "text": text, "partial": partial}
            )
        )
        c.input_transcription.connect(
            lambda text, finished: self._broadcast_json(
                {"type": "transcription", "role": "user", "text": text, "finished": finished}
            )
        )
        c.output_transcription.connect(
            lambda aid, text, finished: self._broadcast_json(
                {
                    "type": "transcription",
                    "role": "agent",
                    "agent_id": aid,
                    "text": text,
                    "finished": finished,
                }
            )
        )
        c.turn_complete.connect(
            lambda aid: self._broadcast_json({"type": "turn_complete", "agent_id": aid})
        )
        c.routing_note.connect(
            lambda note: self._broadcast_json({"type": "routing", "note": note})
        )
        c.agent_status.connect(
            lambda aid, status: self._broadcast_json(
                {"type": "agent_status", "agent_id": aid, "status": status}
            )
        )
        c.image_ready.connect(
            lambda path: self._broadcast_json({"type": "image_ready", "path": path})
        )

        # Flush packets that arrived before attach() was called
        if self._pending_packets:
            logger.info(
                "[LiveKit] Flushing %d queued packet(s) to controller",
                len(self._pending_packets),
            )
            pending, self._pending_packets = self._pending_packets[:], []
            for dp in pending:
                if self._loop and self._loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._handle_data_received(dp), self._loop
                    )

    # ── PyQt6 → LiveKit (agent audio out) ─────────────────────────────────

    def _on_agent_audio(self, agent_id: str, pcm_bytes: bytes):
        # _loop_ready is set only after _audio_source exists — no None race.
        if not self._loop_ready.is_set() or self._audio_queue is None:
            return
        samples_per_channel = len(pcm_bytes) // 2
        frame = rtc.AudioFrame(
            data=pcm_bytes,
            sample_rate=24000,
            num_channels=1,
            samples_per_channel=samples_per_channel,
        )
        # Instead of capturing immediately (which "bursts"), we queue for the pacer
        self._loop.call_soon_threadsafe(self._audio_queue.put_nowait, frame)

    # ── PyQt6 → LiveKit (event broadcasts) ────────────────────────────────

    def _broadcast_json(self, data: dict):
        if not self._loop_ready.is_set() or not self._loop or not self._room:
            return

        json_bytes = json.dumps(data).encode("utf-8")

        async def _publish():
            try:
                # Use protobuf accessor — .CONN_CONNECTED does not exist in
                # older livekit-rtc versions and silently evaluates to 0.
                connected = (
                    self._room.connection_state
                    == rtc.ConnectionState.Value("CONN_CONNECTED")
                )
                if connected:
                    await self._room.local_participant.publish_data(
                        json_bytes,
                        reliable=True,
                        topic="chat",
                    )
            except Exception as exc:
                logger.error("[LiveKit] publish_data error: %s", exc)

        asyncio.run_coroutine_threadsafe(_publish(), self._loop)

    # ── LiveKit → PyQt6 (web audio in) ────────────────────────────────────

    async def _handle_track_subscribed(
        self,
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            audio_stream = rtc.AudioStream(track, sample_rate=16000, num_channels=1)
            async for event in audio_stream:
                if sip.isdeleted(self):
                    break
                if self._controller:
                    self._controller.inject_audio(bytes(event.frame.data))

    # ── LiveKit → PyQt6 (data channel in) ─────────────────────────────────

    async def _handle_data_received(self, dp: rtc.DataPacket):
        try:
            participant_id = dp.participant.identity if dp.participant else "<server>"
        except Exception:
            participant_id = "<unknown>"

        logger.info(
            "[LiveKit] data_received: topic=%r len=%d from=%s",
            dp.topic,
            len(dp.data),
            participant_id,
        )

        if sip.isdeleted(self):
            return

        if not self._controller:
            logger.warning("[LiveKit] Controller not attached — queuing packet")
            self._pending_packets.append(dp)
            return

        if dp.topic != "chat":
            logger.debug("[LiveKit] Ignoring packet on topic %r", dp.topic)
            return

        try:
            payload = json.loads(dp.data.decode("utf-8"))
        except Exception as exc:
            logger.error("[LiveKit] Failed to decode data packet: %s", exc)
            return

        msg_type = payload.get("type")
        logger.info("[LiveKit] Parsed type=%r payload=%s", msg_type, payload)

        if msg_type == "text":
            text = payload.get("text", "").strip()
            if text:
                logger.info("[LiveKit] Forwarding to controller: %r", text)
                self._safe_emit(self._text_received, text)
            else:
                logger.warning("[LiveKit] Empty text in 'text' message")

    # ── Main async loop ────────────────────────────────────────────────────

    async def run(self):
        # 1. Capture the running loop FIRST.
        self._loop = asyncio.get_running_loop()
        self._shutdown_event = asyncio.Event()

        # 2. Create Room while this loop is running so the FFI event queue
        #    binds to it.  This is the single most important ordering constraint.
        self._room = rtc.Room()

        # 3. Create AudioSource/Track — must exist before _loop_ready is set.
        self._audio_source = rtc.AudioSource(24000, 1)
        self._audio_track = rtc.LocalAudioTrack.create_audio_track(
            "agent-audio", self._audio_source
        )
        self._audio_queue = asyncio.Queue()

        # 4. Signal readiness — from this point _on_agent_audio and
        #    _broadcast_json are safe to run.
        self._loop_ready.set()

        # 5. Start the Pacer Loop
        pacer_task = asyncio.create_task(self._pacer_loop())

        url = os.environ.get("LIVEKIT_URL")
        api_key = os.environ.get("LIVEKIT_API_KEY")
        api_secret = os.environ.get("LIVEKIT_API_SECRET")

        if not all([url, api_key, api_secret]):
            logger.error(
                "[LiveKit] Missing env vars: LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET"
            )
            return

        token = (
            api.AccessToken(api_key, api_secret)
            .with_identity(self._participant_identity)
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=self._room_name,
                    can_publish=True,
                    can_subscribe=True,
                    can_publish_data=True,
                )
            )
            .to_jwt()
        )

        # Register handlers BEFORE connecting so no events are missed.
        @self._room.on("track_subscribed")
        def on_track_subscribed(track, pub, participant):
            asyncio.ensure_future(
                self._handle_track_subscribed(track, pub, participant)
            )

        @self._room.on("data_received")
        def on_data_received(dp: rtc.DataPacket):
            if not sip.isdeleted(self):
                asyncio.ensure_future(self._handle_data_received(dp))

        @self._room.on("connection_state_changed")
        def on_connection_state_changed(state):
            if not sip.isdeleted(self):
                self._safe_emit(self.connection_state_changed, self.connection_state)

        try:
            await self._room.connect(url, token)
            self._safe_emit(self.connection_state_changed, "connected")
            logger.info("[LiveKit] Connected to room %r", self._room_name)

            # Publish the audio track so web clients can hear agents.
            await self._room.local_participant.publish_track(self._audio_track)
            logger.info("[LiveKit] Audio track published")

            # Wait until stopped
            await self._shutdown_event.wait()
            logger.info("[LiveKit] Shutdown event received")

        except Exception as exc:
            logger.error("[LiveKit] Fatal error: %s", exc, exc_info=True)
        finally:
            self._loop_ready.clear()
            pacer_task.cancel()
            try:
                await pacer_task
            except asyncio.CancelledError:
                pass
            if self._room:
                await self._room.disconnect()
            self._safe_emit(self.connection_state_changed, "disconnected")

    async def _pacer_loop(self):
        """
        Pacer Loop: pulling AudioFrames from the queue and sending them to 
        LiveKit at the correct real-time frequency to avoid "bursting".
        """
        while True:
            try:
                if self._audio_queue is None:
                    await asyncio.sleep(0.1)
                    continue

                frame = await self._audio_queue.get()
                
                # Calculate duration of this frame to know how long to wait
                # duration = samples / sample_rate
                duration_s = frame.samples_per_channel / frame.sample_rate
                
                start_time = asyncio.get_event_loop().time()
                
                if self._audio_source:
                    await self._audio_source.capture_frame(frame)
                
                # Wait for the duration of the frame minus capture time
                elapsed = asyncio.get_event_loop().time() - start_time
                wait_time = max(0, duration_s - elapsed)
                
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                
                self._audio_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[LiveKit] Pacer loop error: %s", e)
                await asyncio.sleep(0.1)

    def stop(self):
        """Signal the background thread to exit and wait for it."""
        if self._loop and self._shutdown_event:
            self._loop.call_soon_threadsafe(self._shutdown_event.set)
        logger.info("[LiveKit] Requested bridge shutdown")

    def start_background(self):
        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.run())
            except Exception as exc:
                logger.error(
                    "[LiveKit] Background thread crashed: %s", exc, exc_info=True
                )
            finally:
                loop.close()

        t = threading.Thread(target=_run, daemon=True, name="livekit-bridge")
        t.start()
        return t