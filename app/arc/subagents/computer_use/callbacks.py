"""
arc/subagents/computer_use/callbacks.py
────────────────────────────────────────
on_before_action / on_after_action callbacks for the Computer Use agent.

These intercept every step the CU model takes (click, scroll, type, navigate,
etc.) and batch micro-actions into readable milestone descriptions before
writing them to the shared SessionBus.

Batching logic
──────────────
• Navigation-type actions (goto_url, open_tab, search) → "Navigating to …"
• Form/input actions (type, fill, select) → "Entering data …"
• Click actions → "Clicking on …"
• Scroll / screenshot actions → grouped, not individually narrated
• Any other tool → emitted as-is with a truncated summary

Only one milestone write per action step (even if a step involves multiple
granular operations) to keep the bus lean.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Action-type grouping ──────────────────────────────────────────────────────

_NAV_VERBS   = {"goto_url", "navigate", "open_url", "search", "open_tab"}
_FORM_VERBS  = {"type", "fill", "set_text", "select", "change_value"}
_CLICK_VERBS = {"click", "left_click", "right_click", "double_click", "tap", "click_at"}
_PAGE_VERBS  = {"print_page", "print", "save_page", "save", "share_page"}
_WINDOW_VERBS = {"close_application", "close_window", "minimize_window", "maximize_window", "restore_window"}
_APP_VERBS   = {"open_application", "open_app", "launch_app", "run_application"}


def _summarise_action(tool_name: str, tool_args: dict) -> str:
    """Convert a raw tool call into a readable milestone description."""
    name = (tool_name or "").lower()

    if name in _NAV_VERBS:
        target = tool_args.get("url") or tool_args.get("query") or tool_args.get("value", "")
        if target:
            return f"Navigating to {target}"
        return "Navigating to a new page"

    if name in _FORM_VERBS:
        value = tool_args.get("value") or tool_args.get("text", "")
        field = tool_args.get("selector") or tool_args.get("element", "")
        if value and field:
            return f"Entering data into {field}"
        return "Filling in a form field"

    if name in _CLICK_VERBS:
        target = (
            tool_args.get("selector")
            or tool_args.get("element")
            or tool_args.get("text", "")
        )
        if target:
            return f"Clicking on '{target}'"
        return "Clicking an element"

    if name in {"scroll", "scroll_to"}:
        return ""   # silently skip scrolls — too granular

    if name == "screenshot":
        return ""   # skip screenshot steps

    if name in _PAGE_VERBS:
        if "print" in name:
            return "Printing page"
        if "save" in name:
            return "Saving page"
        if "share" in name:
            return "Sharing page"

    if name in {"download_file", "download"}:
        url = tool_args.get("url") or tool_args.get("link", "")
        return f"Downloading from {url[:50]}…" if url else "Downloading file"

    if name in {"upload_file", "select_file", "attach_file"}:
        return "Uploading / selecting file"

    if name in _WINDOW_VERBS:
        if "close" in name:
            return "Closing window"
        if "minimize" in name:
            return "Minimizing window"
        if "maximize" in name:
            return "Maximizing window"
        if "restore" in name:
            return "Restoring window"

    if name in _APP_VERBS:
        app = tool_args.get("application") or tool_args.get("app") or tool_args.get("name", "")
        return f"Opening {app}" if app else "Opening application"

    # Generic fallback
    summary = tool_args.get("description") or tool_args.get("value") or name
    return str(summary)[:80] if summary else name


# ── Callback functions ────────────────────────────────────────────────────────

def on_before_action(
    tool_name: str,
    tool_args: dict,
    bus: Any,  # SessionBus — avoid import cycle
    page_context: str = "",
):
    """
    Called immediately before each CU action step executes.
    Writes the upcoming milestone to the bus so Mark can narrate proactively.
    """
    milestone = _summarise_action(tool_name, tool_args)
    if not milestone:
        return   # skip silent actions (scroll, screenshot)

    bus.write_cu_action(
        action=milestone,
        page=page_context,
        status="running",
    )
    logger.debug("[CU before] %s — %s", tool_name, milestone)


def on_after_action(
    tool_name: str,
    tool_args: dict,
    result: Any,
    bus: Any,
    page_context: str = "",
):
    """
    Called immediately after each CU action step completes.
    Optionally updates the current page context from navigation results.
    """
    name = (tool_name or "").lower()

    # Update current page when navigation completes
    if name in _NAV_VERBS:
        url = ""
        if isinstance(result, dict):
            url = result.get("url") or result.get("current_url", "")
        elif isinstance(result, str):
            url = result[:120]

        if url:
            bus.write_cu_action(
                action=f"Arrived at {url}",
                page=url,
                status="running",
            )
            logger.debug("[CU after] Arrived at %s", url)
