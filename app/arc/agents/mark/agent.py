"""
arc/agents/mark/agent.py
─────────────────────────
MarkWorker — LiveAgentWorker subclass for the Mark agent.

Mark now inherits all advanced capabilities (Computer Use, Image Gen, Search)
from the base LiveAgentWorker. This subclass exists primarily to apply
Mark's specific instruction and model.
"""

from __future__ import annotations

import logging
from .prompts import MARK_INSTRUCTION
from ..live_agent import LiveAgentWorker

logger = logging.getLogger(__name__)

MARK_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"


class MarkWorker(LiveAgentWorker):
    """
    MarkWorker — specialized for the "Mark" persona.
    All background task logic and tool definitions are now inherited from LiveAgentWorker.
    """

    def __init__(
        self,
        persona: dict,
        shared_log: any,
        startup_delay: float = 0.0,
    ):
        # Ensure the persona has the correct instruction if not already set
        if not persona.get("instruction") or persona["instruction"] == "You are Mark":
            persona["instruction"] = MARK_INSTRUCTION
            
        super().__init__(
            persona=persona,
            shared_log=shared_log,
            startup_delay=startup_delay,
        )
        logger.info("[Mark] Initialized using enhanced LiveAgentWorker base.")

    # MarkWorker no longer needs to override _main or shutdown as the base 
    # class now handles the background tasks, events, and bus watching.
