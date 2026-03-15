"""
arc/web/livekit_bridge.py
────────────────────────
LiveKit Bridge for the ARC Application.

Connects to a LiveKit Room and bridges audio AND events between the Room
and the PyQt6 SessionController, replacing the legacy WebSocket server.
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

logger = logging.getLogger(__name__)

class LiveKitBridge(QObject):
    # Signal to update the UI with connection state changes
    connection_state_changed = pyqtSignal(str)
    # Signal emitted from the background asyncio thread to deliver text to the
    # SessionController on the Qt main thread (queued cross-thread connection)
    _text_received = pyqtSignal(str)

    def __init__(self, room_name: str = "bidi-demo-room", participant_identity: str = "arc-agent"):
        super().__init__()
        self._controller: Optional[SessionController] = None
        self._room_name = room_name
        self._participant_identity = participant_identity
        
        self._room = rtc.Room()
        self._audio_source: Optional[rtc.AudioSource] = None
        self._audio_track: Optional[rtc.LocalAudioTrack] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        
        # Threading event to ensure the loop is ready before async calls are made
        self._loop_ready = threading.Event()

    @property
    def connection_state(self) -> str:
        state_map = {
            0: "disconnected",
            1: "connected",
            2: "connecting",
        }
        return state_map.get(self._room.connection_state, "disconnected")

    def attach(self, controller: SessionController):
        self._controller = controller
        logger.info("[LiveKit] Attached to SessionController")
        
        # Wire cross-thread text delivery: signal emitted from asyncio thread,
        # received by controller.send_text on the Qt main thread via queued connection.
        self._text_received.connect(controller.send_text)
        
        # Audio
        if hasattr(self._controller, "audio_chunk_generated"):
            self._controller.audio_chunk_generated.connect(self._on_agent_audio)
            
        # Events (Data Channel broadcasts)
        c = self._controller
        c.text_received.connect(
            lambda aid, text, partial: self._broadcast_json({
                "type": "text_chunk", "agent_id": aid, "text": text, "partial": partial
            })
        )
        c.input_transcription.connect(
            lambda text, finished: self._broadcast_json({
                "type": "transcription", "role": "user", "text": text, "finished": finished
            })
        )
        c.output_transcription.connect(
            lambda aid, text, finished: self._broadcast_json({
                "type": "transcription", "role": "agent", "agent_id": aid, "text": text, "finished": finished
            })
        )
        c.turn_complete.connect(
            lambda aid: self._broadcast_json({ "type": "turn_complete", "agent_id": aid })
        )
        c.routing_note.connect(
            lambda note: self._broadcast_json({ "type": "routing", "note": note })
        )
        c.agent_status.connect(
            lambda aid, status: self._broadcast_json({
                "type": "agent_status", "agent_id": aid, "status": status
            })
        )
        c.image_ready.connect(
            lambda path: self._broadcast_json({
                "type": "image_ready", "path": path
            })
        )

    # ── PyQT6 → LiveKit (Backend → Web) ────────────────────────────────────────

    def _on_agent_audio(self, agent_id: str, pcm_bytes: bytes):
        if not self._audio_source or not self._loop_ready.is_set():
            return

        samples_per_channel = len(pcm_bytes) // 2
        frame = rtc.AudioFrame(
            data=pcm_bytes,
            sample_rate=24000,
            num_channels=1,
            samples_per_channel=samples_per_channel
        )
        
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._audio_source.capture_frame(frame), self._loop
            )

    def _broadcast_json(self, data: dict):
        if not self._loop_ready.is_set() or not self._loop:
            return
            
        json_str = json.dumps(data)
        
        async def _publish():
            if self._room.connection_state == rtc.ConnectionState.Value("CONN_CONNECTED"):
                await self._room.local_participant.publish_data(
                    json_str.encode("utf-8"), 
                    topic="chat"
                )
                
        if self._loop.is_running():
            asyncio.run_coroutine_threadsafe(_publish(), self._loop)

    # ── LiveKit → PyQT6 (Web → Backend) ────────────────────────────────────────

    async def _handle_track_subscribed(self, track: rtc.Track, publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            audio_stream = rtc.AudioStream(track, sample_rate=16000, num_channels=1)
            async for event in audio_stream:
                if self._controller:
                    self._controller.inject_audio(bytes(event.frame.data))

    async def _handle_data_received(self, dp: rtc.DataPacket):
        # Log EVERY packet before any filtering so we can diagnose drops
        participant_id = dp.participant.identity if dp.participant else "<server>"
        logger.info(
            f"[LiveKit] data_received: topic={dp.topic!r}, "
            f"len={len(dp.data)}, from={participant_id}"
        )
        
        if not self._controller:
            logger.warning("[LiveKit] No controller attached – dropping packet")
            return
        if dp.topic != "chat":
            logger.debug(f"[LiveKit] Ignoring packet on topic {dp.topic!r}")
            return
            
        try:
            payload = json.loads(dp.data.decode("utf-8"))
            msg_type = payload.get("type")
            logger.info(f"[LiveKit] Parsed message type={msg_type!r} payload={payload}")
            if msg_type == "text":
                text = payload.get("text", "").strip()
                if text:
                    logger.info(f"[LiveKit] Forwarding text to controller: {text!r}")
                    # Emit signal instead of calling directly — this crosses the
                    # asyncio-thread → Qt-main-thread boundary safely via Qt queued connection.
                    self._text_received.emit(text)
                else:
                    logger.warning("[LiveKit] Received 'text' message with empty text")
        except Exception as e:
            logger.error(f"[LiveKit] Error decoding data channel msg: {e}", exc_info=True)

    # ── Main Loop ──────────────────────────────────────────────────────────────

    async def run(self):
        self._loop = asyncio.get_running_loop()
        self._loop_ready.set()
        
        url = os.environ.get("LIVEKIT_URL")
        api_key = os.environ.get("LIVEKIT_API_KEY")
        api_secret = os.environ.get("LIVEKIT_API_SECRET")
        
        if not all([url, api_key, api_secret]):
            logger.error("[LiveKit] Missing config.")
            return

        token = api.AccessToken(api_key, api_secret) \
            .with_identity(self._participant_identity) \
            .with_grants(api.VideoGrants(
                room_join=True,
                room=self._room_name,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )).to_jwt()

        @self._room.on("track_subscribed")
        def on_track_subscribed(track, pub, participant):
            asyncio.create_task(self._handle_track_subscribed(track, pub, participant))
            
        @self._room.on("data_received")
        def on_data_received(dp):
            if self._loop:
                self._loop.create_task(self._handle_data_received(dp))

        @self._room.on("connection_state_changed")
        def on_connection_state_changed(state):
            self.connection_state_changed.emit(self.connection_state)

        self._audio_source = rtc.AudioSource(24000, 1)
        self._audio_track = rtc.LocalAudioTrack.create_audio_track("agent-audio", self._audio_source)

        try:
            await self._room.connect(url, token)
            self.connection_state_changed.emit("connected")
            await self._room.local_participant.publish_track(self._audio_track)
            
            while True:
                await asyncio.sleep(3600)
        except Exception as e:
            logger.error(f"[LiveKit] Error: {e}")
        finally:
            await self._room.disconnect()
            self.connection_state_changed.emit("disconnected")

    def start_background(self):
        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.run())
            except: pass
            finally: loop.close()
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return t
