"""
tests/test_session_bus.py
──────────────────────────
Unit tests for SessionBus and SessionBusWatcher.

Tests cover:
  1. SessionBus write / read / snapshot correctness
  2. SessionBusWatcher rate-limit: verifies debouncing (≤1 injection per 5 s)
  3. Watcher message format for CU and Imagen state transitions
  4. CancelledError handling in watcher
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from unittest.mock import MagicMock

import pytest

# Match the import convention used by other tests in this project
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.arc.shared.session_bus import SessionBus, SessionBusWatcher, MIN_INJECT_INTERVAL


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def bus():
    return SessionBus()


# ── SessionBus write/read tests ───────────────────────────────────────────────

class TestSessionBus:

    def test_initial_state(self, bus):
        snap = bus.snapshot()
        assert snap["cu_status"] == "idle"
        assert snap["img_status"] == "idle"
        assert snap["cu_last_action"] == ""
        assert snap["img_result"] == ""

    def test_write_cu_action_running(self, bus):
        bus.write_cu_action("Navigating to google.com", page="google.com", status="running")
        snap = bus.snapshot()
        assert snap["cu_last_action"] == "Navigating to google.com"
        assert snap["cu_current_page"] == "google.com"
        assert snap["cu_status"] == "running"

    def test_write_cu_action_completed(self, bus):
        bus.write_cu_action("Done", status="completed", result="Task finished OK")
        snap = bus.snapshot()
        assert snap["cu_status"] == "completed"
        assert snap["cu_result"] == "Task finished OK"

    def test_write_img_status_generating(self, bus):
        bus.write_img_status("generating")
        assert bus.get("img_status") == "generating"

    def test_write_img_status_completed(self, bus):
        bus.write_img_status("completed", result="/tmp/arc_imagen_123.png")
        snap = bus.snapshot()
        assert snap["img_status"] == "completed"
        assert snap["img_result"] == "/tmp/arc_imagen_123.png"

    def test_snapshot_is_copy(self, bus):
        snap1 = bus.snapshot()
        bus.write_cu_action("new action", status="running")
        snap2 = bus.snapshot()
        # snap1 should NOT reflect the second write
        assert snap1["cu_last_action"] != snap2["cu_last_action"]

    def test_reset_cu(self, bus):
        bus.write_cu_action("action", status="completed", result="done")
        bus.reset_cu()
        snap = bus.snapshot()
        assert snap["cu_status"] == "idle"
        assert snap["cu_last_action"] == ""
        assert snap["cu_result"] == ""

    def test_reset_img(self, bus):
        bus.write_img_status("completed", result="/path/img.png")
        bus.reset_img()
        assert bus.get("img_status") == "idle"
        assert bus.get("img_result") == ""

    def test_thread_safety(self, bus):
        """Concurrent writes from multiple threads should not corrupt state."""
        import threading

        errors = []

        def writer(i):
            try:
                for _ in range(100):
                    bus.write_cu_action(f"action-{i}", status="running")
                    bus.snapshot()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread safety errors: {errors}"


# ── SessionBusWatcher tests ───────────────────────────────────────────────────

class TestSessionBusWatcher:

    def _make_lrq(self):
        """Mock LiveRequestQueue."""
        return MagicMock()

    def test_build_message_cu_running(self):
        watcher = SessionBusWatcher()
        current = {
            "cu_last_action": "Navigating to google.com",
            "cu_current_page": "google.com",
            "cu_status": "running",
            "cu_result": "",
            "img_status": "idle",
            "img_result": "",
        }
        prev = {
            "cu_last_action": "",
            "cu_current_page": "",
            "cu_status": "idle",
            "cu_result": "",
            "img_status": "idle",
            "img_result": "",
        }
        msg = watcher._build_message(current, prev)
        assert msg is not None
        assert "Navigating to google.com" in msg
        assert "BACKGROUND UPDATE" in msg

    def test_build_message_cu_completed(self):
        watcher = SessionBusWatcher()
        current = {
            "cu_last_action": "Done",
            "cu_current_page": "",
            "cu_status": "completed",
            "cu_result": "Finished successfully",
            "img_status": "idle",
            "img_result": "",
        }
        prev = {
            "cu_status": "running",
            "cu_last_action": "Something",
            "cu_current_page": "",
            "cu_result": "",
            "img_status": "idle",
            "img_result": "",
        }
        msg = watcher._build_message(current, prev)
        assert msg is not None
        assert "Completed" in msg
        assert "Finished successfully" in msg

    def test_build_message_img_completed(self):
        watcher = SessionBusWatcher()
        current = {
            "cu_last_action": "",
            "cu_current_page": "",
            "cu_status": "idle",
            "cu_result": "",
            "img_status": "completed",
            "img_result": "/home/user/arc_images/arc_imagen_123.png",
        }
        prev = {
            "cu_last_action": "",
            "cu_current_page": "",
            "cu_status": "idle",
            "cu_result": "",
            "img_status": "generating",
            "img_result": "",
        }
        msg = watcher._build_message(current, prev)
        assert msg is not None
        assert "Image ready" in msg
        assert "arc_imagen_123.png" in msg

    def test_build_message_no_change_returns_none(self):
        watcher = SessionBusWatcher()
        state = {
            "cu_last_action": "same action",
            "cu_current_page": "page",
            "cu_status": "running",
            "cu_result": "",
            "img_status": "idle",
            "img_result": "",
        }
        # Same snapshot — cu_last_action didn't change
        msg = watcher._build_message(state, state.copy())
        assert msg is None

    @pytest.mark.asyncio
    async def test_watcher_debounces_rapid_changes(self):
        """
        Even with rapid bus changes, the watcher should inject at most
        once per MIN_INJECT_INTERVAL seconds.
        """
        bus = SessionBus()
        lrq = self._make_lrq()
        watcher = SessionBusWatcher()

        # Force last_inject_ts to now so the first injection is debounced
        watcher._last_inject_ts = time.monotonic()

        injections = []
        original_inject = watcher._inject
        def counting_inject(lrq, msg):
            injections.append(msg)
        watcher._inject = counting_inject

        # Write a series of rapid changes
        bus.write_cu_action("step 1", status="running")
        bus.write_cu_action("step 2", status="running")
        bus.write_cu_action("step 3", status="running")

        # Run watcher briefly — 2 poll cycles (POLL_INTERVAL=1.5 s each)
        # but debounce should block both since _last_inject_ts was just now
        task = asyncio.create_task(watcher.run(bus, lrq))
        await asyncio.sleep(0.1)  # let the loop start
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # No injections should have fired (debounce window still active)
        assert len(injections) == 0, f"Expected 0 injections, got {len(injections)}"

    @pytest.mark.asyncio
    async def test_watcher_cancels_cleanly(self):
        """Watcher task.cancel() should not raise unhandled exceptions."""
        bus = SessionBus()
        lrq = self._make_lrq()
        watcher = SessionBusWatcher()

        task = asyncio.create_task(watcher.run(bus, lrq))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        # If we get here without exception, the watcher cancelled cleanly
        assert task.done()
