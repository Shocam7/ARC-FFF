"""
arc/ui/widgets/transcript_panel.py
────────────────────────────────────
TranscriptPanel — scrolling conversation transcript shown below the video tiles.

Handles multi-agent output: each agent's transcription is labelled with the
agent's name so the user can tell who said what.
"""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui  import QFont

from ...core.config import P, FONT_UI


class TranscriptPanel(QWidget):
    def __init__(self, agent_names: dict[str, str], parent=None):
        """
        agent_names : {agent_id: display_name}
        """
        super().__init__(parent)
        self._agent_names = agent_names

        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(f"""
            QScrollArea{{border:none;background:transparent;}}
            QScrollBar:vertical{{background:transparent;width:5px;}}
            QScrollBar::handle:vertical{{background:{P['border_hi']};border-radius:2px;}}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}
        """)
        self._cont = QWidget()
        self._cont.setStyleSheet("background:transparent;")
        self._vl = QVBoxLayout(self._cont)
        self._vl.setAlignment(Qt.AlignmentFlag.AlignBottom)
        self._vl.setSpacing(4)
        self._vl.setContentsMargins(14, 8, 14, 8)
        self._scroll.setWidget(self._cont)
        vl.addWidget(self._scroll)

        # Per-agent state
        self._cur_out:  dict[str, QLabel | None] = {k: None for k in agent_names}
        self._cur_out_text: dict[str, str]        = {k: "" for k in agent_names}
        self._cur_in:   QLabel | None             = None
        self._cur_in_text: str                    = ""
        self._in_done:  bool                      = False
        self._has_out_trans: bool                 = False
        self._cur_msg:  dict[str, QLabel | None]  = {k: None for k in agent_names}

    def register_agent(self, agent_id: str, display_name: str):
        """Dynamically add state for a new agent."""
        if agent_id not in self._agent_names:
            self._agent_names[agent_id] = display_name
            self._cur_out[agent_id] = None
            self._cur_out_text[agent_id] = ""
            self._cur_msg[agent_id] = None

    # ── Bubble factory ────────────────────────────────────────────────────────

    def _bubble(self, text: str, align="left", bg=None, italic=False,
                tag: str = "") -> tuple[QWidget, QLabel]:
        bg = bg or P["agent_bub"]
        row = QWidget(); row.setStyleSheet("background:transparent;")
        hl  = QHBoxLayout(row); hl.setContentsMargins(0, 0, 0, 0)

        col_w = QWidget(); col_w.setStyleSheet("background:transparent;")
        col   = QVBoxLayout(col_w); col.setContentsMargins(0, 0, 0, 0); col.setSpacing(2)

        if tag:
            tag_lbl = QLabel(tag)
            tag_lbl.setFont(QFont(FONT_UI, 8))
            tag_lbl.setStyleSheet(f"color:{P['text3']};background:transparent;border:none;")
            col.addWidget(tag_lbl)

        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setMaximumWidth(580)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lbl.setFont(QFont(FONT_UI, 10 if sys.platform != "darwin" else 13))
        lbl.setStyleSheet(f"""
            QLabel{{background:{bg};
                    color:{P['text2'] if italic else P['text']};
                    border-radius:10px; padding:7px 13px;
                    font-style:{'italic' if italic else 'normal'};}}
        """)
        col.addWidget(lbl)

        if align == "right":
            hl.addStretch(1); hl.addWidget(col_w)
        elif align == "center":
            hl.addStretch(1); hl.addWidget(col_w); hl.addStretch(1)
        else:
            hl.addWidget(col_w); hl.addStretch(1)
        return row, lbl

    def _add(self, widget: QWidget):
        self._vl.addWidget(widget)
        QTimer.singleShot(30, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()))

    # ── Public slots ─────────────────────────────────────────────────────────

    def add_system(self, text: str, error: bool = False):
        bg = P["err_bub"] if error else P["sys_bub"]
        row, _ = self._bubble(text, "center", bg=bg)
        self._add(row)

    def on_text_received(self, agent_id: str, text: str, partial: bool):
        if not partial and self._has_out_trans:
            return
        if self._cur_msg[agent_id] is None:
            name = self._agent_names.get(agent_id, agent_id)
            row, lbl = self._bubble("", "left", P["agent_bub"], tag=name)
            self._cur_msg[agent_id] = lbl
            self._finalize_in_trans()
            self._add(row)
        t = self._cur_msg[agent_id].text()
        if t.endswith(" ▌"): t = t[:-2]
        self._cur_msg[agent_id].setText(t + text + (" ▌" if partial else ""))

    def on_input_transcription(self, text: str, finished: bool):
        if self._in_done:
            return
        if self._cur_in is None:
            row, lbl = self._bubble(text, "right", P["user_bub"], italic=True)
            self._cur_in = lbl; self._cur_in_text = text
            self._add(row)
        else:
            if finished:
                self._cur_in.setText(text); self._cur_in_text = text
            else:
                self._cur_in_text += text
                self._cur_in.setText(self._cur_in_text + " ▌")
        if finished:
            self._cur_in = None; self._cur_in_text = ""; self._in_done = True

    def on_output_transcription(self, agent_id: str, text: str, finished: bool):
        self._has_out_trans = True
        self._finalize_in_trans()
        name = self._agent_names.get(agent_id, agent_id)
        if self._cur_out[agent_id] is None:
            row, lbl = self._bubble(text, "left", P["agent_bub"],
                                    italic=True, tag=name)
            self._cur_out[agent_id] = lbl
            self._cur_out_text[agent_id] = text
            self._add(row)
        else:
            if finished:
                self._cur_out[agent_id].setText(text)
            else:
                self._cur_out_text[agent_id] += text
                self._cur_out[agent_id].setText(self._cur_out_text[agent_id] + " ▌")
        if finished:
            self._cur_out[agent_id] = None
            self._cur_out_text[agent_id] = ""

    def on_turn_complete(self, agent_id: str):
        lbl = self._cur_msg.get(agent_id)
        if lbl:
            t = lbl.text()
            if t.endswith(" ▌"): lbl.setText(t[:-2])
        self._cur_msg[agent_id] = None
        out = self._cur_out.get(agent_id)
        if out:
            t = out.text()
            if t.endswith(" ▌"): out.setText(t[:-2])
        self._cur_out[agent_id] = None
        self._cur_out_text[agent_id] = ""
        self._in_done = False
        self._has_out_trans = False

    def on_interrupted(self, agent_id: str):
        self._cur_msg[agent_id] = None
        self._cur_out[agent_id] = None
        self._cur_out_text[agent_id] = ""
        self._in_done = False
        self._has_out_trans = False

    def _finalize_in_trans(self):
        if self._cur_in:
            t = self._cur_in.text()
            if t.endswith(" ▌"): self._cur_in.setText(t[:-2])
            self._cur_in = None; self._cur_in_text = ""; self._in_done = True
