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
from typing import Callable, Any

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
    on_event: Callable[[dict[str, Any]], Any] | None = None,
):
    """
    Background coroutine — runs inside Mark's asyncio.gather().

    Waits for trigger_ev to be set (by trigger_computer_use FunctionTool),
    then executes the computer use task in a thread, writing milestone
    updates to the SessionBus as it progresses.

    Cancelled cleanly when Mark's session ends (via asyncio Task.cancel()).
    """
    while True:
        logger.info("[ComputerUse] Waiting for trigger…")
        bus.reset_cu()

        try:
            await trigger_ev.wait()
            trigger_ev.clear()
        except asyncio.CancelledError:
            logger.info("[ComputerUse] Cancelled waiting for trigger")
            return

        task = task_ref[0]
        logger.info("[ComputerUse] Triggered with task: %s", task[:80])
        bus.write_cu_action(action="Starting computer task…", status="running")

        try:
            if callable(on_event):
                on_event({"subagent": "computer_use", "status": "running", "summary": f"Task: {task}"})
            # All blocking I/O runs in a thread so Mark's loop stays free ✓
            result = await asyncio.to_thread(_blocking_cu_call, task, bus, on_event)
            if callable(on_event):
                on_event({"subagent": "computer_use", "status": "completed", "summary": "Task completed", "result": result})
            bus.write_cu_action(
                action="Task completed",
                status="completed",
                result=result,
            )
            logger.info("[ComputerUse] Completed: %s", result[:120])

        except asyncio.CancelledError:
            # task.cancel() was called — shut down cleanly
            if callable(on_event):
                on_event({"subagent": "computer_use", "status": "failed", "summary": "Task cancelled"})
            bus.write_cu_action(action="Task cancelled", status="failed")
            logger.info("[ComputerUse] Cancelled during execution")
            raise  # re-raise so asyncio.gather / create_task knows it's done

        except Exception as exc:
            if callable(on_event):
                on_event({"subagent": "computer_use", "status": "failed", "summary": f"Error: {exc}"})
            bus.write_cu_action(action=f"Error: {exc}", status="failed")
            logger.error("[ComputerUse] Failed: %s", exc)


# ── Blocking worker (runs in asyncio.to_thread) ────────────────────────────

def _blocking_cu_call(task: str, bus: SessionBus, on_event: Callable = None) -> str:
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

    # Build the initial request. Note: Documentation requires computer_use and 
    # function_declarations to be in separate tool objects.
    tools = [
        gtypes.Tool(
            computer_use=gtypes.ComputerUse(
                environment=gtypes.Environment.ENVIRONMENT_BROWSER
            )
        ),
        gtypes.Tool(
            function_declarations=[
                gtypes.FunctionDeclaration(
                    name="request_user_input",
                    description="Pause the task and ask the user for specific missing information (like a password, personal detail, or clarification). Use this when you are stuck or need the user to provide data not available on the screen.",
                    parameters=gtypes.Schema(
                        type="OBJECT",
                        properties={
                            "question": gtypes.Schema(
                                type="STRING",
                                description="The specific question or information needed from the user."
                            )
                        },
                        required=["question"]
                    )
                ),
                gtypes.FunctionDeclaration(
                    name="memorize",
                    description="Store a piece of information (text, code, architecture details) in persistent memory for later recall. Useful for cross-application tasks or complex data analysis.",
                    parameters=gtypes.Schema(
                        type="OBJECT",
                        properties={
                            "key": gtypes.Schema(type="STRING", description="A unique identifier for the information."),
                            "value": gtypes.Schema(type="STRING", description="The information to store.")
                        },
                        required=["key", "value"]
                    )
                ),
                gtypes.FunctionDeclaration(
                    name="recall",
                    description="Retrieve previously stored information from memory by its key. If no key is provided, it lists all available keys.",
                    parameters=gtypes.Schema(
                        type="OBJECT",
                        properties={
                            "key": gtypes.Schema(type="STRING", description="The identifier of the information to recall.")
                        },
                    )
                )
            ]
        )
    ]
    config = gtypes.GenerateContentConfig(
        tools=tools,
        automatic_function_calling={'disable': True},
        system_instruction=(
            "# Role: Autonomous Digital Intelligence\n\n"
            "You are a state-of-the-art computer operator capable of autonomous web surfing, complex data processing, and cross-application multi-tasking. "
            "Your goal is to complete tasks with human-like intuition and digital precision.\n\n"
            "## Core Capabilities\n"
            "- **Autonomous Web Surfing**: You navigate Chrome, select search keywords, and analyze page layouts in real-time.\n"
            "- **Screen Analysis & Memory**: You 'memorize' what you see. If you encounter neural network architectures, long text, or complex data, use the 'memorize' tool to store it for later recall.\n"
            "- **Cross-Application Assistance**: You bridge applications. You can read a research paper in a browser, memorize key points, then switch to a code editor to implement them.\n"
            "- **Universal Interaction**: You work across ANY window—media players, games, specialized tools, and system settings.\n"
            "- **Complex Processing**: You can write professional emails, find eco-friendly alternatives, analyze medical images (like X-rays shown on screen), and interpret specialized data.\n"
            "- **Live Execution**: Provide continuous feedback.\n\n"
            "## Operating Principles\n"
            "- **Step-by-Step Execution**: Analyze the screen state, plan the next logical action, and execute it.\n"
            "- **Verification**: After every action, re-evaluate the screen state to ensure success.\n"
            "- **Honesty & Persistence**: NEVER claim success unless you see the final confirmation.\n"
            "- **Minimalism**: Use the most direct path to the goal.\n\n"
            "## Tool Protocol\n"
            "- **Memory**: Use 'memorize' for data you will need laterally or later. Use 'recall' to check your notes.\n"
            "- **App Launching**: Use 'open_application' for desktop apps and 'open_web_browser' for web tasks.\n\n"
            "## Interaction Protocol\n"
            "1. **Narrate**: Your text responses are used to narrate progress. Think out loud about what you see.\n"
            "2. **Request Input**: Use 'request_user_input' whenever you need human intervention (credentials, missing data, clarification).\n"
            "3. **Confirm**: Always verify the final result before reporting completion."
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

        if callable(on_event):
            on_event({"subagent": "computer_use", "status": "running", "summary": "Thinking..."})

        candidate = response.candidates[0] if response.candidates else None
        if not candidate or not candidate.content:
            break

        content = candidate.content
        
        # Collect parallel tool calls from this turn
        turn_model_parts: list[gtypes.Part] = []
        turn_user_parts: list[gtypes.Part] = []
        
        found_tool_call = False

        for part in (content.parts or []):
            if part.function_call:
                found_tool_call = True
                fc = part.function_call
                tool_name = fc.name or ""
                tool_args = dict(fc.args or {})
                
                # Model turn: Include the part containing the function call
                turn_model_parts.append(part)

                # Narrate intent
                on_before_action(tool_name, tool_args, bus, page_context)
                if callable(on_event):
                    on_event({"subagent": "computer_use", "status": "running", "summary": f"Action: {tool_name}", "data": tool_args})

                # Handle tool execution
                safety = tool_args.get("safety_decision")
                safety_ack = False
                
                if isinstance(safety, dict) and safety.get("decision") == "require_confirmation":
                    # PAUSE and ask user for confirmation
                    explanation = safety.get("explanation", "Safety confirmation requested.")
                    confirmed = _confirm_safety(explanation, bus, on_event)
                    
                    if confirmed:
                        # User approved -> Execute real action
                        tool_result = execute_action(tool_name, tool_args)
                        safety_ack = True
                    else:
                        # User denied -> Error response
                        tool_result = {"status": "error", "error": "User denied safety confirmation for this action."}
                
                elif tool_name == "request_user_input":
                    tool_result = _handle_user_input_request(tool_args, bus, on_event)
                else:
                    # Regular action or non-confirmation safety decision
                    tool_result = execute_action(tool_name, tool_args)
                    if isinstance(safety, dict):
                        safety_ack = True # Acknowledge non-blocker safety decisions

                # Apply safety acknowledgement flag if confirmed/needed
                if safety_ack:
                    if not isinstance(tool_result, dict):
                        tool_result = {"status": "success", "output": str(tool_result)}
                    tool_result["safety_acknowledgement"] = True

                if callable(on_event):
                    on_event({"subagent": "computer_use", "status": "running", "summary": f"Result: {tool_result.get('status', 'unknown')}", "data": tool_result})

                # Ensure result has current_url for Computer Use API
                if isinstance(tool_result, dict):
                    if "url" not in tool_result and "current_url" not in tool_result:
                        tool_result["current_url"] = page_context or "about:blank"
                
                # Update local context if navigation happened
                on_after_action(tool_name, tool_args, tool_result, bus, page_context)
                if isinstance(tool_result, dict) and tool_result.get("url"):
                    page_context = tool_result["url"]
                elif tool_args.get("url"):
                    page_context = tool_args["url"]

                # Take screenshot to show the result of this action
                response_parts = []
                try:
                    if callable(on_event):
                        on_event({"subagent": "computer_use", "status": "running", "summary": "Taking screenshot..."})
                    screenshot_bytes = take_screenshot()
                    response_parts.append(
                        gtypes.FunctionResponsePart.from_bytes(
                            data=screenshot_bytes,
                            mime_type="image/png",
                        )
                    )
                except Exception as e:
                    logger.warning("[ComputerUse] Screenshot failed: %s", e)

                # User turn: Add the FunctionResponse part
                turn_user_parts.append(
                    gtypes.Part(
                        function_response=gtypes.FunctionResponse(
                            name=tool_name,
                            response=tool_result,
                            parts=response_parts,
                        )
                    )
                )
            
            elif part.text:
                final_text = part.text
                turn_model_parts.append(part)

        # Update history with the model turn and user response turn
        if found_tool_call:
            contents.append(gtypes.Content(role="model", parts=turn_model_parts))
            contents.append(gtypes.Content(role="user", parts=turn_user_parts))
        else:
            # Task finished (final answer)
            break

    else:
        # Loop finished by hitting max_steps
        if final_text:
            return f"Task incomplete after {max_steps} steps. Last report: {final_text}"
        return f"Task timed out after {max_steps} execution steps without a final answer."

    return final_text or "Computer use task complete."


def _handle_user_input_request(tool_args: dict, bus: SessionBus, on_event: Callable | None = None) -> dict:
    """Helper to process request_user_input tool and return tool_result."""
    question = tool_args.get("question", "Please provide information.")
    logger.info("[ComputerUse] Requesting user input: %s", question)
    
    # Update status pill and notify
    if callable(on_event):
        on_event({"subagent": "computer_use", "status": "awaiting", "summary": "Awaiting user input", "question": question})
    
    bus.set_awaiting_input(question)
    bus.write_cu_action(action=f"Awaiting user input: {question}", status="running")
    
    # Wait for human to type something
    user_resp = bus.wait_for_input()
    bus.clear_input()
    
    if user_resp:
        return {"status": "success", "output": f"User provided: {user_resp}\n\nPlease resume the task."}
    else:
        return {"status": "error", "output": "No input received or task cancelled."}


def _confirm_safety(explanation: str, bus: SessionBus, on_event: Callable | None) -> bool:
    """Helper to ask for safety confirmation and return True if approved."""
    logger.info("[ComputerUse] Awaiting safety confirmation: %s", explanation)
    if callable(on_event):
        on_event({"subagent": "computer_use", "status": "awaiting", "summary": "Safety Confirmation Required", "question": explanation})
    
    bus.set_awaiting_input(f"SAFETY CONFIRMATION: {explanation}\n\nType 'yes' or 'proceed' to allow this action.")
    resp = bus.wait_for_input()
    bus.clear_input()
    
    return resp.lower().strip() in ("yes", "y", "proceed", "allow")
