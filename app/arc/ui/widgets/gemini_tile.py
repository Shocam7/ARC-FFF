"""
arc/ui/widgets/gemini_tile.py
──────────────────────────────
GeminiTile — animated agent "video" tile.

Idle  : near-black with a very faint slow-drifting colour wash.
Active: the full tile floods with fluid Gemini-gradient blobs that swirl
        and intermix — no symbols, just pure gradient animation.

Each tile gets its own blob colour palette from the agent persona config.
"""

from __future__ import annotations

import math

from PyQt6.QtWidgets import QWidget, QPushButton, QMenu
from PyQt6.QtCore    import Qt, QTimer, QPointF, pyqtSignal
from PyQt6.QtGui     import QPainter, QColor, QBrush, QRadialGradient, QFont, QAction

from ...core.config import P, FONT_UI


class GeminiTile(QWidget):
    """
    Parameters
    ----------
    blob_colors : list of (R, G, B, angle_offset, orbit_r_frac, size_frac)
        Defines the colour blobs that form the animated gradient.
        If not supplied, falls back to the standard Gemini palette.
    """

    _DEFAULT_BLOBS = [
        (0x42, 0x85, 0xF4, 0.00,        0.50, 1.10),
        (0xEA, 0x43, 0x35, math.pi*0.5, 0.40, 0.95),
        (0xFB, 0xBC, 0x04, math.pi*0.9, 0.55, 1.00),
        (0x34, 0xA8, 0x53, math.pi*1.4, 0.50, 1.05),
        (0x00, 0xBC, 0xD4, math.pi*1.8, 0.45, 0.90),
        (0x9C, 0x27, 0xB0, math.pi*0.3, 0.35, 0.80),
    ]

    # Emitted when a menu action is triggered (e.g. "info" or "remove")
    action_triggered = pyqtSignal(str)

    def __init__(self, blob_colors: list | None = None, parent=None):
        super().__init__(parent)
        self._blobs  = blob_colors or self._DEFAULT_BLOBS
        self._active = False
        # Each blob has its own independent phase
        self._phases = [i * (2 * math.pi / len(self._blobs))
                        for i in range(len(self._blobs))]
        self._pulse  = 0.0   # 0 = idle dim, 1 = fully active
        self._label  = ""
        self._sublabel = ""

        self._timer = QTimer(self)
        self._timer.setInterval(16)   # ~60 fps
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self.setMinimumSize(200, 160)
        
        # Options button (overlayed in the top-right corner)
        self._opt_btn = QPushButton("⋮", self)
        self._opt_btn.setFixedSize(30, 30)
        self._opt_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._opt_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(0, 0, 0, 0.3);
                color: {P['text']};
                border: none;
                border-radius: 15px;
                font-size: 18px;
                font-weight: bold;
                padding-bottom: 4px;
            }}
            QPushButton:hover {{
                background: rgba(80, 80, 80, 0.7);
            }}
        """)
        self._opt_btn.clicked.connect(self._show_options_menu)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._opt_btn.move(self.width() - 40, 10)

    def _show_options_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background: {P['surface']}; color: {P['text']}; border: 1px solid {P['border']}; border-radius: 4px; padding: 4px; }}
            QMenu::item {{ padding: 6px 20px 6px 20px; border-radius: 3px; font-family: {FONT_UI}; font-size: 13px; }}
            QMenu::item:selected {{ background: {P['raised']}; }}
        """)
        
        info_action = QAction("ℹ️  Info", self)
        info_action.triggered.connect(lambda: self.action_triggered.emit("info"))
        
        remove_action = QAction("❌  Remove", self)
        remove_action.triggered.connect(lambda: self.action_triggered.emit("remove"))
        
        menu.addAction(info_action)
        menu.addAction(remove_action)
        
        menu.exec(self.mapToGlobal(self._opt_btn.pos() + self._opt_btn.rect().bottomLeft()))

    # ── Public API ────────────────────────────────────────────────────────────

    def set_active(self, active: bool):
        self._active = active

    def set_label(self, text: str):
        self._label = text
        self.update()

    def set_sublabel(self, text: str):
        self._sublabel = text
        self.update()

    # ── Animation ─────────────────────────────────────────────────────────────

    def _tick(self):
        speeds_active = [0.009, 0.012, 0.007, 0.014, 0.010, 0.008]
        speeds_idle   = [0.002, 0.003, 0.002, 0.003, 0.002, 0.002]
        speeds = speeds_active if self._active else speeds_idle

        for i in range(len(self._phases)):
            spd = speeds[i] if i < len(speeds) else 0.002
            self._phases[i] = (self._phases[i] + spd) % (2 * math.pi)

        target = 1.0 if self._active else 0.07
        self._pulse += (target - self._pulse) * 0.05
        self.update()

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h   = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        diag   = math.hypot(w, h)

        # ── Solid dark base ──────────────────────────────────────────────────
        p.fillRect(0, 0, w, h, QColor(8, 8, 12))
        p.setPen(Qt.PenStyle.NoPen)

        # ── Fluid gradient blobs ─────────────────────────────────────────────
        for i, blob in enumerate(self._blobs):
            r, g, b, ao, orf, bsf = blob
            phase = self._phases[i % len(self._phases)]

            ox = math.cos(phase + ao) * diag * orf * 0.38
            oy = math.sin(phase * 0.7 + ao) * diag * orf * 0.28
            bx = cx + ox
            by = cy + oy
            br = diag * bsf * 0.52 * (0.92 + 0.08 * math.sin(phase * 1.3 + i))

            base_alpha  = 0.13 + 0.87 * self._pulse
            centre_a    = int(255 * base_alpha * (0.75 + 0.25 * math.sin(phase + i * 1.1)))

            grad = QRadialGradient(QPointF(bx, by), br)
            grad.setColorAt(0.0, QColor(r, g, b, centre_a))
            grad.setColorAt(0.5, QColor(r, g, b, int(centre_a * 0.45)))
            grad.setColorAt(1.0, QColor(r, g, b, 0))
            p.setBrush(QBrush(grad))
            p.drawRect(0, 0, w, h)

        # ── Name label (bottom-left pill) ─────────────────────────────────────
        if self._label:
            self._draw_label(p, w, h)

    def _draw_label(self, p: QPainter, w: int, h: int):
        p.setFont(QFont(FONT_UI, 10))
        fm = p.fontMetrics()

        lines = [self._label]
        if self._sublabel:
            lines.append(self._sublabel)

        lh  = fm.height() * len(lines) + 10
        lw  = max(fm.horizontalAdvance(l) for l in lines) + 20
        lx  = 12
        ly  = h - lh - 12

        p.setBrush(QColor(0, 0, 0, 165))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(lx, ly, lw, lh, 7, 7)

        p.setPen(QColor(P["text"]))
        for i, line in enumerate(lines):
            y = ly + fm.ascent() + 5 + i * fm.height()
            if i == 1:
                p.setPen(QColor(P["text2"]))
                p.setFont(QFont(FONT_UI, 9))
                fm = p.fontMetrics()
            p.drawText(lx + 10, y, line)
