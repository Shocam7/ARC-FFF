import sys
import os
import pytest
from pathlib import Path

# Add app to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.arc.core.config import get_safety_settings

def test_get_safety_settings_off():
    settings = get_safety_settings("off")
    assert len(settings) == 4
    for s in settings:
        # HarmBlockThreshold.BLOCK_NONE is usually 4
        # We check the name or value depending on the environment
        assert "BLOCK_NONE" in str(s["threshold"])

def test_get_safety_settings_medium():
    settings = get_safety_settings("medium")
    for s in settings:
        assert "BLOCK_MEDIUM_AND_ABOVE" in str(s["threshold"])

def test_get_safety_settings_strict():
    settings = get_safety_settings("strict")
    for s in settings:
        assert "BLOCK_LOW_AND_ABOVE" in str(s["threshold"])

def test_get_safety_settings_default():
    # Invalid level should default to 'off'
    settings = get_safety_settings("unknown")
    for s in settings:
        assert "BLOCK_NONE" in str(s["threshold"])
