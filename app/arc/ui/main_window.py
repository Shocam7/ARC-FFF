"""
arc/ui/main_window.py
──────────────────────
MainWindow — Google Meet-style layout with:
  • Two agent video tiles (one per specialist)
  • User tile
  • Shared transcript panel
  • Bottom call-control bar
  • Hidden event console (toggled via top bar)
  • Text input bar (hidden, toggled via keyboard button)

All business logic lives in SessionController.
"""

from __future__ import annotations

import sys
import logging

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QFrame, QLabel, QLineEdit, QSplitter, QSizePolicy,
    QFileDialog, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer, QBuffer, QIODevice
from PyQt6.QtGui  import QFont, QColor, QImage

from ..core.config  import P, FONT_UI, FONT_MONO, AGENT_PERSONAS, LIVE_MODEL_GEMINI
from ..agents.session_controller import SessionController
from ..web.livekit_bridge import LiveKitBridge

from .widgets.gemini_tile     import GeminiTile
from .widgets.user_tile       import UserTile
from .widgets.transcript_panel import TranscriptPanel
from .widgets.event_console   import EventConsole
from .widgets.controls        import (
    round_btn, text_btn, toggle_btn, styled_checkbox,
)
from .agent_creator import AgentCreatorDialog


logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):

    def __init__(self, lk_bridge: LiveKitBridge | None = None):
        super().__init__()
        self.setWindowTitle("ARC — AI Panel Conference")
        self.setMinimumSize(960, 600)
        self._recording   = False
        self._lk_bridge   = lk_bridge
        self._controller: SessionController | None = None

        # Build UI first (no session yet)
        self._build_ui()
        self._apply_theme()


        # Start session
        self._start_session()

    @property
    def session_controller(self) -> SessionController | None:
        """Expose the session controller for external components (e.g. LiveKit bridge)."""
        return self._controller

    # ══════════════════════════════════════════════════════════════════════════
    # UI construction
    # ══════════════════════════════════════════════════════════════════════════

    def _build_ui(self):
        root_w = QWidget(); self.setCentralWidget(root_w)
        root   = QVBoxLayout(root_w)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        root.addWidget(self._build_topbar())

        # Centre: left panel | right console (hidden)
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setStyleSheet(
            f"QSplitter::handle{{background:{P['border']};width:1px;}}")
        self._splitter.addWidget(self._build_left_panel())

        self._console = EventConsole(
            title="EVENT CONSOLE",
            agent_names={p["id"]: p["name"] for p in AGENT_PERSONAS})
        self._console.setVisible(False)
        self._console.setMinimumWidth(300)
        self._splitter.addWidget(self._console)

        self._cu_console = EventConsole(
            title="COMPUTER USE CONSOLE",
            agent_names={p["id"]: p["name"] for p in AGENT_PERSONAS})
        self._cu_console.setVisible(False)
        self._cu_console.setMinimumWidth(300)
        self._splitter.addWidget(self._cu_console)

        self._img_console = EventConsole(
            title="IMAGE GEN CONSOLE",
            agent_names={p["id"]: p["name"] for p in AGENT_PERSONAS})
        self._img_console.setVisible(False)
        self._img_console.setMinimumWidth(300)
        self._splitter.addWidget(self._img_console)

        self._splitter.setSizes([1000, 400, 400, 400])

        root.addWidget(self._splitter, 1)
        root.addWidget(self._build_bottom_bar())

    # ── Top bar ───────────────────────────────────────────────────────────────

    def _build_topbar(self) -> QWidget:
        bar = QFrame(); bar.setFixedHeight(48)
        bar.setStyleSheet(
            f"background:{P['surface']};border-bottom:1px solid {P['border']};")
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(20, 0, 20, 0); hl.setSpacing(14)

        logo = QLabel("ARC")
        logo.setFont(QFont(FONT_MONO, 16, QFont.Weight.Bold))
        logo.setStyleSheet(f"color:{P['accent']};letter-spacing:4px;")
        hl.addWidget(logo)

        # Routing indicator
        self._routing_lbl = QLabel("")
        self._routing_lbl.setFont(QFont(FONT_MONO, 9))
        self._routing_lbl.setStyleSheet(f"color:{P['text3']};")
        hl.addWidget(self._routing_lbl)

        hl.addStretch(1)

        self._add_agent_btn = toggle_btn("➕ Add Agent")
        self._add_agent_btn.clicked.connect(self._on_add_agent_clicked)
        hl.addWidget(self._add_agent_btn)
        hl.addSpacing(8)

        hl.addSpacing(12)

        self._btn_console = toggle_btn("Console")
        self._btn_console.toggled.connect(
            lambda checked: self._console.setVisible(checked))
        hl.addWidget(self._btn_console); hl.addSpacing(10)

        self._btn_cu_console = toggle_btn("CompConsole")
        self._btn_cu_console.toggled.connect(
            lambda checked: self._cu_console.setVisible(checked))
        hl.addWidget(self._btn_cu_console); hl.addSpacing(10)

        self._btn_img_console = toggle_btn("IMGConsole")
        self._btn_img_console.toggled.connect(
            lambda checked: self._img_console.setVisible(checked))
        hl.addWidget(self._btn_img_console); hl.addSpacing(10)

        # Invite button
        self._invite_btn = text_btn("Invite", primary=True)
        self._invite_btn.clicked.connect(self._on_invite_clicked)
        hl.addWidget(self._invite_btn)
        hl.addSpacing(10)

        # Added LiveKit specific status indicator logic as requested by User
        self._lk_status_lbl = QLabel("LiveKit: OFF")
        self._lk_status_lbl.setFont(QFont(FONT_MONO, 8))
        self._lk_status_lbl.setStyleSheet(f"color:{P['text3']};")
        hl.addWidget(self._lk_status_lbl)
        hl.addSpacing(10)

        self._dot_lbl = QLabel("●")
        self._dot_lbl.setFont(QFont(FONT_UI, 10))
        self._dot_lbl.setStyleSheet(f"color:{P['text3']};")
        hl.addWidget(self._dot_lbl)
        self._status_lbl = QLabel("Connecting…")
        self._status_lbl.setFont(QFont(FONT_UI, 10))
        self._status_lbl.setStyleSheet(f"color:{P['text2']};")
        hl.addWidget(self._status_lbl)
        return bar

    # ── Left panel ────────────────────────────────────────────────────────────

    def _build_left_panel(self) -> QWidget:
        panel = QWidget(); panel.setStyleSheet(f"background:{P['bg']};")
        vl = QVBoxLayout(panel)
        vl.setContentsMargins(0, 0, 0, 0); vl.setSpacing(0)

        vl.addWidget(self._build_video_row(), 1)
        div = QFrame(); div.setFixedHeight(1)
        div.setStyleSheet(f"background:{P['border']};")
        vl.addWidget(div)
        vl.addWidget(self._build_transcript_area())
        vl.addWidget(self._build_text_input_bar())
        return panel

    def _build_video_row(self) -> QWidget:
        """Two agent tiles + one user tile in a horizontal row."""
        row = QWidget(); row.setStyleSheet(f"background:{P['bg']};")
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._video_row_layout = QHBoxLayout(row)
        self._video_row_layout.setContentsMargins(16, 14, 16, 10); self._video_row_layout.setSpacing(12)

        # Build one GeminiTile per persona
        self._agent_tiles: dict[str, GeminiTile] = {}
        for p in AGENT_PERSONAS:
            tile = GeminiTile(blob_colors=p.get("blob_colors"))
            tile.set_label(p["name"])
            tile.set_sublabel(p["field"])
            tile.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            tile.action_triggered.connect(lambda action, aid=p["id"]: self._on_tile_action(aid, action))
            self._agent_tiles[p["id"]] = tile
            self._video_row_layout.addWidget(tile, 2)

        # User tile (narrower, fixed width)
        self._user_tile = UserTile("You")
        self._user_tile.setFixedWidth(180)
        self._user_tile.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self._video_row_layout.addWidget(self._user_tile, 1)
        return row

    def _build_transcript_area(self) -> QWidget:
        agent_names = {p["id"]: p["name"] for p in AGENT_PERSONAS}
        self._transcript = TranscriptPanel(agent_names=agent_names)
        self._transcript.setFixedHeight(200)
        self._transcript.setStyleSheet(f"background:{P['surface']};")
        return self._transcript

    def _build_text_input_bar(self) -> QWidget:
        bar = QFrame()
        bar.setStyleSheet(
            f"background:{P['surface']};border-top:1px solid {P['border']};")
        bar.setVisible(False)
        self._text_input_bar = bar

        hl = QHBoxLayout(bar); hl.setContentsMargins(16, 9, 16, 9); hl.setSpacing(8)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a message… (routes automatically)")
        self._input.setFont(QFont(FONT_UI, 11 if sys.platform != "darwin" else 13))
        self._input.setStyleSheet(f"""
            QLineEdit{{background:{P['raised']};color:{P['text']};
                border:1px solid {P['border']};border-radius:20px;padding:6px 16px;}}
            QLineEdit:focus{{border-color:{P['accent']};}}
        """)
        self._input.returnPressed.connect(self._send_text)
        hl.addWidget(self._input, 1)

        self._send_btn = text_btn("Send", primary=True)
        self._send_btn.clicked.connect(self._send_text)
        hl.addWidget(self._send_btn)

        img_btn = round_btn("📎", size=34, tooltip="Send image")
        img_btn.setFixedSize(34, 34)
        img_btn.clicked.connect(self._pick_image)
        self._img_btn = img_btn
        hl.addWidget(img_btn)
        return bar

    # ── Bottom bar ────────────────────────────────────────────────────────────

    def _build_bottom_bar(self) -> QWidget:
        bar = QFrame(); bar.setFixedHeight(76)
        bar.setStyleSheet(
            f"background:{P['surface']};border-top:1px solid {P['border']};")
        hl = QHBoxLayout(bar); hl.setContentsMargins(28, 0, 28, 0); hl.setSpacing(12)

        self._session_lbl = QLabel("")
        self._session_lbl.setFont(QFont(FONT_MONO, 8))
        self._session_lbl.setStyleSheet(f"color:{P['text3']};")
        hl.addWidget(self._session_lbl); hl.addStretch(1)

        # Mic toggle
        self._mic_btn = round_btn("🎤", size=52, tooltip="Toggle microphone",
                                   checkable=True, bg="#2a2a2a", bg_active=P["red"])
        self._mic_btn.toggled.connect(self._on_mic_toggled)
        hl.addWidget(self._mic_btn)

        # Text input toggle
        self._txt_toggle = round_btn("⌨️", size=44, tooltip="Toggle text input",
                                      checkable=True, bg="#2a2a2a", bg_active="#3a3a3a")
        self._txt_toggle.toggled.connect(
            lambda c: (self._text_input_bar.setVisible(c),
                       self._input.setFocus() if c else None))
        hl.addWidget(self._txt_toggle)

        # Image
        self._img_bar_btn = round_btn("📷", size=44, tooltip="Send image", bg="#2a2a2a")
        self._img_bar_btn.clicked.connect(self._pick_image)
        hl.addWidget(self._img_bar_btn)

        # End / reconnect
        end_btn = round_btn("📵", size=52, tooltip="End session / reconnect",
                             bg=P["red"])
        end_btn.clicked.connect(lambda: self._restart_session("Reconnecting…"))
        hl.addWidget(end_btn)

        hl.addStretch(1)

        self._model_lbl = QLabel("")
        self._model_lbl.setFont(QFont(FONT_MONO, 8))
        self._model_lbl.setStyleSheet(f"color:{P['text3']};")
        self._model_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        hl.addWidget(self._model_lbl)
        return bar

    # ══════════════════════════════════════════════════════════════════════════
    # Session lifecycle
    # ══════════════════════════════════════════════════════════════════════════

    def _start_session(self):
        ctrl = SessionController()
        # Agent tile animation
        ctrl.agent_speaking.connect(self._on_agent_speaking)
        # Transcript
        ctrl.text_received.connect(self._transcript.on_text_received)
        ctrl.input_transcription.connect(self._transcript.on_input_transcription)
        ctrl.output_transcription.connect(self._transcript.on_output_transcription)
        ctrl.turn_complete.connect(self._transcript.on_turn_complete)
        ctrl.interrupted.connect(self._transcript.on_interrupted)
        # Consoles
        ctrl.event_logged.connect(self._console.log)
        ctrl.cu_logged.connect(self._cu_console.log)
        ctrl.img_logged.connect(self._img_console.log)
        # Status / error
        ctrl.agent_status.connect(self._on_agent_status)
        ctrl.agent_error.connect(
            lambda aid, msg: self._transcript.add_system(
                f"Error [{aid}]: {msg}", error=True))
        # Routing note
        ctrl.routing_note.connect(self._on_routing_note)
        ctrl.active_agent_changed.connect(self._on_active_changed)
        ctrl.image_ready.connect(self._on_image_ready)
        ctrl.user_message.connect(self._on_user_message_received)

        self._controller = ctrl
        ctrl.start()
            
        # Attach the LiveKit Bridge to the new session
        if self._lk_bridge:
            self._lk_bridge.attach(ctrl)
            # Sync connection state to the UI indicator
            self._lk_bridge.connection_state_changed.connect(
                self._update_livekit_indicator
            )
            # DO NOT start background automatically here anymore as per User requirement
            # self._update_livekit_indicator(self._lk_bridge.connection_state)

        model   = LIVE_MODEL_GEMINI
        short   = model.split("/")[-1] if "/" in model else model
        backend = "Gemini AI"
        self._model_lbl.setText(f"{backend}  ·  {short}")

    def _restart_session(self, reason: str = "Reconnecting…"):
        logger.info("[MainWindow] Restarting session, reason: %s", reason)
        if self._controller:
            self._controller.stop()
            self._controller = None
        if self._recording:
            self._recording = False
            self._mic_btn.setChecked(False)
            self._user_tile.set_mic(False)
        for tile in self._agent_tiles.values():
            tile.set_active(False)

        # Clear tracking and immediately update Top Bar UI
        self._agent_statuses = {}
        self._last_agg_status = "reconnecting"
        
        self._dot_lbl.setStyleSheet(f"color:{P['yellow']};")
        self._status_lbl.setText("Reconnecting…")
        self._session_lbl.setText("")
        
        if reason:
            self._transcript.add_system(reason)

        # Disable input while transitioning
        for w in (self._mic_btn, self._txt_toggle, self._img_bar_btn,
                  self._send_btn, self._img_btn):
            w.setEnabled(False)

        QTimer.singleShot(600, self._start_session)

    def _update_livekit_indicator(self, state: str):
        color = P['green'] if state == 'connected' else P['yellow'] if state == 'connecting' else P['red']
        self._lk_status_lbl.setText(f"LiveKit: {state.upper()}")
        self._lk_status_lbl.setStyleSheet(f"color:{color}; font-weight: bold;")
        if state == 'connected':
            self._invite_btn.setEnabled(False)
            self._invite_btn.setText("In Session")

    def _on_invite_clicked(self):
        link = "https://arc-fff.vercel.app/"
        QMessageBox.information(
            self, "Invite Participants",
            f"Share this link with participants to invite them to the meeting:<br><br>"
            f"<a href='{link}'>{link}</a><br><br>"
            "LiveKit bridge is starting...",
        )
        # Copy to clipboard
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(link)
        self._transcript.add_system(f"🔗 Shareable link copied to clipboard: {link}")

        if self._lk_bridge:
            # Check if already started or start it
            if not getattr(self, "_lk_started", False):
                self._lk_bridge.start_background()
                self._lk_started = True
                self._lk_status_lbl.setText("LiveKit: STARTING...")
                self._lk_status_lbl.setStyleSheet(f"color:{P['yellow']};")

    # ══════════════════════════════════════════════════════════════════════════
    # Slots
    # ══════════════════════════════════════════════════════════════════════════

    def _on_agent_speaking(self, agent_id: str, speaking: bool):
        tile = self._agent_tiles.get(agent_id)
        if tile:
            tile.set_active(speaking)

    def _on_active_changed(self, agent_id: str):
        # Dim all tiles except the one now speaking
        for aid, tile in self._agent_tiles.items():
            if aid != agent_id:
                tile.set_active(False)

    def _on_image_ready(self, path: str):
        self._transcript.add_system(f"📷 Image ready: {path}")
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _on_routing_note(self, note: str):
        self._routing_lbl.setText(note)
        # Auto-clear after 4 seconds
        QTimer.singleShot(4000, lambda: self._routing_lbl.setText(""))

    def _update_aggregate_status(self):
        if not hasattr(self, "_agent_statuses"):
            return
            
        old_agg = getattr(self, "_last_agg_status", "disconnected")
        all_statuses = list(self._agent_statuses.values())
        
        # Determine strict aggregate state across all agents
        if "reconnecting" in all_statuses:
            agg, col = "reconnecting", P["yellow"]
        elif "connecting" in all_statuses:
            agg, col = "connecting", P["yellow"]
        elif "disconnected" in all_statuses:
            agg, col = "disconnected", P["red"]
        elif not all_statuses:
            agg, col = "disconnected", P["red"]
        else:
            # Only green when everything is present and fully connected
            agg, col = "connected", P["green"]

        self._dot_lbl.setStyleSheet(f"color:{col};")
        self._status_lbl.setText(agg.capitalize())
        self._last_agg_status = agg

        # Announce successful connection inside the transcript
        if old_agg != "connected" and agg == "connected":
            self._transcript.add_system("✅ Connected")

        ok = agg == "connected"
        for w in (self._mic_btn, self._txt_toggle, self._img_bar_btn,
                  self._send_btn, self._img_btn):
            w.setEnabled(ok)

    def _on_agent_status(self, agent_id: str, status: str):
        if not hasattr(self, "_agent_statuses"):
            self._agent_statuses: dict[str, str] = {}
        self._agent_statuses[agent_id] = status
        self._update_aggregate_status()

        # Update the session ID explicitly shown in bottom-left corner
        if status == "connected" and self._controller:
            agent_worker = self._controller._agents.get(agent_id)
            if agent_worker:
                self._session_lbl.setText(agent_worker.session_id)

    def _on_mic_toggled(self, checked: bool):
        self._recording = checked
        self._user_tile.set_mic(checked)
        if checked:
            if self._controller:
                self._controller.start_recording()
            self._transcript.add_system("🎤 Microphone active")
        else:
            if self._controller:
                self._controller.stop_recording()
            self._transcript.add_system("Microphone muted")

    def _on_user_message_received(self, text: str):
        self._transcript.add_system(f"You: {text}")

    def _send_text(self):
        text = self._input.text().strip()
        if not text or not self._controller:
            return
        # Transcript updated via user_message signal from controller
        self._controller.send_text(text)
        self._input.clear()

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Image", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path or not self._controller:
            return
        img = QImage(path)
        if img.isNull():
            self._transcript.add_system("Could not load image", error=True)
            return
        if img.width() > 768 or img.height() > 768:
            img = img.scaled(768, 768,
                             Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        buf = QBuffer(); buf.open(QIODevice.OpenModeFlag.ReadWrite)
        img.save(buf, "JPEG", 85)
        jpeg_bytes = bytes(buf.data()); buf.close()
        self._controller.send_image(jpeg_bytes)
        self._transcript.add_system(f"📷 Image sent ({len(jpeg_bytes):,} bytes)")

    def _apply_theme(self):
        self.setStyleSheet(f"QMainWindow{{background:{P['bg']};}}")

    def _on_add_agent_clicked(self):
        # Allow clicking Add Agent button normally, no toggle uncheck logic needed
        self._add_agent_btn.setChecked(False)
        dialog = AgentCreatorDialog(self)
        if dialog.exec():
            persona = dialog.result_persona
            if not persona:
                return
            
            # 1. Add to AGENT_PERSONAS list
            AGENT_PERSONAS.append(persona)
            
            # 2. Add GeminiTile to UI
            tile = GeminiTile(blob_colors=persona.get("blob_colors"))
            tile.set_label(persona["name"])
            tile.set_sublabel(persona.get("field", "Expert"))
            tile.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            tile.action_triggered.connect(lambda action, aid=persona["id"]: self._on_tile_action(aid, action))
            self._agent_tiles[persona["id"]] = tile
            
            # Insert before the user tile
            user_idx = self._video_row_layout.indexOf(self._user_tile)
            self._video_row_layout.insertWidget(max(0, user_idx), tile, 2)
            
            self._console._agent_names[persona["id"]] = persona["name"]
            self._cu_console._agent_names[persona["id"]] = persona["name"]
            self._img_console._agent_names[persona["id"]] = persona["name"]
            self._transcript.register_agent(persona["id"], persona["name"])
            
            # 3. Dynamic injection into SessionController
            if self._controller:
                # Track status explicitly to prevent connection UI lock
                if not hasattr(self, "_agent_statuses"):
                    self._agent_statuses = {}
                self._agent_statuses[persona["id"]] = "connecting"
                
                self._controller.add_agent_live(persona)
                self._transcript.add_system(f"✨ {persona['name']} has joined the panel.")
                self._controller._log.append("system", "System", f"{persona['name']} ({persona.get('field', 'Expert')}) has dynamically joined the panel.")
                
                # Setup late-bound signals for the newly added agent worker
                # They are inside controller._agents by now
                worker = self._controller._agents.get(persona["id"])
                if worker:
                    # Some specific late signals if needed, or _wire_agent handled most
                    pass
                
                # 4. Trigger introduction text natively. 
                # Wait until connected before telling it to introduce itself
                import threading
                def introduce():
                    import time
                    # Wait for status to become connected
                    for _ in range(60): # 60 * 0.5s = 30s timeout
                        if getattr(self, "_agent_statuses", {}).get(persona["id"]) == "connected":
                            break
                        time.sleep(0.5)
                    else:
                        return # Timeout
                        
                    # Sleep an extra bit to ensure audio system is primed
                    time.sleep(1.0)
                    self._controller.send_text("Please introduce yourself to the panel.", force_agent_id=persona["id"])
                threading.Thread(target=introduce, daemon=True).start()

    def _on_tile_action(self, agent_id: str, action: str):
        persona = next((p for p in AGENT_PERSONAS if p["id"] == agent_id), None)
        if not persona:
            return
            
        if action == "info":
            text = f"<b>Name:</b> {persona['name']}<br>" \
                   f"<b>Field:</b> {persona.get('field', 'Expert')}<br><br>" \
                   f"<b>System Instruction:</b><br>" \
                   f"<div style='white-space: pre-wrap;'>{persona.get('instruction', 'None')}</div>"
            msg = QMessageBox(self)
            msg.setWindowTitle(f"Agent Info: {persona['name']}")
            msg.setTextFormat(Qt.TextFormat.RichText)
            msg.setText(text)
            msg.setStyleSheet(f"background: {P['surface']}; color: {P['text']}; QLabel {{ min-width: 400px; }}")
            msg.exec()
            
        elif action == "remove":
            reply = QMessageBox.question(
                self, 'Remove Agent',
                f"Are you sure you want to remove '{persona['name']}' from the meeting?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                # 1. Remove from Controller
                if self._controller:
                    self._controller.remove_agent_live(agent_id)
                    self._transcript.add_system(f"👋 {persona['name']} has been removed from the panel.")
                    self._controller._log.append("system", "System", f"{persona['name']} was removed from the panel by the user.")
                    
                # 2. Clean from UI Tracking
                if hasattr(self, "_agent_statuses"):
                    self._agent_statuses.pop(agent_id, None)
                    # Force update aggregate status
                    self._update_aggregate_status()

                # 3. Remove UI Tile
                tile = self._agent_tiles.pop(agent_id, None)
                if tile:
                    self._video_row_layout.removeWidget(tile)
                    tile.deleteLater()
                    
                # 4. Remove from AGENT_PERSONAS (optional but good for consistency)
                for i, p in enumerate(AGENT_PERSONAS):
                    if p["id"] == agent_id:
                        del AGENT_PERSONAS[i]
                        break

    def closeEvent(self, e):
        if self._controller:
            self._controller.stop()
        if self._lk_bridge:
            self._lk_bridge.stop()
        e.accept()