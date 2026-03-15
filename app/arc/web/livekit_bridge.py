"""
arc/web/livekit_bridge.py
────────────────────────
LiveKit Bridge for the ARC Application.

Connects to a LiveKit Room and bridges audio between the Room and the
PyQt6 SessionController.
- Receives user Opus audio from LiveKit, decodes to PCM, injects into SessionController.
- Receives agent PCM audio from SessionController, encodes to Opus, pushes to LiveKit.
"""

import asyncio
import logging
import os
from typing import Optional

from livekit import api, rtc
from ..agents.session_controller import SessionController

logger = logging.getLogger(__name__)

class LiveKitBridge:
    def __init__(self, room_name: str = "bidi-demo-room", participant_identity: str = "arc-agent"):
        self._controller: Optional[SessionController] = None
        self._room_name = room_name
        self._participant_identity = participant_identity
        
        self._room = rtc.Room()
        self._audio_source: Optional[rtc.AudioSource] = None
        self._audio_track: Optional[rtc.LocalAudioTrack] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def attach(self, controller: SessionController):
        self._controller = controller
        logger.info("[LiveKit] Attached to SessionController")
        
        # When an agent speaks, we get PCM bytes
        # We need to push these to the LiveKit AudioSource
        if hasattr(self._controller, "audio_chunk_generated"):
            self._controller.audio_chunk_generated.connect(self._on_agent_audio)

    def _on_agent_audio(self, agent_id: str, pcm_bytes: bytes):
        """Called by PyQt6 thread when an agent generates audio to speak."""
        if not self._audio_source:
            return

        # Gemini returns 24kHz, 1 channel, 16-bit PCM.
        # Ensure we wrap the raw bytes in an rtc.AudioFrame
        
        # Calculate samples per channel (2 bytes per sample for intro-16)
        samples_per_channel = len(pcm_bytes) // 2
        
        frame = rtc.AudioFrame(
            data=pcm_bytes,
            sample_rate=24000,
            num_channels=1,
            samples_per_channel=samples_per_channel
        )
        
        # Capture the frame async
        if self._loop and self._loop.is_running():
            # capture_frame is async in livekit-python
            asyncio.run_coroutine_threadsafe(
                self._audio_source.capture_frame(frame), self._loop
            )

    async def _handle_track_subscribed(self, track: rtc.Track, publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant):
        """Called when a user in the room starts putting out an audio track"""
        print(f"[LiveKit] Track subscribed: {publication.sid} from {participant.identity}")
        logger.info(f"[LiveKit] Track subscribed: {publication.sid} from {participant.identity}")
        
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            print(f"[LiveKit] Subscribed to AUDIO track from {participant.identity}. Starting stream...")
            audio_stream = rtc.AudioStream(track, sample_rate=16000, num_channels=1)
            
            # Start background task to drain this audio stream and send it to the agent
            async for event in audio_stream:
                if not self._controller:
                    continue
                
                # The event contains an rtc.AudioFrame
                frame = event.frame
                # Inject audio into the session controller
                self._controller.inject_audio(bytes(frame.data))

    async def run(self):
        """Main asyncio loop for the LiveKit connection"""
        self._loop = asyncio.get_running_loop()
        
        url = os.environ.get("LIVEKIT_URL")
        api_key = os.environ.get("LIVEKIT_API_KEY")
        api_secret = os.environ.get("LIVEKIT_API_SECRET")
        
        if not all([url, api_key, api_secret]):
            logger.error("[LiveKit] Missing LIVEKIT_URL, LIVEKIT_API_KEY, or LIVEKIT_API_SECRET. LiveKit bridge disabled.")
            return

        # Generate token for the agent
        # We use the REST API Token object
        token = api.AccessToken(api_key, api_secret) \
            .with_identity(self._participant_identity) \
            .with_name("ARC Agent") \
            .with_grants(api.VideoGrants(
                room_join=True,
                room=self._room_name,
                can_publish=True,
                can_subscribe=True,
            )).to_jwt()

        # Connect room events
        @self._room.on("track_subscribed")
        def on_track_subscribed(track: rtc.Track, publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant):
            # Run the async handler as a new task
            asyncio.create_task(self._handle_track_subscribed(track, publication, participant))

        # We will create an audio source for our agent to speak into
        self._audio_source = rtc.AudioSource(
            sample_rate=24000,
            num_channels=1,
        )
        self._audio_track = rtc.LocalAudioTrack.create_audio_track("agent-audio", self._audio_source)

        options = rtc.RoomOptions(
            auto_subscribe=True,
        )

        logger.info(f"[LiveKit] Connecting to room: {self._room_name} at {url}")
        try:
            await self._room.connect(url, token, options=options)
            logger.info("[LiveKit] Connected OK.")
            
            # Publish our local audio track so the web users can hear us
            # We don't strictly need to await this to block the run loop
            await self._room.local_participant.publish_track(self._audio_track)
            logger.info("[LiveKit] Published agent audio track")
            
            # Keep alive
            while True:
                await asyncio.sleep(3600)
                
        except Exception as e:
            logger.error(f"[LiveKit] Error: {e}")
        finally:
            await self._room.disconnect()

    def start_background(self):
        """Helper to run the asyncio loop in a background thread or event loop if needed"""
        import threading
        
        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.run())
            
        t = threading.Thread(target=_run, daemon=True, name="LiveKit-Bridge")
        t.start()
        return t
