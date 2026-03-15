"""
arc/core/shared_memory.py
─────────────────────────
SharedConversationLog — mmap-backed, thread-safe conversation log.

Binary layout
─────────────
  [0:8]    uint64-LE  write cursor (byte offset into body)
  [8:]     UTF-8 NDJSON, one record per line

Record schema:
  {"role": "user"|"agent"|"summary", "agent": "<n>", "text": "<text>"}
  role="summary" records replace a batch of raw turns (rolling summariser).

Only finalised, clean text is stored — no thoughts, no event metadata.
"""

from __future__ import annotations

import json
import mmap
import struct
import threading


_HEADER         = 8
_BODY           = 4 * 1024 * 1024   # 4 MB
_TOTAL          = _HEADER + _BODY
_CHARS_PER_TOKEN = 4.5               # conservative chars-per-token heuristic


class SharedConversationLog:
    """
    mmap-backed conversation log shared by all agent threads.

    Key methods
    ───────────
    append(role, agent, text)              — write one record
    replace_range(start, end, summary)     — swap N records for 1 summary
    as_text(max_tokens, window)            — sliding-budget formatted read
    last_n(n)                              — last n raw records
    turn_count()                           — non-summary record count
    """

    def __init__(self):
        self._mm   = mmap.mmap(-1, _TOTAL)
        self._lock = threading.Lock()
        self._mm[0:_HEADER] = b'\x00' * _HEADER

    # ── Cursor ────────────────────────────────────────────────────────────────

    def _cur(self) -> int:
        return struct.unpack_from('<Q', self._mm, 0)[0]

    def _set_cur(self, v: int):
        struct.pack_into('<Q', self._mm, 0, v)

    # ── Write ─────────────────────────────────────────────────────────────────

    def append(self, role: str, agent: str, text: str):
        """
        Append one record.  Only call with clean, finalised text —
        no thought fragments, no raw event JSON.
        """
        text = text.strip()
        if not text:
            return
        line    = json.dumps({"role": role, "agent": agent, "text": text},
                              ensure_ascii=False) + '\n'
        encoded = line.encode('utf-8')
        with self._lock:
            pos = self._cur()
            if pos + len(encoded) > _BODY:
                self._compact()
                pos = self._cur()
                if pos + len(encoded) > _BODY:
                    return
            dest = _HEADER + pos
            self._mm[dest : dest + len(encoded)] = encoded
            self._set_cur(pos + len(encoded))

    def replace_range(self, start_idx: int, end_idx: int, summary_text: str):
        """
        Atomically swap records [start_idx:end_idx] for one summary record.
        Called by the rolling summariser every SUMMARISE_EVERY turns.
        """
        with self._lock:
            all_recs = _parse_ndjson(bytes(self._mm[_HEADER : _HEADER + self._cur()]))
            if start_idx >= len(all_recs) or end_idx > len(all_recs):
                return
            kept = (
                all_recs[:start_idx]
                + [{"role": "summary", "agent": "", "text": summary_text}]
                + all_recs[end_idx:]
            )
            blob = b''.join(
                (json.dumps(r, ensure_ascii=False) + '\n').encode('utf-8')
                for r in kept
            )
            new_pos = min(len(blob), _BODY)
            self._mm[_HEADER : _HEADER + new_pos] = blob[:new_pos]
            self._set_cur(new_pos)

    # ── Read ──────────────────────────────────────────────────────────────────

    def read_all(self) -> list[dict]:
        pos = self._cur()
        return _parse_ndjson(bytes(self._mm[_HEADER : _HEADER + pos]))

    def last_n(self, n: int) -> list[dict]:
        return self.read_all()[-n:]

    def as_text(self, max_tokens: int = 800, window: int = 40) -> str:
        """
        Sliding token-budget read — walks newest-to-oldest, fills until
        max_tokens is exhausted.  window caps how far back we look.

        Summary records are prefixed with '📋 SUMMARY:' so agents understand
        they are compressed context, not verbatim turns.
        """
        records = self.read_all()[-window:]
        budget  = max_tokens
        lines: list[str] = []

        for rec in reversed(records):
            role  = rec.get("role", "?")
            agent = rec.get("agent", "")
            text  = rec.get("text", "")

            if role == "summary":
                line = f"📋 SUMMARY: {text}"
            elif role == "agent":
                line = f"[{agent}]: {text}"
            else:
                line = f"[User]: {text}"

            cost = len(line) / _CHARS_PER_TOKEN
            if cost > budget:
                chars_allowed = max(0, int(budget * _CHARS_PER_TOKEN))
                if chars_allowed > 20:
                    lines.insert(0, line[:chars_allowed] + "…")
                break
            budget -= cost
            lines.insert(0, line)
            if budget <= 0:
                break

        return "\n".join(lines)

    def turn_count(self) -> int:
        """Number of non-summary records (raw user + agent turns)."""
        return sum(1 for r in self.read_all() if r.get("role") != "summary")

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def clear(self):
        with self._lock:
            self._mm[0:_HEADER] = b'\x00' * _HEADER

    def close(self):
        try:
            self._mm.close()
        except Exception:
            pass

    def __len__(self) -> int:
        return len(self.read_all())

    def __bool__(self) -> bool:
        return self._cur() > 0

    # ── Internal ──────────────────────────────────────────────────────────────

    def _compact(self):
        pos   = self._cur()
        lines = [l for l in bytes(self._mm[_HEADER:_HEADER+pos]).split(b'\n') if l.strip()]
        keep  = lines[len(lines) // 3:]
        blob  = b'\n'.join(keep) + (b'\n' if keep else b'')
        new_pos = min(len(blob), _BODY)
        self._mm[_HEADER : _HEADER + new_pos] = blob[:new_pos]
        self._set_cur(new_pos)


def _parse_ndjson(data: bytes) -> list[dict]:
    result = []
    for line in data.decode('utf-8', errors='replace').splitlines():
        line = line.strip()
        if line:
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return result