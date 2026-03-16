"""
arc/ui/widgets/event_console.py
────────────────────────────────
EventConsole — raw ADK event log panel (hidden by default).
Now shows which agent each event came from.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QCheckBox, QTextEdit
from PyQt6.QtCore    import Qt
from PyQt6.QtGui     import QFont, QColor, QTextCursor

from ...core.config import P, FONT_UI, FONT_MONO


class EventConsole(QWidget):
    def __init__(self, title: str = "EVENT CONSOLE", agent_names: dict[str, str] | None = None, parent=None):
        super().__init__(parent)
        self._title = title
        self._agent_names = agent_names or {}
        self._show_audio  = False
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        hdr = QFrame(); hdr.setFixedHeight(40)
        hdr.setStyleSheet(
            f"background:{P['surface']};border-bottom:1px solid {P['border']};")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(14, 0, 10, 0)

        t = QLabel(self._title)
        t.setFont(QFont(FONT_MONO, 8))
        t.setStyleSheet(f"color:{P['text3']};letter-spacing:2px;")
        hl.addWidget(t); hl.addStretch()

        chk = QCheckBox("audio")
        chk.setStyleSheet(f"""
            QCheckBox{{color:{P['text3']};font-size:10px;}}
            QCheckBox::indicator{{width:12px;height:12px;border-radius:3px;
                border:1px solid {P['border_hi']};background:{P['raised']};}}
            QCheckBox::indicator:checked{{background:{P['accent']};
                border-color:{P['accent']};}}
        """)
        chk.toggled.connect(lambda v: setattr(self, '_show_audio', v))
        hl.addWidget(chk)

        clr = QPushButton("clear"); clr.setFixedSize(44, 22)
        clr.setStyleSheet(f"""
            QPushButton{{background:transparent;color:{P['text3']};
                border:1px solid {P['border']};border-radius:4px;font-size:10px;}}
            QPushButton:hover{{color:{P['text']};border-color:{P['border_hi']};}}
        """)
        clr.clicked.connect(lambda: self._text.clear())
        hl.addWidget(clr)
        root.addWidget(hdr)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(QFont(FONT_MONO, 9))
        self._text.setStyleSheet(f"""
            QTextEdit{{background:{P['surface']};color:{P['text3']};
                border:none;padding:6px;}}
            QScrollBar:vertical{{background:{P['surface']};width:4px;}}
            QScrollBar::handle:vertical{{background:{P['border']};border-radius:2px;}}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}
        """)
        root.addWidget(self._text)

    def log(self, agent_id: str, ev: dict):
        is_audio = (
            "content" in ev
            and any("inlineData" in pp
                    for pp in ev.get("content", {}).get("parts", []))
            and not any("text" in pp
                        for pp in ev.get("content", {}).get("parts", []))
        )
        if is_audio and not self._show_audio:
            return

        ts   = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        name = self._agent_names.get(agent_id, agent_id)
        emoji, summary, col = self._classify(ev)

        self._text.moveCursor(QTextCursor.MoveOperation.End)
        self._text.setTextColor(QColor(P["text3"]))
        self._text.insertPlainText(f"\n{ts} [{name}] ")
        self._text.setTextColor(QColor(col))
        self._text.insertPlainText(f"{emoji} {summary}\n")

        if not is_audio:
            ev2 = copy.deepcopy(ev)
            for pp in ev2.get("content", {}).get("parts", []):
                if "inlineData" in pp and "data" in pp["inlineData"]:
                    n = len(pp["inlineData"]["data"])
                    pp["inlineData"]["data"] = f"({int(n * 0.75):,} bytes)"
            self._text.setTextColor(QColor(P["text3"]))
            self._text.insertPlainText(json.dumps(ev2, indent=2)[:500] + "\n")

        self._text.moveCursor(QTextCursor.MoveOperation.End)

    def _classify(self, ev: dict) -> tuple[str, str, str]:
        if ev.get("subagent"):
            sa = ev["subagent"]
            emojis = {"computer_use": "💻", "image_generation": "🎨"}
            emoji = emojis.get(sa, "🤖")
            summary = ev.get("summary", "Subagent task")
            status  = ev.get("status")
            color   = P["accent"] if status == "running" else P["green"] if status == "completed" else P["red"] if status == "failed" else P["text2"]
            return emoji, summary, color

        if ev.get("turnComplete"):        return "✓", "Turn complete",  P["green"]
        if ev.get("interrupted"):         return "⏸", "Interrupted",    P["yellow"]
        if ev.get("inputTranscription"):
            t = ev["inputTranscription"].get("text", "")[:50]
            return "📝", f'In: "{t}"', P["text2"]
        if ev.get("outputTranscription"):
            t = ev["outputTranscription"].get("text", "")[:50]
            return "📝", f'Out: "{t}"', P["text2"]
        if ev.get("usageMetadata"):
            n = ev["usageMetadata"].get("totalTokenCount", "?")
            return "📊", f"Tokens: {n}", P["accent"]
        if c := ev.get("content"):
            parts = c.get("parts", [])
            if any("inlineData" in pp for pp in parts):
                return "🔊", "Audio response", P["text3"]
            if any("text" in pp for pp in parts):
                txt = next((pp["text"] for pp in parts if "text" in pp), "")[:60]
                return "💬", f'"{txt}"', P["text"]
        return "·", "Event", P["text3"]
