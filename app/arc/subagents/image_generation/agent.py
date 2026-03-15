"""
arc/subagents/image_generation/agent.py
────────────────────────────────────────
run_image_generation_background — independent async background task.

Architecture
────────────
• Gated by asyncio.Event (trigger_ev) — set by trigger_image_generation()
  FunctionTool via loop.call_soon_threadsafe.
• Wrapped in asyncio.create_task() by MarkWorker for real .cancel() support.
• All google.genai blocking calls run in asyncio.to_thread() so Mark's
  upstream/downstream tasks are never blocked.
• Writes img_status / img_result to SessionBus; MarkWorker monitors the
  bus via SessionBusWatcher and emits image_ready(path) pyqtSignal when
  img_status == "completed".

Model
─────
gemini-2.5-flash-image via client.models.generate_content() with
response_modalities=["TEXT", "IMAGE"] (Nano Banana; generate_images is
Imagen-only and does not support this model). Images are saved to a temp
directory and the file path is written to the SessionBus.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from google import genai
from google.genai import types as gtypes

from ...core.config import GEMINI_ENV
from ...shared.session_bus import SessionBus

logger = logging.getLogger(__name__)

IMAGE_MODEL   = "gemini-2.5-flash-image"  # Nano Banana; use generate_content, not generate_images
OUTPUT_DIR    = os.path.join(os.path.expanduser("~"), "arc_images")


# ── Public entry point ────────────────────────────────────────────────────────

async def run_image_generation_background(
    bus: SessionBus,
    trigger_ev: asyncio.Event,
    prompt_ref: list,   # mutable single-element list: prompt_ref[0] = prompt string
):
    """
    Background coroutine — runs inside Mark's asyncio.gather().

    Waits for trigger_ev (set by trigger_image_generation FunctionTool via
    loop.call_soon_threadsafe), then generates an image in a thread and
    writes the result path to SessionBus.

    Cancelled cleanly when Mark's session ends (via asyncio Task.cancel()).
    """
    logger.info("[ImageGen] Waiting for trigger…")

    try:
        await trigger_ev.wait()
    except asyncio.CancelledError:
        logger.info("[ImageGen] Cancelled before trigger")
        return

    prompt = prompt_ref[0]
    logger.info("[ImageGen] Triggered with prompt: %s", prompt[:80])
    bus.write_img_status("generating")

    try:
        # All blocking I/O runs in a thread so Mark's loop stays free ✓
        path = await asyncio.to_thread(_blocking_imagen_call, prompt)
        bus.write_img_status("completed", result=path)
        logger.info("[ImageGen] Saved to: %s", path)

    except asyncio.CancelledError:
        bus.write_img_status("failed")
        logger.info("[ImageGen] Cancelled during generation")
        raise  # re-raise for asyncio task lifecycle

    except Exception as exc:
        bus.write_img_status("failed")
        logger.error("[ImageGen] Failed: %s", exc)


# ── Blocking worker (runs in asyncio.to_thread) ────────────────────────────

def _blocking_imagen_call(prompt: str) -> str:
    """
    Synchronous image generation via Gemini (Nano Banana) — safe to block (runs in a thread).

    Uses generate_content() with response_modalities IMAGE; saves to OUTPUT_DIR and returns path.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    os.environ.update(GEMINI_ENV)
    client = genai.Client()

    response = client.models.generate_content(
        model=IMAGE_MODEL,
        contents=prompt,
        config=gtypes.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
        ),
    )

    # Extract first image part (SDK may expose response.parts or response.candidates[0].content.parts)
    parts = getattr(response, "parts", None) or (
        response.candidates[0].content.parts if response.candidates else []
    )
    img_part = None
    for part in parts:
        if part.inline_data is not None:
            img_part = part
            break
    if img_part is None:
        raise RuntimeError("Model returned no image")

    timestamp = int(time.time())
    filename = f"arc_imagen_{timestamp}.png"
    path = os.path.join(OUTPUT_DIR, filename)

    # inline_data.data is raw bytes (or base64 depending on SDK); prefer saving via PIL if available
    if hasattr(img_part, "as_image") and callable(img_part.as_image):
        img_part.as_image().save(path)
    else:
        raw = getattr(img_part.inline_data, "data", None) or getattr(img_part.inline_data, "image_bytes", None)
        if isinstance(raw, str):
            import base64
            raw = base64.b64decode(raw)
        with open(path, "wb") as f:
            f.write(raw)

    return path
