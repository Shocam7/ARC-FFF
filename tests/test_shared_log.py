import sys
import os
import pytest
import json
import threading
from pathlib import Path

# Add app to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.arc.core.shared_memory import SharedConversationLog, _sanitize

def test_sanitize():
    assert _sanitize("Hello—World") == "Hello - World"
    assert _sanitize("Curly 'quotes' and \"double\"") == "Curly 'quotes' and \"double\""
    assert _sanitize("Ellipsis...") == "Ellipsis..."
    # Test accented chars (NFKD normalization)
    assert _sanitize("éàü") == "eau"

def test_append_and_read_all():
    log = SharedConversationLog()
    log.clear()
    
    log.append("user", "", "Hello panel")
    log.append("agent", "scientist", "Hello user")
    
    recs = log.read_all()
    assert len(recs) == 2
    assert recs[0]["role"] == "user"
    assert recs[0]["text"] == "Hello panel"
    assert recs[1]["agent"] == "scientist"
    assert recs[1]["text"] == "Hello user"
    
    log.clear()

def test_last_n():
    log = SharedConversationLog()
    log.clear()
    
    for i in range(10):
        log.append("agent", f"agent_{i}", f"message {i}")
        
    last_3 = log.last_n(3)
    assert len(last_3) == 3
    assert last_3[0]["agent"] == "agent_7"
    assert last_3[2]["agent"] == "agent_9"
    
    last_20 = log.last_n(20)
    assert len(last_20) == 10
    
    log.clear()

def test_turn_count():
    log = SharedConversationLog()
    log.clear()
    
    log.append("user", "", "One")
    log.append("summary", "", "A summary of many things")
    log.append("agent", "scientist", "Two")
    
    # Summary doesn't count towards turn_count
    assert log.turn_count() == 2
    
    log.clear()

def test_as_text_budgeting():
    log = SharedConversationLog()
    log.clear()
    
    log.append("user", "", "A" * 100) # ~22 tokens
    log.append("agent", "scientist", "B" * 100) # ~22 tokens
    
    # Budget of 30 tokens should only include the last message or a truncated version
    text = log.as_text(max_tokens=30)
    assert "scientist: BBB" in text
    # User message should be truncated (indicated by ellipsis)
    assert "…" in text or "User: AAA" not in text
    
    log.clear()

def test_thread_safety():
    log = SharedConversationLog()
    log.clear()
    
    def worker(id_str):
        for i in range(50):
            log.append("agent", id_str, f"message {i}")
            
    threads = []
    for i in range(5):
        t = threading.Thread(target=worker, args=(f"thread_{i}",))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    recs = log.read_all()
    assert len(recs) == 250
    assert log.turn_count() == 250
    
    log.clear()
