"""
arc/ui/widgets/user_tile.py
────────────────────────────
UserTile — simple dark tile showing the user's avatar and mic status.
"""

import sys
import math

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore    import Qt, QPointF
from PyQt6.QtGui     import QPainter, QColor, QBrush, QFont

from ...core.config import P, FONT_UI


class UserTile(QWidget):
    def __init__(self, name: str = "You", parent=None):
        super().__init__(parent)
        self._name   = name
        self._mic_on = False
        self.setMinimumSize(140, 110)

    def set_mic(self, on: bool):
        self._mic_on = on
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h   = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0

        # Background
        p.fillRect(0, 0, w, h, QColor(P["tile_dark"]))

        # Avatar circle
        av_r = min(w, h) * 0.22
        p.setBrush(QBrush(QColor(50, 70, 110)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy - av_r * 0.1), av_r, av_r)

        # Initial
        font = QFont(FONT_UI, int(av_r * 0.85), QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(QColor(P["text"]))
        fm  = p.fontMetrics()
        ini = self._name[0].upper() if self._name else "U"
        p.drawText(
            int(cx - fm.horizontalAdvance(ini) / 2),
            int(cy - av_r * 0.1 + (fm.ascent() - fm.descent()) / 2),
            ini,
        )

        # Mic status dot
        p.setBrush(QBrush(QColor(P["green"] if self._mic_on else P["red"])))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(w - 16, h - 16), 6, 6)

        # Name label
        font2 = QFont(FONT_UI, 9)
        p.setFont(font2)
        fm2 = p.fontMetrics()
        lw = fm2.horizontalAdvance(self._name) + 18
        lh = fm2.height() + 6
        lx, ly = 8, h - lh - 8
        p.setBrush(QColor(0, 0, 0, 155))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(lx, ly, lw, lh, 5, 5)
        p.setPen(QColor(P["text"]))
        p.drawText(lx + 9, ly + lh - fm2.descent() - 3, self._name)
