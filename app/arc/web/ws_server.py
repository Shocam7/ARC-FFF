"""
arc/web/ws_server.py
────────────────────
WebSocket Bridge Server for the ARC Application.

Runs a pure Python websockets server in a background thread alongside the PyQt6 host app.
Clients (browsers) connect to ws://localhost:8765/ws/guest_id/session_id

Multiplexes two protocols on the same connection:
  - Text messages (JSON strings): Chat text, routing notes, UI state.
  - Binary messages (PCM bytes): 16kHz audio from the browser mic, 
    and 24kHz audio from the agent going back to the browser speaker.
"""

import asyncio
import base64
import json
import logging
import threading
from typing import Set

import websockets
from websockets.server import WebSocketServerProtocol

from ..agents.session_controller import SessionController

logger = logging.getLogger(__name__)

# Configurable port. In production, this can be exposed via ngrok.
WS_PORT = 8765

class ARCWebSocketServer:
    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._clients: Set[WebSocketServerProtocol] = set()
        self._controller: SessionController | None = None
        self._stop_event = threading.Event()

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def attach(self, controller: SessionController):
        """Link the server to the active SessionController from the GUI."""
        self._controller = controller

        # Disconnect previous handlers if any, then wire up the new ones
        self._wire_controller_signals()
        logger.info("[WS] Attached to new SessionController instance")

    def start(self, controller: SessionController | None = None):
        """Start the background WebSocket server thread."""
        if controller:
            self._controller = controller

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_server_thread,
            daemon=True,
            name="ARC-WebSocket-Server"
        )
        self._thread.start()

    def stop(self):
        """Shut down the server cleanly."""
        self._stop_event.set()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=3.0)

    # ── Thread Root ──────────────────────────────────────────────────────────

    def _run_server_thread(self):
        """The entry point for the background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        async def main():
            # In websockets v13+, serve() must be called inside a running loop
            async with websockets.serve(
                self._handle_client,
                "0.0.0.0",
                WS_PORT,
                ping_interval=20,
                ping_timeout=20
            ) as server:
                logger.info(f"[WS] Listening on ws://0.0.0.0:{WS_PORT}")
                
                # Wire initial signals if controller was provided
                if self._controller:
                    self._wire_controller_signals()
                
                # Wait until the stop event is toggled or loop stopped
                while not self._stop_event.is_set():
                    await asyncio.sleep(0.5)
                
                logger.info("[WS] Stopping server...")

        try:
            self._loop.run_until_complete(main())
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[WS] Server error: {e}")
        finally:
            # Close all active client connections
            if self._clients:
                # We need to run this in the loop before closing it
                self._loop.run_until_complete(self._close_all())
            
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()
            logger.info("[WS] Server thread finished")

    async def _close_all(self):
        if self._clients:
            close_tasks = [client.close() for client in self._clients]
            await asyncio.gather(*close_tasks, return_exceptions=True)

    # ── Client Handling ──────────────────────────────────────────────────────

    async def _handle_client(self, websocket: WebSocketServerProtocol):
        """Handle an individual WebSocket connection."""
        # path is typically something like /ws/guest-abc/session-123
        path = websocket.request.path
        parts = path.strip("/").split("/")
        user_id = parts[1] if len(parts) > 1 else "unknown-user"
        
        self._clients.add(websocket)
        logger.info(f"[WS] Client connected: {user_id} ({len(self._clients)} total)")

        try:
            # Send initial connection success message
            await websocket.send(json.dumps({
                "type": "system",
                "text": f"Connected to ARC server local instance"
            }))

            # Main listen loop
            async for message in websocket:
                if isinstance(message, str):
                    await self._handle_text_message(websocket, user_id, message)
                elif isinstance(message, bytes):
                    await self._handle_binary_message(websocket, user_id, message)

        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            logger.error(f"[WS] Error handling client {user_id}: {e}")
        finally:
            self._clients.discard(websocket)
            logger.info(f"[WS] Client disconnected: {user_id} ({len(self._clients)} left)")

    async def _handle_text_message(self, websocket: WebSocketServerProtocol, user_id: str, raw_text: str):
        """Handle incoming JSON text messages from the browser."""
        try:
            data = json.loads(raw_text)
            msg_type = data.get("type")

            if msg_type == "ping":
                await websocket.send(json.dumps({"type": "pong"}))
                
            elif msg_type == "text":
                text = data.get("text", "").strip()
                if text and self._controller:
                    # Route incoming web text into the master PyQt6 session controller!
                    # We must dispatch safely since send_text touches Qt/Orchestrator
                    # PyQt6 signals are thread-safe, but direct method calls across threads can be risky.
                    # QThread handles signal slot invocation nicely though.
                    self._controller.send_text(text)
                    
        except json.JSONDecodeError:
            pass

    async def _handle_binary_message(self, websocket: WebSocketServerProtocol, user_id: str, pcm_bytes: bytes):
        """
        Handle incoming raw 16kHz PCM audio from the browser microphone.
        Inject this directly into the active agent so the Gemini Live API hears the web user.
        """
        if self._controller:
            self._controller.inject_audio(pcm_bytes)

    # ── Broadcasting (PyQt6 → WebSockets) ────────────────────────────────────

    def _broadcast_json(self, data: dict):
        """Thread-safe JSON broadcast to all connected web clients."""
        if not self._clients or not self._loop:
            return

        json_str = json.dumps(data)

        def _do_broadcast():
            if not self._clients:
                return
            # create tasks to send to all clients concurrently
            tasks = [asyncio.create_task(client.send(json_str)) for client in self._clients]
            # don't wait for them, just let them run
            
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(_do_broadcast)

    def _broadcast_binary(self, pcm_bytes: bytes):
        """Thread-safe Binary PCM broadcast to all connected web clients."""
        if not self._clients or not self._loop:
            return

        def _do_broadcast():
            if not self._clients:
                return
            # Audio must be streamed instantly over the WS frame
            tasks = [asyncio.create_task(client.send(pcm_bytes)) for client in self._clients]
            
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(_do_broadcast)

    # ── Signal Wiring ────────────────────────────────────────────────────────

    def _wire_controller_signals(self):
        """
        Connect PyQt6 signals from the active SessionController so that 
        we can stream agent responses immediately back to web clients.
        
        Since PyQt6 signals can connect directly to standard Python functions 
        (even ones that then use asyncio loop.call_soon_threadsafe), this is safe.
        """
        if not self._controller:
            return
            
        c = self._controller

        # It's important to use unique lambda scopes for these bindings so they 
        # don't break if the controller stops/restarts. We use the UI layer logic.

        # Text chunks (streaming)
        c.text_received.connect(
            lambda aid, text, partial: self._broadcast_json({
                "type": "text_chunk",
                "agent_id": aid,
                "text": text,
                "partial": partial
            })
        )

        # Transcriptions (User speech)
        c.input_transcription.connect(
            lambda text, finished: self._broadcast_json({
                "type": "transcription",
                "role": "user",
                "text": text,
                "finished": finished
            })
        )

        # Transcriptions (Agent speech)
        c.output_transcription.connect(
            lambda aid, text, finished: self._broadcast_json({
                "type": "transcription",
                "role": "agent",
                "agent_id": aid,
                "text": text,
                "finished": finished
            })
        )

        # Turn completion
        c.turn_complete.connect(
            lambda aid: self._broadcast_json({
                "type": "turn_complete",
                "agent_id": aid
            })
        )

        # Routing notes
        c.routing_note.connect(
            lambda note: self._broadcast_json({
                "type": "routing",
                "note": note
            })
        )

        # Agent connection statuses
        c.agent_status.connect(
            lambda aid, status: self._broadcast_json({
                "type": "agent_status",
                "agent_id": aid,
                "status": status
            })
        )
        
        # Image generation updates
        c.image_ready.connect(
            lambda path: self._broadcast_json({
                "type": "image_ready",
                "path": path,
                # In a real app we'd HTTP serve the image or pass B64
                # For now, just notifying the UI it's done
            })
        )

        # The new binary audio bridging signal
        # We'll add this to SessionController specifically for the WS server
        if hasattr(c, "audio_chunk_generated"):
            c.audio_chunk_generated.connect(
                lambda aid, pcm_bytes: self._broadcast_binary(pcm_bytes)
            )

