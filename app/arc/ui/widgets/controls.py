"""
arc/ui/widgets/controls.py
───────────────────────────
Reusable control widgets: round icon buttons, pill toggles, checkboxes.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QFrame, QPushButton, QCheckBox
from PyQt6.QtCore    import Qt, pyqtSignal
from PyQt6.QtGui     import QFont

from ...core.config import P, FONT_UI


def round_btn(label: str, size: int = 48, tooltip: str = "",
              checkable: bool = False, bg: str = "#2a2a2a",
              bg_active: str = "#ea4335") -> QPushButton:
    """Round icon button suitable for a Google Meet-style toolbar."""
    b = QPushButton(label)
    b.setFixedSize(size, size)
    b.setCheckable(checkable)
    b.setToolTip(tooltip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFont(QFont("Segoe UI Emoji,Apple Color Emoji,Noto Color Emoji", 18))
    b.setStyleSheet(f"""
        QPushButton{{background:{bg};color:white;border:none;
            border-radius:{size // 2}px;}}
        QPushButton:hover{{background:#3c3c3c;}}
        QPushButton:checked{{background:{bg_active};}}
        QPushButton:disabled{{background:#1a1a1a;color:#3a3a3a;}}
    """)
    return b


def text_btn(label: str, primary: bool = False) -> QPushButton:
    b = QPushButton(label)
    b.setFont(QFont(FONT_UI, 10))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        b.setStyleSheet(f"""
            QPushButton{{background:{P['accent']};color:#000;border:none;
                border-radius:18px;padding:6px 20px;}}
            QPushButton:hover{{background:#a8c8ff;}}
            QPushButton:disabled{{background:{P['raised']};color:{P['text3']};}}
        """)
    else:
        b.setStyleSheet(f"""
            QPushButton{{background:{P['raised']};color:{P['text']};
                border:1px solid {P['border']};border-radius:18px;padding:6px 16px;}}
            QPushButton:hover{{border-color:{P['border_hi']};}}
            QPushButton:disabled{{color:{P['text3']};}}
        """)
    return b


def toggle_btn(label: str) -> QPushButton:
    """Small text toggle button for the top bar."""
    b = QPushButton(label)
    b.setCheckable(True)
    b.setFont(QFont(FONT_UI, 9))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(f"""
        QPushButton{{background:transparent;color:{P['text3']};
            border:1px solid {P['border']};border-radius:5px;padding:3px 12px;}}
        QPushButton:hover{{color:{P['text']};border-color:{P['border_hi']};}}
        QPushButton:checked{{background:{P['raised']};color:{P['accent']};
            border-color:{P['accent']};}}
    """)
    return b


def styled_checkbox(label: str) -> QCheckBox:
    cb = QCheckBox(label)
    cb.setFont(QFont(FONT_UI, 9))
    cb.setStyleSheet(f"""
        QCheckBox{{color:{P['text3']};spacing:5px;}}
        QCheckBox::indicator{{width:13px;height:13px;border-radius:3px;
            border:1px solid {P['border_hi']};background:{P['raised']};}}
        QCheckBox::indicator:checked{{background:{P['accent']};
            border-color:{P['accent']};}}
    """)
    return cb




