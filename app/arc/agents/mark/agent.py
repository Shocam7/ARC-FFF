"""
arc/agents/mark/agent.py
─────────────────────────
MarkWorker — LiveAgentWorker subclass for the Mark agent.

Mark extends LiveAgentWorker with three additions:
  1. Two ADK FunctionTools (trigger_computer_use, trigger_image_generation)
     that the LLM calls autonomously when the user requests those actions.
  2. Two async background tasks (Computer Use, Image Generation) that run
     concurrently with Mark's bidi upstream/downstream via asyncio.gather().
     Both are gated by asyncio.Event flags and wrapped in asyncio.create_task()
     so they can be cancelled cleanly on session end.
  3. A SessionBusWatcher that polls the shared SessionBus every 1.5 seconds
     and injects milestone updates into Mark's LiveRequestQueue (rate-limited
     to at most one injection per 5 seconds via MIN_INJECT_INTERVAL).

Concurrency diagram
───────────────────
  Mark's QThread asyncio loop
    └── asyncio.gather(
          _upstream()                        # user audio → Mark (VAD + bidi)
          _downstream(runner, cfg)           # Mark audio → user
          _cu_task   (create_task)           # Computer Use background
          _img_task  (create_task)           # Image Generation background
          SessionBusWatcher.run(bus, lrq)    # bus → lrq injector
        )

Thread-safety note
──────────────────
ADK calls FunctionTools synchronously from a worker thread (not the asyncio
loop). The trigger functions therefore use loop.call_soon_threadsafe() to
set asyncio.Event objects, not event.set() directly.

Image display
─────────────
MarkWorker emits image_ready(str) pyqtSignal with the image file path when
img_status transitions to "completed". SessionController connects this signal
to the UI layer.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid

from PyQt6.QtCore import pyqtSignal

from google.adk.agents import Agent
from google.adk.tools import google_search, FunctionTool
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from ..live_agent import LiveAgentWorker
from ...core.config import APP_NAME, GEMINI_ENV, SR_IN
from ...core.shared_memory import SharedConversationLog
from ...shared.session_bus import SessionBus, SessionBusWatcher
from ...subagents.computer_use.agent import run_computer_use_background
from ...subagents.image_generation.agent import run_image_generation_background
from .prompts import MARK_INSTRUCTION

logger = logging.getLogger(__name__)

MARK_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"


class MarkWorker(LiveAgentWorker):
    """
    Signals (in addition to LiveAgentWorker signals)
    ─────────────────────────────────────────────────
        image_ready(str)   absolute path to the generated image file
    """

    image_ready = pyqtSignal(str)

    def __init__(
        self,
        persona: dict,
        shared_log: SharedConversationLog,
        proactivity: bool = False,
        affective_dialog: bool = False,
        startup_delay: float = 0.0,
    ):
        super().__init__(
            persona=persona,
            shared_log=shared_log,
            proactivity=proactivity,
            affective_dialog=affective_dialog,
            startup_delay=startup_delay,
        )

        # Shared action bus — written by background tasks, read by watcher
        self._bus = SessionBus()

        # Mutable refs — FunctionTools write to these before setting their events
        self._cu_task_ref:    list[str] = [""]
        self._img_prompt_ref: list[str] = [""]

        # asyncio.Event gates — set via loop.call_soon_threadsafe from tool callbacks
        self._cu_trigger:  asyncio.Event | None = None
        self._img_trigger: asyncio.Event | None = None

        # asyncio.Task handles — stored for .cancel() on shutdown
        self._cu_bg_task:  asyncio.Task | None = None
        self._img_bg_task: asyncio.Task | None = None

        # Track last img_status so we emit image_ready exactly once
        self._last_img_status: str = "idle"

    # ── Shutdown override ─────────────────────────────────────────────────────

    def shutdown(self):
        """Cancel background tasks before the parent shutdown closes the queue."""
        if self._loop:
            if self._cu_bg_task and not self._cu_bg_task.done():
                self._loop.call_soon_threadsafe(self._cu_bg_task.cancel)
            if self._img_bg_task and not self._img_bg_task.done():
                self._loop.call_soon_threadsafe(self._img_bg_task.cancel)
        super().shutdown()

    # ── Asyncio main override ──────────────────────────────────────────────────

    async def _main(self):
        """Override _main to run background tasks alongside bidi streaming."""

        MAX_RETRIES = 6
        BASE_DELAY  = 2.0
        MAX_DELAY   = 30.0

        if self._startup_delay > 0:
            await asyncio.sleep(self._startup_delay)

        self._queue = asyncio.Queue()

        # ── Capture the running loop (before tools are defined)
        #    FunctionTools will use this for thread-safe event signalling.
        loop = asyncio.get_running_loop()

        # ── asyncio Events initialised here (inside the loop) ─────────────────
        self._cu_trigger  = asyncio.Event()
        self._img_trigger = asyncio.Event()

        # ── ADK FunctionTools ─────────────────────────────────────────────────
        # Closures capture loop, events, and mutable refs.
        # ADK calls these synchronously from a thread, so we use
        # loop.call_soon_threadsafe() to safely signal the asyncio loop.

        def trigger_computer_use(task: str) -> str:
            """
            Trigger the Computer Use background agent.
            Call this when the user asks you to interact with a computer,
            open apps, browse websites, fill forms, or automate any desktop task.
            """
            self._cu_task_ref[0] = task
            # Thread-safe: ADK runs tools in a worker thread ✓
            loop.call_soon_threadsafe(self._cu_trigger.set)
            logger.info("[Mark] Triggered Computer Use: %s", task[:80])
            return f"Computer Use task started: {task[:60]}"

        def trigger_image_generation(prompt: str) -> str:
            """
            Generate an image using the Imagen model.
            Call this when the user asks you to create, generate, or draw an image.
            """
            self._img_prompt_ref[0] = prompt
            # Thread-safe: ADK runs tools in a worker thread ✓
            loop.call_soon_threadsafe(self._img_trigger.set)
            logger.info("[Mark] Triggered Image Generation: %s", prompt[:80])
            return f"Image generation started for: {prompt[:60]}"

        # ── Apply env and build agent ──────────────────────────────────────────
        os.environ.update(GEMINI_ENV)

        _agent = Agent(
            name="arc_mark",
            model=MARK_MODEL,
            tools=[
                google_search,
                FunctionTool(trigger_computer_use),
                FunctionTool(trigger_image_generation),
            ],
            instruction=MARK_INSTRUCTION,        
        )

        svc    = InMemorySessionService()
        runner = Runner(app_name=APP_NAME, agent=_agent, session_service=svc)
        await svc.create_session(
            app_name=APP_NAME,
            user_id=self.user_id,
            session_id=self.session_id,
        )

        # ── RunConfig with context window compression ──────────────────────────
        cfg = RunConfig(
            streaming_mode=StreamingMode.BIDI,
            response_modalities=["AUDIO"],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            session_resumption=types.SessionResumptionConfig(),
            proactivity=types.ProactivityConfig(proactive_audio=True) if self.proactivity else None,
            enable_affective_dialog=self.affective_dialog or None,
            # Context window compression — keeps long Mark sessions alive ✓
            context_window_compression=types.ContextWindowCompressionConfig(
                trigger_tokens=32_000,
                sliding_window=types.SlidingWindow(
                    target_tokens=16_000,
                ),
            ),
        )

        attempt = 0
        while self._alive and attempt < MAX_RETRIES:
            self.status_changed.emit("connecting")

            try:
                from google.adk.agents.live_request_queue import LiveRequestQueue
                self._turns_in_current_session = 0
                self._session_ready = asyncio.Event()
                self._lrq = LiveRequestQueue()
                self._audio.start()
                self.status_changed.emit("connected")

                # ── Background tasks — wrapped in create_task for .cancel() ✓
                self._cu_bg_task  = asyncio.create_task(
                    run_computer_use_background(
                        self._bus,
                        self._cu_trigger,
                        self._cu_task_ref,
                    ),
                    name="mark-computer-use",
                )
                self._img_bg_task = asyncio.create_task(
                    run_image_generation_background(
                        self._bus,
                        self._img_trigger,
                        self._img_prompt_ref,
                    ),
                    name="mark-image-gen",
                )

                # ── Bus watcher — inject milestones into Mark's LRQ ───────────
                watcher = SessionBusWatcher()
                watcher_task = asyncio.create_task(
                    watcher.run(self._bus, self._lrq),
                    name="mark-bus-watcher",
                )

                # ── Image-ready monitor — polls bus for img completion ─────────
                monitor_task = asyncio.create_task(
                    self._monitor_image_completion(),
                    name="mark-img-monitor",
                )

                up_task   = asyncio.ensure_future(self._upstream())
                down_task = asyncio.ensure_future(self._downstream(runner, cfg))

                try:
                    done, pending = await asyncio.wait(
                        {up_task, down_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                finally:
                    # Cancel all background tasks on session end
                    for t in (
                        up_task, down_task,
                        self._cu_bg_task, self._img_bg_task,
                        watcher_task, monitor_task,
                    ):
                        if t and not t.done():
                            t.cancel()
                            try:
                                await t
                            except (asyncio.CancelledError, Exception):
                                pass

                for t in done:
                    exc = t.exception()
                    if exc is not None:
                        raise exc

                self._lrq.close()
                self._audio.stop()

                if not self._alive:
                    break

                # Seamless reconnect
                await asyncio.sleep(0.2)
                # Reset Events so background tasks can be re-triggered
                self._cu_trigger  = asyncio.Event()
                self._img_trigger = asyncio.Event()
                attempt = 0
                continue

            except asyncio.CancelledError:
                self._lrq.close()
                self._audio.stop()
                break

            except Exception as exc:
                err_str = str(exc)
                self._audio.clear()
                try:
                    self._lrq.close()
                except Exception:
                    pass
                self._audio.stop()

                if not self._alive:
                    break

                is_transient = any(kw in err_str for kw in (
                    "1011", "service is currently unavailable",
                    "503", "UNAVAILABLE", "connection closed",
                    "Connection closed",
                    "no close frame received or sent",
                    "ConnectionClosed", "ConnectionClosedError",
                    "ConnectionResetError", "connection reset",
                    "EOF occurred", "BrokenPipe",
                ))

                attempt += 1
                if is_transient and attempt < MAX_RETRIES:
                    from math import log2
                    delay = min(BASE_DELAY * (2 ** (attempt - 1)), MAX_DELAY)
                    logger.warning(
                        "[Mark] Transient error (attempt %d/%d), retrying in %.1fs: %s",
                        attempt, MAX_RETRIES, delay, err_str)
                    self.status_changed.emit("reconnecting")
                    await asyncio.sleep(delay)
                else:
                    self.error_occurred.emit(
                        f"[Mark] Connection failed after {attempt} attempts: {err_str}")
                    break

        if self._alive:
            self.status_changed.emit("disconnected")

    # ── Image completion monitor ───────────────────────────────────────────────

    async def _monitor_image_completion(self):
        """
        Lightweight async loop that watches for img_status == 'completed'
        on the SessionBus and emits the image_ready pyqtSignal.

        Runs inside Mark's asyncio loop. Cancelled automatically when
        the session ends (via the task cancel in _main).
        """
        while True:
            try:
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                return

            current_status = self._bus.get("img_status", "idle")
            if current_status == "completed" and self._last_img_status != "completed":
                path = self._bus.get("img_result", "")
                if path:
                    # Emit on Qt thread via signal — safe even from asyncio loop
                    # because PyQt6 signals are thread-safe at emit time.
                    self.image_ready.emit(path)
                    logger.info("[Mark] image_ready emitted: %s", path)

            self._last_img_status = current_status
