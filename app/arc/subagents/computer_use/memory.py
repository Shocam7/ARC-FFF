"""
arc/subagents/computer_use/memory.py
───────────────────────────────────
A simple persistent memory for the Computer Use subagent.
Stores key-value pairs in a JSON file.
"""

import json
import os
import logging

logger = logging.getLogger(__name__)

MEMORY_FILE = os.path.join(os.path.dirname(__file__), "agent_memory.json")

def memorize(key: str, value: str) -> bool:
    """Store a piece of information in persistent memory."""
    try:
        memory = _load_memory()
        memory[key] = value
        _save_memory(memory)
        return True
    except Exception as e:
        logger.error(f"Failed to memorize {key}: {e}")
        return False

def recall(key: str) -> str | None:
    """Retrieve a piece of information from persistent memory."""
    try:
        memory = _load_memory()
        return memory.get(key)
    except Exception as e:
        logger.error(f"Failed to recall {key}: {e}")
        return None

def list_memory() -> dict:
    """List all stored memory items."""
    return _load_memory()

def _load_memory() -> dict:
    if not os.path.exists(MEMORY_FILE):
        return {}
    try:
        with open(MEMORY_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_memory(memory: dict):
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory, f, indent=2)
