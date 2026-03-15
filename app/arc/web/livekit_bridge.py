"""
arc/web/livekit_bridge.py
────────────────────────
LiveKit Bridge for the ARC Application.

Connects to a LiveKit Room and bridges audio AND events between the Room
and the PyQt6 SessionController, replacing the legacy WebSocket server.
- Receives user Opus audio from LiveKit, decodes to PCM, injects into SessionController.
- Receives agent PCM audio from SessionController, encodes to Opus, pushes to LiveKit.
- Receives text/events via LiveKit Data Channels from the web UI.
- Broadcasts agent text/events via LiveKit Data Channels to the web UI.
"""

import asyncio
import json
import logging
import os
import threading
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal
from livekit import api, rtc
from ..agents.session_controller import SessionController

logger = logging.getLogger(__name__)

class LiveKitBridge(QObject):
    # Signal to update the UI with connection state changes
    connection_state_changed = pyqtSignal(str)

    def __init__(self, room_name: str = "bidi-demo-room", participant_identity: str = "arc-agent"):
        super().__init__()
        self._controller: Optional[SessionController] = None
        self._room_name = room_name
        self._participant_identity = participant_identity
        
        self._frames_received = 0
        self._room = rtc.Room()
        self._audio_source: Optional[rtc.AudioSource] = None
        self._audio_track: Optional[rtc.LocalAudioTrack] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        
        # Threading event to ensure the loop is ready before async calls are made
        self._loop_ready = threading.Event()

    @property
    def connection_state(self) -> str:
        state_map = {
            rtc.ConnectionState.CONN_DISCONNECTED: "disconnected",
            rtc.ConnectionState.CONN_CONNECTING: "connecting",
            rtc.ConnectionState.CONN_CONNECTED: "connected",
        }
        return state_map.get(self._room.connection_state, "disconnected")

    def attach(self, controller: SessionController):
        self._controller = controller
        logger.info("[LiveKit] Attached to SessionController")
        
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
        """Called by PyQt6 thread when an agent generates audio to speak."""
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
        """Sends JSON events over LiveKit DataChannel to all web clients."""
        if not self._loop_ready.is_set() or not self._loop:
            return
            
        json_str = json.dumps(data)
        
        async def _publish():
            if self._room.connection_state == rtc.ConnectionState.CONN_CONNECTED:
                await self._room.local_participant.publish_data(
                    json_str.encode("utf-8"), 
                    topic="chat"
                )
                
        if self._loop.is_running():
            asyncio.run_coroutine_threadsafe(_publish(), self._loop)

    # ── LiveKit → PyQT6 (Web → Backend) ────────────────────────────────────────

    async def _handle_track_subscribed(self, track: rtc.Track, publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant):
        """Called when a user in the room starts putting out an audio track"""
        logger.info(f"[LiveKit] Track subscribed: {publication.sid} from {participant.identity}")
        
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            logger.info(f"[LiveKit] Subscribed to AUDIO track from {participant.identity}. Starting stream...")
            audio_stream = rtc.AudioStream(track, sample_rate=16000, num_channels=1)
            
            async for event in audio_stream:
                if not self._controller:
                    continue
                
                # Defend against cross-thread Qt calls by using call_soon_threadsafe
                # or emitting a signal. SessionController handles raw calls OK from Qt signals,
                # but direct from asyncio can cause silent drops.
                # However, live_agent uses QThread heavily, so threadsafe is safest.
                self._frames_received += 1
                
                # We must put it on the controller thread, which is main thread for controller
                # PyQt expects signals to cross threads, but since we just have a ref, 
                # we'll use loop execution if needed, or direct call since controller uses safe queues internally.
                # In session_controller, inject_audio just calls deliver_audio which is a threaded queue.
                self._controller.inject_audio(bytes(event.frame.data))

    async def _handle_data_received(self, data: bytes, participant: rtc.RemoteParticipant, kind: rtc.DataPacketKind, topic: str):
        """Called when a user sends a DataChannel message (e.g. text chat)."""
        if not self._controller or topic != "chat":
            return
            
        try:
            payload = json.loads(data.decode("utf-8"))
            msg_type = payload.get("type")
            
            if msg_type == "text":
                text = payload.get("text", "").strip()
                if text:
                    self._controller.send_text(text)
        except Exception as e:
            logger.error(f"[LiveKit] Error decoding data channel msg: {e}")

    # ── Main Loop ──────────────────────────────────────────────────────────────

    async def run(self):
        """Main asyncio loop for the LiveKit connection"""
        self._loop = asyncio.get_running_loop()
        self._loop_ready.set()
        
        url = os.environ.get("LIVEKIT_URL")
        api_key = os.environ.get("LIVEKIT_API_KEY")
        api_secret = os.environ.get("LIVEKIT_API_SECRET")
        
        if not all([url, api_key, api_secret]):
            logger.error("[LiveKit] Missing LIVEKIT_URL, LIVEKIT_API_KEY, or LIVEKIT_API_SECRET. LiveKit bridge disabled.")
            return

        token = api.AccessToken(api_key, api_secret) \
            .with_identity(self._participant_identity) \
            .with_name("ARC Agent") \
            .with_grants(api.VideoGrants(
                room_join=True,
                room=self._room_name,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )).to_jwt()

        # Connect room events
        @self._room.on("track_subscribed")
        def on_track_subscribed(track: rtc.Track, publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant):
            asyncio.create_task(self._handle_track_subscribed(track, publication, participant))
            
        @self._room.on("data_received")
        def on_data_received(dp: rtc.DataPacket):
            # The python SDK maps data_received to a DataPacket
            # data is dp.data, participant is dp.participant
            asyncio.create_task(self._handle_data_received(dp.data, dp.participant, dp.kind, dp.topic))

        @self._room.on("connection_state_changed")
        def on_connection_state_changed(state: rtc.ConnectionState):
            # Emit Qt signal to UI
            self.connection_state_changed.emit(self.connection_state)

        # Audio source for the agent
        self._audio_source = rtc.AudioSource(
            sample_rate=24000,
            num_channels=1,
        )
        self._audio_track = rtc.LocalAudioTrack.create_audio_track("agent-audio", self._audio_source)

        options = rtc.RoomOptions(
            auto_subscribe=True,
        )

        logger.info(f"[LiveKit] Connecting to room: {self._room_name} at {url}")
        self.connection_state_changed.emit("connecting")
        
        try:
            await self._room.connect(url, token, options=options)
            logger.info("[LiveKit] Connected.")
            self.connection_state_changed.emit("connected")
            
            await self._room.local_participant.publish_track(self._audio_track)
            logger.info("[LiveKit] Published agent audio track")
            
            # Keep alive
            while True:
                await asyncio.sleep(3600)
                
        except asyncio.CancelledError:
            logger.info("[LiveKit] Bridge cancelled, disconnecting.")
        except Exception as e:
            logger.error(f"[LiveKit] Error: {e}")
        finally:
            await self._room.disconnect()
            self.connection_state_changed.emit("disconnected")

    def start_background(self):
        """Helper to run the asyncio loop in a background thread."""
        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.run())
            except Exception as e:
                logger.error(f"[LiveKit] Background thread exception: {e}")
            finally:
                # Discard pending tasks to avoid event loop complaints
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.close()
            
        t = threading.Thread(target=_run, daemon=True, name="LiveKit-Bridge")
        t.start()
        return t

