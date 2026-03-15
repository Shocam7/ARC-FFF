"""
arc/core/config.py
──────────────────
All constants, environment config, colour palette, and agent persona definitions.

Edit AGENT_PERSONAS to add/remove agents.
Edit aliases[] to teach the orchestrator which words map to each agent.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from PyQt6.QtGui import QColor

# ── Load .env ─────────────────────────────────────────────────────────────────
_here = Path(__file__).resolve().parent.parent.parent
for _c in [_here / "app" / ".env", _here / ".env", _here.parent / ".env"]:
    if _c.exists():
        load_dotenv(_c)
        break
else:
    load_dotenv()

# ── App ───────────────────────────────────────────────────────────────────────
APP_NAME = "arc"
SR_IN    = 16_000
SR_OUT   = 24_000

# ── Models ────────────────────────────────────────────────────────────────────
LIVE_MODEL_GEMINI = os.environ.get("GEMINI_MODEL", "")

# Orchestrator: fast text-only — routing decisions only, no audio.
ORCHESTRATOR_MODEL_GEMINI = "gemini-2.5-flash-lite"

# ── Backend env blocks ────────────────────────────────────────────────────────
# Applied to os.environ before every SDK call.
GEMINI_ENV = {
    "GOOGLE_API_KEY": os.environ.get("GOOGLE_API_KEY", ""),
}
# ── Agent personas ─────────────────────────────────────────────────────────────
# aliases: every word/phrase the orchestrator recognises as addressing this agent.
#          Checked case-insensitively. Be generous.
AGENT_PERSONAS = [
    {
        "id":    "scientist",
        "name":  "Dr. Nova",
        "field": "Science & Technology",
        "tile_label": "Dr. Nova  ·  Science & Tech",
        "instruction": (
            "You are Dr. Nova, a world-class expert in science, technology, physics, "
            "biology, chemistry, engineering, mathematics, and AI. "
            "You are in a live panel conference alongside Prof. Lex, a humanities scholar. "
            "IMPORTANT: The conversation history will be provided to you. Treat it as your shared memory. "
            "Reference Prof. Lex's points when relevant. "
            "Be concise and engaging. "
            "When a topic is better suited to Prof. Lex, address him naturally by name "
            "at the end of your turn — for example: 'Lex, what are your thoughts on that?' "
            "or 'Prof. Lex, I'd love to hear the historical perspective here.' "
            "Do NOT use meta-commentary like 'I'll hand it over' or 'passing to Lex'. "
            "Simply engage him conversationally as a colleague."
        ),
        "blob_colors": [
            (0x42, 0x85, 0xF4, 0.00,          0.50, 1.10),
            (0x00, 0xBC, 0xD4, 0.9 * 3.14159, 0.45, 0.90),
            (0x9C, 0x27, 0xB0, 0.3 * 3.14159, 0.35, 0.80),
            (0x42, 0x85, 0xF4, 1.1 * 3.14159, 0.55, 0.85),
            (0x1A, 0x73, 0xE8, 1.6 * 3.14159, 0.40, 0.95),
        ],
    },
    {
        "id":    "historian",
        "name":  "Prof. Lex",
        "field": "History & Philosophy",
        "tile_label": "Prof. Lex  ·  History & Philosophy",
        "instruction": (
            "You are Prof. Lex, a distinguished scholar of history, philosophy, "
            "literature, art, and culture. "
            "You are in a live panel conference alongside Dr. Nova, a scientist. "
            "IMPORTANT: The conversation history will be provided to you. Treat it as your shared memory. "
            "Reference Dr. Nova's points when relevant. "
            "Be thoughtful and draw on historical examples. "
            "When a topic is better suited to Dr. Nova, address him naturally by name "
            "at the end of your turn — for example: 'Nova, what does the science say here?' "
            "or 'Dr. Nova, I'd be curious to hear your take on the technical side.' "
            "Do NOT use meta-commentary like 'I'll pass this to Nova' or 'over to you'. "
            "Simply engage him conversationally as a colleague."
        ),
        "blob_colors": [
            (0xEA, 0x43, 0x35, 0.00,          0.50, 1.10),
            (0xFB, 0xBC, 0x04, 0.9 * 3.14159, 0.55, 1.00),
            (0xFF, 0x67, 0x22, 0.3 * 3.14159, 0.38, 0.85),
            (0x34, 0xA8, 0x53, 1.4 * 3.14159, 0.50, 1.05),
            (0xEA, 0x43, 0x35, 1.8 * 3.14159, 0.45, 0.90),
        ],
    },
    {
        "id":    "mark",
        "name":  "Mark",
        "field": "General Assistant & Task Narrator",
        "tile_label": "Mark  ·  Assistant",
        # Instruction is imported lazily to avoid circular imports at module load time.
        # MarkWorker overrides _main() and passes MARK_INSTRUCTION directly;
        # this entry is used by OrchestratorWorker for routing descriptions only.
        "instruction": (
            "You are Mark, a friendly real-time AI assistant. "
            "You can search the web, narrate computer actions, and generate images."
        ),
        "blob_colors": [
            (0x34, 0xA8, 0x53, 0.00,          0.50, 1.10),
            (0x00, 0xE6, 0x76, 0.9 * 3.14159, 0.45, 0.90),
            (0x1D, 0xC4, 0x6A, 0.3 * 3.14159, 0.38, 0.85),
            (0x34, 0xA8, 0x53, 1.1 * 3.14159, 0.55, 0.85),
            (0x0B, 0x80, 0x43, 1.6 * 3.14159, 0.40, 0.95),
        ],
    },
]

# ── UI palette ────────────────────────────────────────────────────────────────
P = {
    "bg":        "#0f0f0f",
    "surface":   "#1c1c1c",
    "raised":    "#282828",
    "tile_dark": "#0d0d12",
    "border":    "#2a2a2a",
    "border_hi": "#444444",
    "accent":    "#8ab4f8",
    "text":      "#e8eaed",
    "text2":     "#9aa0a6",
    "text3":     "#5f6368",
    "agent_bub": "#1a2a1a",
    "user_bub":  "#1a3a5c",
    "sys_bub":   "#1e1e1e",
    "err_bub":   "#2a1010",
    "green":     "#34a853",
    "red":       "#ea4335",
    "yellow":    "#fbbc04",
}

GEMINI_COLORS = [
    QColor(0xEA, 0x43, 0x35),
    QColor(0xFB, 0xBC, 0x04),
    QColor(0x34, 0xA8, 0x53),
    QColor(0x42, 0x85, 0xF4),
]

FONT_UI   = "Segoe UI,Inter,SF Pro Display,sans-serif"
FONT_MONO = "Consolas,JetBrains Mono,Fira Code,monospace"

def get_personas() -> list[dict]:
    return AGENT_PERSONAS