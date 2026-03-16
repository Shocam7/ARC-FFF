"""
arc/shared/session_bus.py
─────────────────────────
SessionBus — thread-safe shared dict acting as the action bus between
Mark and its background subagents (Computer Use, Image Generation).

SessionBusWatcher — async polling loop that detects changes on the bus
and injects narrative context into Mark's LiveRequestQueue as text.

Design notes
────────────
• Computer Use and Image Generation write to SessionBus from asyncio
  threads (via asyncio.to_thread). A threading.Lock guards all writes.
• SessionBusWatcher runs inside Mark's asyncio loop and polls every
  POLL_INTERVAL seconds. It enforces MIN_INJECT_INTERVAL so Mark's queue
  is not flooded when Computer Use is writing many rapid milestones.
• When a change is detected, the watcher sends a plain text message into
  Mark's LiveRequestQueue. Mark's LLM will naturally decide how/when to
  narrate it to the user (it does NOT interrupt mid-sentence because the
  Live API handles this via its own VAD + turn model).
"""

from __future__ import annotations

import asyncio
import copy
import logging
import threading
import time

from google.adk.agents.live_request_queue import LiveRequestQueue
from google.genai import types

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

POLL_INTERVAL     = 1.5   # seconds between bus polls
MIN_INJECT_INTERVAL = 5.0 # minimum seconds between queue injections (debounce)


# ── SessionBus ────────────────────────────────────────────────────────────────

class SessionBus:
    """
    Plain dict-backed action bus.

    Keys written by Computer Use:
        cu_last_action   str  — milestone description of last action
        cu_current_page  str  — current page / context
        cu_status        str  — "idle" | "running" | "completed" | "failed"
        cu_result        str  — final result text (set on completion)

    Keys written by Image Generation:
        img_status       str  — "idle" | "generating" | "completed" | "failed"
        img_result       str  — file path to saved image (set on completion)
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._input_ready = threading.Event()
        self._data: dict = {
            # Computer Use keys
            "cu_last_action":  "",
            "cu_current_page": "",
            "cu_status":       "idle",
            "cu_result":       "",
            # Image Generation keys
            "img_status":  "idle",
            "img_result":  "",
            # Human Input (HITL)
            "awaiting_input": False,
            "input_question": "",
            "input_value":    None,
        }

    # ── Computer Use writers ──────────────────────────────────────────────────

    def write_cu_action(
        self,
        action: str,
        page: str = "",
        status: str = "running",
        result: str = "",
    ):
        """Write a Computer Use milestone to the bus."""
        with self._lock:
            self._data["cu_last_action"]  = action
            self._data["cu_current_page"] = page
            self._data["cu_status"]       = status
            if result:
                self._data["cu_result"] = result
        logger.debug("[SessionBus] CU action: %s | status: %s", action, status)

    # ── Image Generation writers ───────────────────────────────────────────────

    def write_img_status(self, status: str, result: str = ""):
        """Write an Image Generation status update to the bus."""
        with self._lock:
            self._data["img_status"] = status
            if result:
                self._data["img_result"] = result
        logger.debug("[SessionBus] IMG status: %s", status)

    # ── Readers ───────────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """Return an atomic shallow copy of the current bus state."""
        with self._lock:
            return copy.copy(self._data)

    def get(self, key: str, default=None):
        with self._lock:
            return self._data.get(key, default)

    # ── Human Input (HITL) ──────────────────────────────────────────────────

    def set_awaiting_input(self, question: str):
        with self._lock:
            self._data["awaiting_input"] = True
            self._data["input_question"] = question
            self._data["input_value"]    = None
        self._input_ready.clear()

    def provide_input(self, value: str):
        with self._lock:
            self._data["input_value"] = value
        self._input_ready.set()

    def wait_for_input(self, timeout: float | None = None) -> str | None:
        """Blocks until provide_input is called."""
        if self._input_ready.wait(timeout):
            with self._lock:
                return self._data.get("input_value")
        return None

    def clear_input(self):
        with self._lock:
            self._data["awaiting_input"] = False
            self._data["input_question"] = ""
            self._data["input_value"]    = None
        self._input_ready.clear()

    # ── Reset helpers ─────────────────────────────────────────────────────────

    def reset_cu(self):
        with self._lock:
            self._data.update({
                "cu_last_action": "", "cu_current_page": "",
                "cu_status": "idle", "cu_result": "",
            })

    def reset_img(self):
        with self._lock:
            self._data.update({"img_status": "idle", "img_result": ""})


# ── SessionBusWatcher ─────────────────────────────────────────────────────────

class SessionBusWatcher:
    """
    Async polling watcher — runs inside Mark's asyncio loop.

    On each poll cycle it diffs the current bus snapshot against the last
    seen snapshot. When a meaningful change is detected it injects a short
    system text message into Mark's LiveRequestQueue so Mark can narrate
    the event naturally.

    Rate-limiting: even when the bus changes on every cycle, injections
    are spaced at least MIN_INJECT_INTERVAL seconds apart to avoid flooding
    Mark's turn with system messages mid-conversation.
    """

    def __init__(self):
        self._last_snapshot: dict = {}
        self._last_inject_ts: float = 0.0

    async def run(self, bus: SessionBus, lrq: LiveRequestQueue):
        """Main watcher loop. Runs until cancelled."""
        logger.debug("[SessionBusWatcher] Started")
        while True:
            try:
                await asyncio.sleep(POLL_INTERVAL)
            except asyncio.CancelledError:
                logger.debug("[SessionBusWatcher] Cancelled")
                return

            current = bus.snapshot()
            msg = self._build_message(current, self._last_snapshot)

            if not msg:
                self._last_snapshot = current
                continue

            # Bypass debounce for terminal states (completed/failed) so the agent
            # narrates the final result immediately without a 5s lag.
            is_terminal = any(s in msg for s in [
                "Finished.", "Failed or was cancelled.", 
                "Image ready:", "Image generation failed.",
                "Thread stopped"
            ])
            
            now = time.monotonic()
            if not is_terminal and (now - self._last_inject_ts) < MIN_INJECT_INTERVAL:
                # Too soon — skip injection this cycle; next poll will try again
                # because we haven't updated self._last_snapshot yet.
                logger.debug("[SessionBusWatcher] Debounced (%.1fs since last inject)",
                             now - self._last_inject_ts)
                continue

            self._inject(lrq, msg)
            self._last_inject_ts = now
            self._last_snapshot = current

    def _build_message(self, current: dict, prev: dict) -> str | None:
        """
        Compute a human-readable update string from bus diff.
        Returns None if nothing noteworthy changed.
        """
        parts: list[str] = []

        # ── Computer Use changes ─────────────────────────────────────────────
        cu_status  = current.get("cu_status", "idle")
        prev_cu    = prev.get("cu_status", "idle")
        cu_action  = current.get("cu_last_action", "")
        cu_page    = current.get("cu_current_page", "")
        cu_result  = current.get("cu_result", "")

        if cu_status == "running" and cu_action and cu_action != prev.get("cu_last_action"):
            loc = f" (on: {cu_page})" if cu_page else ""
            parts.append(f"[Computer Use] {cu_action}{loc}")

        elif cu_status == "completed" and prev_cu != "completed":
            # Detect if the task was actually finished or just hit a limit
            res_lower = cu_result.lower()
            if "incomplete" in res_lower or "timeout" in res_lower or "timed out" in res_lower:
                parts.append(f"[Computer Use] Thread stopped, but task is incomplete. Details: {cu_result}")
            else:
                summary = cu_result or "Task finished successfully."
                parts.append(f"[Computer Use] Finished. {summary}")

        elif cu_status == "failed" and prev_cu != "failed":
            parts.append("[Computer Use] Failed or was cancelled.")

        # ── HITL / Input Request changes ─────────────────────────────────────
        awaiting_input = current.get("awaiting_input", False)
        prev_awaiting = prev.get("awaiting_input", False)
        input_question = current.get("input_question", "")

        if awaiting_input and not prev_awaiting:
            parts.append(f"[Input Needed] The computer process is stuck and needs information: {input_question}")
        img_status = current.get("img_status", "idle")
        prev_img   = prev.get("img_status", "idle")
        img_result = current.get("img_result", "")

        if img_status == "generating" and prev_img != "generating":
            parts.append("[Image Generation] Generating image…")

        elif img_status == "completed" and prev_img != "completed":
            parts.append(f"[Image Generation] Image ready: {img_result}")

        elif img_status == "failed" and prev_img != "failed":
            parts.append("[Image Generation] Image generation failed.")

        if not parts:
            return None

        return (
            "[BACKGROUND UPDATE — narrate naturally, do not read this verbatim]\n"
            + "\n".join(parts)
        )

    def _inject(self, lrq: LiveRequestQueue, message: str):
        """Push a text message into Mark's Live request queue."""
        try:
            lrq.send_content(
                types.Content(
                    role="user",
                    parts=[types.Part(text=message)],
                )
            )
            logger.debug("[SessionBusWatcher] Injected: %s", message[:80])
        except Exception as exc:
            logger.warning("[SessionBusWatcher] Failed to inject: %s", exc)
