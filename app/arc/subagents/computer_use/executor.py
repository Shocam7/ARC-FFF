"""
arc/subagents/computer_use/executor.py
──────────────────────────────────────
Real screen capture and action execution for the computer-use agent.

Uses pyautogui for screenshots, clicks, typing, and key presses;
webbrowser for opening URLs. Coordinates from the model are treated as
pixels; if they are in a 0–1000 virtual space, the caller can scale
before passing (e.g. scale x,y by screen size / 1000).
"""

from __future__ import annotations

import io
import logging
import os
import platform
import subprocess
import webbrowser
from typing import Any
from urllib.parse import quote as _quote

import pyautogui

# Reduce pyautogui speed and add failsafe (move mouse to corner to abort)
pyautogui.PAUSE = 0.15
pyautogui.FAILSAFE = True

logger = logging.getLogger(__name__)

# Common screen size for normalizing virtual coords (e.g. 1000x1000 from model)
VIRTUAL_SIZE = (1000, 1000)


def get_screen_size() -> tuple[int, int]:
    """Return (width, height) of the primary screen in pixels."""
    w, h = pyautogui.size()
    return (w, h)


def _scale_coord(val: int | float, axis: int) -> int:
    """Scale from VIRTUAL_SIZE space to actual screen size."""
    screen = get_screen_size()
    if axis == 0:
        return int(round(val / VIRTUAL_SIZE[0] * screen[0]))
    return int(round(val / VIRTUAL_SIZE[1] * screen[1]))


def take_screenshot() -> bytes:
    """Capture the primary screen as PNG and return raw bytes."""
    im = pyautogui.screenshot()
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def execute_action(tool_name: str, tool_args: dict[str, Any]) -> dict[str, Any]:
    """
    Perform one computer-use action. Returns a result dict with at least
    'status' ('success' or 'error') and 'output' or 'error' message.
    When tool_args contains safety_decision with require_confirmation, the
    caller (agent) should not execute and must acknowledge in the response instead.
    """
    name = (tool_name or "").strip().lower()
    try:
        # ── Clicks (including click_at) ──
        if name in {"click", "left_click", "tap", "click_at"}:
            x = tool_args.get("x")
            y = tool_args.get("y")
            if x is None or y is None:
                return {"status": "error", "error": "click requires x and y"}
            x = _scale_coord(float(x), 0)
            y = _scale_coord(float(y), 1)
            pyautogui.click(x, y)
            return {"status": "success", "output": f"Clicked at ({x}, {y})"}

        if name == "right_click":
            x = tool_args.get("x")
            y = tool_args.get("y")
            if x is None or y is None:
                return {"status": "error", "error": "right_click requires x and y"}
            x = _scale_coord(float(x), 0)
            y = _scale_coord(float(y), 1)
            pyautogui.rightClick(x, y)
            return {"status": "success", "output": f"Right-clicked at ({x}, {y})"}

        if name == "double_click":
            x = tool_args.get("x")
            y = tool_args.get("y")
            if x is None or y is None:
                return {"status": "error", "error": "double_click requires x and y"}
            x = _scale_coord(float(x), 0)
            y = _scale_coord(float(y), 1)
            pyautogui.doubleClick(x, y)
            return {"status": "success", "output": f"Double-clicked at ({x}, {y})"}

        # ── Typing ──
        if name in {"type", "type_text", "fill", "set_text"}:
            text = tool_args.get("text") or tool_args.get("value") or tool_args.get("input", "")
            if isinstance(text, list):
                text = " ".join(str(t) for t in text)
            text = str(text)
            if not text:
                return {"status": "error", "error": "type/fill requires text or value"}
            pyautogui.write(text, interval=0.02)
            return {"status": "success", "output": f"Typed {len(text)} characters"}

        # ── Type text at coordinates (click then type, optional Enter) ──
        if name == "type_text_at":
            x_arg = tool_args.get("x")
            y_arg = tool_args.get("y")
            text = tool_args.get("text") or tool_args.get("value") or ""
            text = str(text)
            if x_arg is not None and y_arg is not None:
                x = _scale_coord(float(x_arg), 0)
                y = _scale_coord(float(y_arg), 1)
                pyautogui.click(x, y)
                import time
                time.sleep(0.5)  # Wait for focus/animation
                out = f"Typed at ({x}, {y})"
            else:
                out = "Typed"
            if text:
                pyautogui.write(text, interval=0.02)
            if tool_args.get("press_enter"):
                pyautogui.press("enter")
            return {"status": "success", "output": out}

        if name in {"key", "press", "press_key", "hotkey", "key_combination"}:
            key = tool_args.get("key") or tool_args.get("keys") or tool_args.get("value")
            if key is None:
                return {"status": "error", "error": "key/press requires key or keys"}
            keys = key if isinstance(key, list) else [key]
            keys = [str(k).strip() for k in keys]
            pyautogui.hotkey(*keys) if len(keys) > 1 else pyautogui.press(keys[0])
            return {"status": "success", "output": f"Pressed {keys}"}

        # ── Navigation (browser) ──
        if name in {"goto_url", "navigate", "open_url", "open_tab", "open_web_browser"}:
            url = tool_args.get("url") or tool_args.get("query") or tool_args.get("value", "")
            url = str(url).strip()
            if not url:
                # Open a blank or default page
                url = "about:blank"
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            webbrowser.open(url)
            return {"status": "success", "output": f"Opened {url}", "url": url}

        # ── Search (open search engine or run query) ──
        if name == "search":
            query = tool_args.get("query") or tool_args.get("q") or tool_args.get("value", "")
            query = str(query).strip()
            if query:
                url = "https://www.google.com/search?q=" + _quote(query)
                webbrowser.open(url)
                return {"status": "success", "output": f"Searched for {query}", "url": url}
            # No query: open Google home (model may then type in the box)
            url = "https://www.google.com"
            webbrowser.open(url)
            return {"status": "success", "output": "Opened Google", "url": url}

        # ── Scroll ──
        if name in {"scroll", "scroll_down", "scroll_up"}:
            dx = tool_args.get("delta_x") or tool_args.get("dx") or 0
            dy = tool_args.get("delta_y") or tool_args.get("dy") or tool_args.get("amount", 3)
            if name == "scroll_up":
                dy = -abs(int(dy)) if dy else -3
            else:
                dy = int(dy) if dy else 3
            pyautogui.scroll(dy)
            return {"status": "success", "output": f"Scrolled {dy}"}

        # ── Screenshot (no-op here; caller takes screenshot after every action) ──
        if name == "screenshot":
            return {"status": "success", "output": "Screenshot captured"}

        # ── Browser: print, save, share (keyboard shortcuts) ──
        if name in {"print_page", "print"}:
            pyautogui.hotkey("ctrl", "p")
            return {"status": "success", "output": "Opened print dialog"}

        if name in {"save_page", "save"}:
            pyautogui.hotkey("ctrl", "s")
            return {"status": "success", "output": "Opened save dialog"}

        if name == "share_page":
            # Windows share: Win+H; some browsers use Ctrl+Shift+S or menu
            if platform.system() == "Windows":
                pyautogui.hotkey("win", "h")
                return {"status": "success", "output": "Opened share panel"}
            pyautogui.hotkey("ctrl", "shift", "s")
            return {"status": "success", "output": "Triggered share"}

        # ── Download (open URL that triggers download; browser handles it) ──
        if name in {"download_file", "download"}:
            url = tool_args.get("url") or tool_args.get("link") or tool_args.get("value", "")
            url = str(url).strip()
            if not url:
                return {"status": "error", "error": "download_file requires url"}
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            webbrowser.open(url)
            return {"status": "success", "output": f"Opened download URL", "url": url}

        # ── Upload file (type file path at current focus — user/model should focus file input first) ──
        if name in {"upload_file", "select_file", "attach_file"}:
            path = tool_args.get("path") or tool_args.get("file_path") or tool_args.get("file") or tool_args.get("value", "")
            path = os.path.abspath(os.path.expanduser(str(path).strip()))
            if not os.path.exists(path):
                return {"status": "error", "error": f"File not found: {path}"}
            # Type path with quotes so spaces work in file dialogs / inputs
            pyautogui.write(f'"{path}"', interval=0.02)
            return {"status": "success", "output": f"Entered file path: {path}"}

        # ── Desktop window management ──
        if name in {"close_application", "close_window", "close_app"}:
            pyautogui.hotkey("alt", "f4")
            return {"status": "success", "output": "Sent Alt+F4 (close window)"}

        if name in {"minimize_window", "minimize", "minimize_app"}:
            if platform.system() == "Windows":
                pyautogui.hotkey("win", "down")
            else:
                pyautogui.hotkey("ctrl", "super", "down")  # fallback
            return {"status": "success", "output": "Minimized window"}

        if name in {"maximize_window", "maximize", "maximize_app"}:
            if platform.system() == "Windows":
                pyautogui.hotkey("win", "up")
            else:
                pyautogui.hotkey("ctrl", "super", "up")
            return {"status": "success", "output": "Maximized window"}

        if name in {"restore_window", "restore", "restore_app"}:
            # Win+Down restores from maximize or minimizes
            if platform.system() == "Windows":
                pyautogui.hotkey("win", "down")
            else:
                pyautogui.hotkey("ctrl", "super", "down")
            return {"status": "success", "output": "Restored window"}

        # ── Open desktop application ──
        if name in {"open_application", "open_app", "launch_app", "run_application"}:
            app = tool_args.get("application") or tool_args.get("app") or tool_args.get("name") or tool_args.get("path") or tool_args.get("value", "")
            app = str(app).strip()
            if not app:
                return {"status": "error", "error": "open_application requires application name or path"}
            is_path = os.path.exists(app) or os.path.exists(os.path.expanduser(app))
            if is_path:
                path = os.path.abspath(os.path.expanduser(app))
                if platform.system() == "Windows":
                    os.startfile(path)
                else:
                    subprocess.Popen([path], start_new_session=True)
                return {"status": "success", "output": f"Opened {path}"}
            # Try to launch by name (Windows: start; macOS: open; Linux: xdg-open)
            if platform.system() == "Windows":
                subprocess.Popen(["cmd", "/c", "start", "", app], shell=False)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", "-a", app], start_new_session=True)
            else:
                subprocess.Popen(["xdg-open", app], start_new_session=True)
            return {"status": "success", "output": f"Launched {app}"}

        # Unknown action — do not fail, report so model can adapt
        logger.warning("[ComputerUse] Unknown tool: %s with args %s", tool_name, tool_args)
        return {"status": "success", "output": f"Unknown action {tool_name} (no-op)"}

    except Exception as e:
        logger.exception("[ComputerUse] Action failed: %s %s", tool_name, tool_args)
        return {"status": "error", "error": str(e)}
