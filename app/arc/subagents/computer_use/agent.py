"""
arc/subagents/computer_use/agent.py
────────────────────────────────────
run_computer_use_background — independent async background task.

Architecture
────────────
• Gated by an asyncio.Event (trigger_ev) — waits until Mark's LLM calls
  trigger_computer_use() which sets the event via loop.call_soon_threadsafe.
• Wrapped in asyncio.create_task() by MarkWorker, so .cancel() provides
  real CancelledError delivery at the await points.
• All google.genai blocking calls run inside asyncio.to_thread() so
  Mark's upstream/downstream tasks are never stalled.
• Writes step-by-step milestones to SessionBus via on_before_action /
  on_after_action callbacks; final status written on completion or failure.

Model
─────
gemini-2.5-computer-use-preview-10-2025 is invoked via google.genai
client.models.generate_content (not ADK Runner — it is a specialist
computer-use model, not a conversational agent).
"""

from __future__ import annotations

import asyncio
import logging
import os

from google import genai
from google.genai import types as gtypes

from ...core.config import GEMINI_ENV
from ...shared.session_bus import SessionBus
from .callbacks import on_before_action, on_after_action
from .executor import execute_action, take_screenshot

logger = logging.getLogger(__name__)

CU_MODEL = "gemini-2.5-computer-use-preview-10-2025"


# ── Public entry point ────────────────────────────────────────────────────────

async def run_computer_use_background(
    bus: SessionBus,
    trigger_ev: asyncio.Event,
    task_ref: list,   # mutable single-element list: task_ref[0] = task string
):
    """
    Background coroutine — runs inside Mark's asyncio.gather().

    Waits for trigger_ev to be set (by trigger_computer_use FunctionTool),
    then executes the computer use task in a thread, writing milestone
    updates to the SessionBus as it progresses.

    Cancelled cleanly when Mark's session ends (via asyncio Task.cancel()).
    """
    logger.info("[ComputerUse] Waiting for trigger…")

    try:
        await trigger_ev.wait()
    except asyncio.CancelledError:
        logger.info("[ComputerUse] Cancelled before trigger")
        return

    task = task_ref[0]
    logger.info("[ComputerUse] Triggered with task: %s", task[:80])
    bus.write_cu_action(action="Starting computer task…", status="running")

    try:
        # All blocking I/O runs in a thread so Mark's loop stays free ✓
        result = await asyncio.to_thread(_blocking_cu_call, task, bus)
        bus.write_cu_action(
            action="Task completed",
            status="completed",
            result=result,
        )
        logger.info("[ComputerUse] Completed: %s", result[:120])

    except asyncio.CancelledError:
        # task.cancel() was called — shut down cleanly
        bus.write_cu_action(action="Task cancelled", status="failed")
        logger.info("[ComputerUse] Cancelled during execution")
        raise  # re-raise so asyncio.gather / create_task knows it's done

    except Exception as exc:
        bus.write_cu_action(action=f"Error: {exc}", status="failed")
        logger.error("[ComputerUse] Failed: %s", exc)


# ── Blocking worker (runs in asyncio.to_thread) ────────────────────────────

def _blocking_cu_call(task: str, bus: SessionBus) -> str:
    """
    Synchronous google.genai call — safe to block here (runs in a thread).

    Simulates an agentic computer-use loop:
      1. Send the task prompt with computer-use tool enabled.
      2. Parse tool calls from the response — invoke on_before/after_action.
      3. Continue until the model returns a final text result.

    Returns the final text result from the model.
    """
    os.environ.update(GEMINI_ENV)
    client = genai.Client()

    # Build the initial request
    tools = [gtypes.Tool(computer_use=gtypes.ComputerUse())]
    config = gtypes.GenerateContentConfig(
        tools=tools,
        system_instruction=(
            "You are a computer-use agent. Complete the task step by step. "
            "Use computer tools to interact with the screen. "
            "You can: navigate to URLs; click, type, fill forms; take screenshots; "
            "print/save/share the page; upload a file (path) or download from a URL; "
            "open, close, minimize, maximize, or restore desktop applications. "
            "After completing each action, give a brief status check.\n\n"
            "If the screenshot shows a DIFFERENT application (e.g. ARC, or not the browser or target website): "
            "first try to switch to the browser (use key/hotkey: Alt+Tab one or more times to bring the browser forward). "
            "If after trying you still cannot see the right window, respond with a clear message to the user: "
            "'I need the booking website (or target page) to be visible. Please switch to your browser and bring that tab to the front so I can continue.' "
            "Never leave the user without an explanation: if you cannot proceed, say so clearly and tell them what to do."
        ),
    )

    contents: list[gtypes.Content] = [
        gtypes.Content(role="user", parts=[gtypes.Part(text=task)])
    ]

    page_context = ""
    final_text   = ""

    # Agentic loop — continue until model stops calling tools
    max_steps = 30
    for step in range(max_steps):
        logger.debug("[ComputerUse] Step %d/%d", step + 1, max_steps)

        response = client.models.generate_content(
            model=CU_MODEL,
            contents=contents,
            config=config,
        )

        candidate = response.candidates[0] if response.candidates else None
        if not candidate:
            break

        content = candidate.content
        tool_calls_found = False

        for part in (content.parts or []):
            # ── Tool call from model ──────────────────────────────────────────
            if part.function_call:
                fc        = part.function_call
                tool_name = fc.name or ""
                tool_args = dict(fc.args or {})
                tool_calls_found = True

                # Notify bus BEFORE executing (narrate intent)
                on_before_action(tool_name, tool_args, bus, page_context)

                # If the model sent a safety_decision (e.g. require_confirmation), do not
                # execute the action; return an acknowledgment so the API accepts the response.
                safety = tool_args.get("safety_decision")
                if isinstance(safety, dict) and safety.get("decision") == "require_confirmation":
                    tool_result = {
                        "status": "success",
                        "output": safety.get("explanation", "Safety decision acknowledged."),
                        "safety_decision_acknowledged": True,
                    }
                else:
                    # Execute real action (screenshot, click, type, navigate, etc.)
                    tool_result = execute_action(tool_name, tool_args)
                    if tool_result.get("status") == "error":
                        tool_result = {"status": "error", "output": tool_result.get("error", "Unknown error")}

                # Take screenshot and attach so the model sees the new state
                try:
                    screenshot_bytes = take_screenshot()
                    response_parts = [
                        gtypes.FunctionResponsePart.from_bytes(
                            data=screenshot_bytes,
                            mime_type="image/png",
                        )
                    ]
                except Exception as e:
                    logger.warning("[ComputerUse] Screenshot failed: %s", e)
                    response_parts = None

                # Notify bus AFTER executing (update page context if nav)
                on_after_action(tool_name, tool_args, tool_result, bus, page_context)
                if tool_args.get("url"):
                    page_context = tool_args["url"]
                if isinstance(tool_result, dict) and tool_result.get("url"):
                    page_context = tool_result["url"]

                # Computer Use API requires every function response to include url/current_url
                if isinstance(tool_result, dict):
                    if "url" not in tool_result and "current_url" not in tool_result:
                        tool_result = dict(tool_result)
                        tool_result["current_url"] = page_context or "about:blank"

                # Append tool result + screenshot back to conversation
                contents.append(
                    gtypes.Content(role="model", parts=[part])
                )
                contents.append(
                    gtypes.Content(
                        role="user",
                        parts=[gtypes.Part(
                            function_response=gtypes.FunctionResponse(
                                name=tool_name,
                                response=tool_result,
                                parts=response_parts,
                            )
                        )],
                    )
                )

            # ── Final text answer from model ──────────────────────────────────
            elif part.text:
                final_text = part.text

        if not tool_calls_found:
            # Model gave a pure text response — task is done
            break

    return final_text or "Computer use task complete."
