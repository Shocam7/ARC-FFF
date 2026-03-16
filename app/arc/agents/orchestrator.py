"""
arc/agents/orchestrator.py
──────────────────────────
OrchestratorWorker — centralized Transcript-Watcher routing brain.

Handles two source types:
  • source_type="user"  — a human message; always routes to the best agent.
  • source_type="agent" — a completed agent turn; routes to peer ONLY if the
                          transcript shows the agent invited the peer to speak.
                          Silently drops the message if no handoff is detected,
                          so normal agent turns don't cause unwanted re-triggers.

Routing priority (user turns):
  1. Forced            — UI click / explicit override
  2. Redirect          — "not you", "other one", etc.
  3. LLM fallback      — Gemini 2.5 Flash Lite, last 2 turns only

Routing priority (agent turns / A2A):
  1. LLM A2A probe    — "did the agent invite a peer?" → agent_id or None

Rolling summariser: every SUMMARISE_EVERY raw user+agent turns, background
LLM call condenses that batch into 3–4 bullets via replace_range().
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import threading

from PyQt6.QtCore import QThread, pyqtSignal

from google import genai as gai
from google.genai import types as gtypes

from ..core.config import (
    AGENT_PERSONAS,
    ORCHESTRATOR_MODEL_GEMINI,
    GEMINI_ENV,
)
from ..core.shared_memory import SharedConversationLog

logger = logging.getLogger(__name__)

SUMMARISE_EVERY = 10


# ── Routing helpers ───────────────────────────────────────────────────────────

_REDIRECT_TO_OTHER = [
    "not you", "not this one", "other one", "the other", "other guy",
    "i was asking", "i meant", "i mean", "not him", "switch to",
    "talk to the other", "ask the other",
]




def _wants_other_agent(text: str) -> bool:
    lower = text.lower()
    return any(phrase in lower for phrase in _REDIRECT_TO_OTHER)


def _peer_of(agent_id: str, personas: list[dict]) -> str:
    for p in personas:
        if p["id"] != agent_id:
            return p["id"]
    return agent_id


# ── LLM routing ───────────────────────────────────────────────────────────────

def _llm_route_user(
    user_text: str,
    recent_2_turns: str,
    personas: list[dict],
    last_id: str,
    api_key: str,
    model: str,
) -> tuple[str, bool]:
    "Standard user→agent routing. Returns (agent_id, is_roundtable)."
    agents_desc = "\n".join(
        f'  id="{p["id"]}"  name="{p["name"]}"  field="{p["field"]}"'
        for p in personas
    )
    prompt = (
        "# Role: Panel Traffic Controller\n\n"
        "You are a silent moderator for an expert panel discussion. Your goal is to "
        "ensure every user message is handled by the most qualified agent.\n\n"
        "## Domain Experts:\n"
        f"{agents_desc}\n\n"
        f"## State:\n- Last active agent: {last_id}\n\n"
        "## Routing Logic:\n"
        "1. **Direct Address**: If the user names an agent (Nova, Lex, Mark), route to them IMMEDIATELY.\n"
        "2. **Task Parity**: All agents can use Google Search, Computer Use, and Image Gen. Do NOT route to Mark solely based on these tasks; route based on the topic of discussion.\n"
        "3. **Expertise Match**: If no name is mentioned, route to the agent whose field best aligns with the query.\n"
        "4. **User Correction**: If the user says 'not you' or 'other one', route to the peer of the last active agent.\n"
        "5. **Roundtable Detection**: If the query is a general question, philosophical inquiry, or a request for 'everyone's opinion' / 'what do you all think', mark 'roundtable' as true.\n\n"
        f"## Input:\n- Last 2 turns: {recent_2_turns or '(none)'}\n- User query: {user_text}\n\n"
        "## Output (JSON Only):\n"
        '{"agent_id": "<id>", "roundtable": true|false, "reason": "<logic>"}'
    )
    return _call_llm(prompt, last_id, personas, api_key, model)


def _llm_route_a2a(
    agent_transcript: str,
    from_id: str,
    personas: list[dict],
    api_key: str,
    model: str,
) -> str | None:
    """
    A2A handoff probe — tail-only analysis.

    Only the last 200 characters of the transcript are examined.
    A handoff only makes sense when the agent ENDS their turn addressing
    a peer — if the peer's name was mentioned at the start or middle and
    the agent kept talking, the floor was never actually yielded.

    Returns peer agent_id if the tail shows a genuine floor-yield, else None.
    """
    # Examine only the closing words of the turn
    tail = agent_transcript[-200:].strip()

    from_name = next((p["name"] for p in personas if p["id"] == from_id), from_id)
    peers = [p for p in personas if p["id"] != from_id]
    peers_desc = "\n".join(
        f'  id="{p["id"]}"  name="{p["name"]}"'
        for p in peers
    )
    prompt = (
        "# Role: Floor Manager\n\n"
        "Analyze the closing of an agent's turn to detect a handoff.\n\n"
        f"Current Speaker: {from_name}\n"
        "Peer Directory:\n"
        f"{peers_desc}\n\n"
        "## Transcript Tail (Last 200 chars):\n"
        f'"""\n{tail}\n"""\n\n'
        "## Decision Criteria:\n"
        "1. **Floor Yield**: Did the speaker END by asking a peer a direct question? (e.g., 'Lex, what do you think?')\n"
        "2. **Explicit Invite**: Did they name a peer and yield? (e.g., 'I'll let Nova handle the technical details.')\n"
        "3. **Exclusion**: Mentions earlier in the turn do NOT count. Questions to the 'User' do NOT count.\n\n"
        "## Output (JSON Only):\n"
        '{"handoff": true, "agent_id": "<peer_id>"} OR {"handoff": false}'
    )
    try:
        raw = _raw_llm_call(prompt, api_key, max_tokens=60, model=model)
        dec = _parse_json(raw)
        if dec.get("handoff"):
            aid = dec.get("agent_id", "")
            valid = {p["id"] for p in peers}
            return aid if aid in valid else None
        return None
    except _RateLimitError:
        raise   # let the worker method handle UI notification + sleep
    except Exception as exc:
        logger.warning("A2A LLM probe error: %s", exc)
        return None


def _call_llm(
    prompt: str,
    fallback_id: str,
    personas: list[dict],
    api_key: str,
    model: str,
) -> tuple[str, bool]:
    try:
        raw = _raw_llm_call(prompt, api_key, max_tokens=80, model=model)
        dec = _parse_json(raw)
        aid = dec.get("agent_id", fallback_id)
        rt  = bool(dec.get("roundtable", False))
        valid_ids = {p["id"] for p in personas}
        return (aid if aid in valid_ids else fallback_id), rt
    except _RateLimitError:
        raise
    except Exception as exc:
        logger.warning("Orchestrator LLM error: %s", exc)
        return fallback_id, False


class _RateLimitError(Exception):
    """Raised by _raw_llm_call when the API returns 429. Carries retry_after seconds."""
    def __init__(self, retry_after: float, original: Exception):
        super().__init__(str(original))
        self.retry_after = retry_after


def _parse_retry_delay(exc: Exception) -> float:
    """Extract the retryDelay seconds from a 429 exception message, default 60s."""
    import re as _re
    m = _re.search(r'retry[_ ]?(?:in|delay)[^\d]*(\d+(?:\.\d+)?)', str(exc), _re.IGNORECASE)
    if m:
        return float(m.group(1)) + 2.0   # +2 s safety margin
    return 60.0


def _raw_llm_call(
    prompt: str,
    api_key: str,
    max_tokens: int,
    model: str,
) -> str:
    os.environ.update(GEMINI_ENV)
    client = gai.Client(api_key=api_key)

    try:
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=gtypes.GenerateContentConfig(temperature=0.0, max_output_tokens=max_tokens),
        )
        return resp.text or ""
    except Exception as exc:
        if "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc):
            raise _RateLimitError(_parse_retry_delay(exc), exc) from exc
        raise


# ── Rolling summariser ────────────────────────────────────────────────────────

def _run_summariser(
    log: SharedConversationLog,
    start_idx: int,
    end_idx: int,
    turns_text: str,
    api_key: str,
    model: str,
):
    prompt = (
        "# Role: Technical Scribe\n\n"
        "Distill the following conversation batch into 3-4 professional bullets.\n\n"
        "## Objectives:\n"
        "- **Context Retention**: Preserve names, technical decisions, and unresolved tasks.\n"
        "- **Brevity**: Use punchy, 8th-grade vocabulary. No preamble.\n"
        "- **Symbolism**: Use '•' for bullets.\n\n"
        f"## Batch Content:\n{turns_text}"
    )
    try:
        raw     = _raw_llm_call(prompt, api_key, max_tokens=200, model=model)
        summary = raw.strip()
        if summary:
            log.replace_range(start_idx, end_idx, summary)
            logger.debug("Summariser: compressed turns %d–%d", start_idx, end_idx)
    except _RateLimitError as exc:
        logger.warning("Summariser rate-limited, retry in %.0fs", exc.retry_after)
        # Summariser runs in a daemon thread — just skip this batch silently.
        # The UI is notified via the worker's error_occurred signal instead.
    except Exception as exc:
        logger.warning("Rolling summariser error: %s", exc)


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if "```" in raw:
        for part in raw.split("```"):
            p = part.strip().lstrip("json").strip()
            if p.startswith("{"):
                raw = p; break
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        s, e = raw.find("{"), raw.rfind("}") + 1
        if s != -1 and e > s:
            try:
                return json.loads(raw[s:e])
            except Exception:
                pass
    return {}


# ── QThread ───────────────────────────────────────────────────────────────────

class OrchestratorWorker(QThread):
    """
    Signals
    ───────
        route_to(agent_id, enriched_message)
        routing_note(str)
        error_occurred(str)
    """

    route_to       = pyqtSignal(str, str)
    routing_note   = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        personas: list[dict],
        shared_log: SharedConversationLog,
    ):
        super().__init__()
        self._personas    = personas
        self._log         = shared_log
        self._q: queue.Queue = queue.Queue()
        self._last_summarised_at: int = 0

        self._model = ORCHESTRATOR_MODEL_GEMINI
        self._id_to_p = {p["id"]: p for p in personas}
        self._api_key = GEMINI_ENV.get("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", ""))
        self._last_id = personas[0]["id"] if personas else ""
        self.setObjectName("Orchestrator")

        # Roundtable state
        self._roundtable_sequence: list[str] = []
        self._roundtable_idx: int = -1
        self._roundtable_original_query: str = ""

    # ── Public API ────────────────────────────────────────────────────────────

    def route(
        self,
        text: str,
        source_type: str = "user",
        force_agent_id: str | None = None,
        from_agent_id: str | None = None,
    ):
        """
        Enqueue a routing request.

        source_type : "user"  — human message; always routes.
                      "agent" — completed agent turn; only routes if a peer
                                was invited to speak (A2A handoff detected).
        from_agent_id : agent_id of the speaker (required when source_type="agent").
        """
        self._q.put({
            "type":     "route",
            "text":     text,
            "source":   source_type,
            "force":    force_agent_id,
            "from_id":  from_agent_id,
        })

    def set_last_active(self, agent_id: str):
        self._last_id = agent_id

    def add_persona(self, persona: dict):
        self._q.put({
            "type": "add_persona",
            "persona": persona
        })

    def remove_persona(self, agent_id: str):
        self._q.put({
            "type": "remove_persona",
            "agent_id": agent_id
        })

    def shutdown(self):
        logger.info("[Orchestrator] Shutdown requested")
        self._q.put({"type": "stop"})

    # ── Thread loop ───────────────────────────────────────────────────────────

    def run(self):
        while True:
            try:
                msg = self._q.get(timeout=1.0)
            except queue.Empty:
                continue
            if msg["type"] == "stop":
                break
            if msg["type"] == "add_persona":
                p = msg["persona"]
                self._personas.append(p)
                self._id_to_p[p["id"]] = p
            if msg["type"] == "remove_persona":
                aid = msg["agent_id"]
                self._personas = [p for p in self._personas if p["id"] != aid]
                self._id_to_p.pop(aid, None)
            if msg["type"] == "route":
                if msg["source"] == "agent":
                    self._do_route_a2a(msg["text"], msg.get("from_id"))
                else:
                    self._do_route_user(msg["text"], msg.get("force"))

    # ── User → Agent routing ──────────────────────────────────────────────────

    def _do_route_user(self, user_text: str, force_id: str | None):
        # Snapshot history BEFORE appending the current user turn.
        # If we append first then call _enrich_user(), the current message
        # ends up in both the [PANEL HISTORY] block AND the trailing
        # "User's current message:" line.  Vertex AI Live sees the duplicate
        # as an already-processed turn and returns an empty response for every
        # question after the first.  Gemini masks this via session_resumption;
        # Vertex has no equivalent safety net.
        history_snapshot = self._log.as_text(max_tokens=800, window=40)

        # Log the user turn (after snapshot so it is absent from this turn's history)
        self._log.append("user", "", user_text)
        self._maybe_summarise()

        # 1. Forced
        if force_id and force_id in self._id_to_p:
            self._emit(force_id, user_text, "forced", history_snapshot)
            return

        # 2. Explicit name address (heuristic check before LLM)
        lower_input = user_text.lower()
        for aid, p in self._id_to_p.items():
            name = p["name"].lower()
            # Catch "Hey Nova", "Nova,", "Nova can you", etc.
            if re.search(rf"\b{re.escape(name)}\b", lower_input):
                self._emit(aid, user_text, "name-match", history_snapshot)
                return

        # 3. Explicit redirect
        if _wants_other_agent(user_text):
            peer = _peer_of(self._last_id, self._personas)
            self._emit(peer, user_text, "redirected", history_snapshot)
            return

        # 4. LLM fallback (routing + roundtable detection)
        recent_2 = self._log.as_text(max_tokens=200, window=2)
        try:
            agent_id, is_roundtable = _llm_route_user(
                user_text, recent_2, self._personas,
                self._last_id, self._api_key,
                self._model,
            )
        except _RateLimitError as exc:
            self._emit_rate_limit(exc)
            agent_id, is_roundtable = self._last_id, False

        if is_roundtable:
            import random
            all_ids = [p["id"] for p in self._personas]
            random.shuffle(all_ids)
            self._roundtable_sequence = all_ids
            self._roundtable_idx = 0
            self._roundtable_original_query = user_text
            agent_id = self._roundtable_sequence[0]
            self._emit(agent_id, user_text, "roundtable-start", history_snapshot)
        else:
            self._roundtable_idx = -1 # Clear any old state
            self._emit(agent_id, user_text, "llm", history_snapshot)

    # ── Agent → Agent (A2A) handoff routing ───────────────────────────────────

    def _do_route_a2a(self, agent_transcript: str, from_id: str | None):
        """
        Called when an agent's turn completes.  Only emits route_to if a
        genuine handoff invitation is detected; otherwise returns silently.
        """
        if not from_id or from_id not in self._id_to_p:
            return

        # 1. Check if we are in a Roundtable
        if self._roundtable_idx != -1:
            self._roundtable_idx += 1
            if self._roundtable_idx < len(self._roundtable_sequence):
                next_id = self._roundtable_sequence[self._roundtable_idx]
                history_snap = self._log.as_text(max_tokens=800, window=40)
                # For roundtable participants, we use a specialized prompt
                enriched = self._enrich_roundtable(self._roundtable_original_query, history_snap)
                self.route_to.emit(next_id, enriched)
                self._last_id = next_id
                name = self._id_to_p[next_id]["name"]
                self.routing_note.emit(f"→ {name}  [roundtable-seq]")
            else:
                self._roundtable_idx = -1 # Roundtable completed
                self.routing_note.emit("Roundtable concluded.")
            return

        # 2. Otherwise, standard A2A probe
        try:
            peer_id = _llm_route_a2a(
                agent_transcript, from_id, self._personas,
                self._api_key, self._model,
            )
        except _RateLimitError as exc:
            self._emit_rate_limit(exc)
            return

        if peer_id:
            self._emit_a2a(from_id, peer_id, agent_transcript, "a2a-llm")

    # ── Emit helpers ──────────────────────────────────────────────────────────

    def _emit(self, agent_id: str, user_text: str, method: str, history_snapshot: str = ""):
        """User-turn emit: enriched with pre-snapshotted panel history."""
        enriched = self._enrich_user(user_text, history_snapshot)
        self.route_to.emit(agent_id, enriched)
        self._last_id = agent_id
        name = self._id_to_p[agent_id]["name"]
        self.routing_note.emit(f"→ {name}  [{method}]")

    def _emit_a2a(self, from_id: str, to_id: str, transcript: str, method: str):
        """A2A emit: brief transition context for the receiving agent."""
        enriched = self._enrich_a2a(from_id, to_id)
        self.route_to.emit(to_id, enriched)
        self._last_id = to_id
        from_name = self._id_to_p[from_id]["name"]
        to_name   = self._id_to_p[to_id]["name"]
        self.routing_note.emit(f"↔ {from_name} → {to_name}  [{method}]")

    def _emit_rate_limit(self, exc: _RateLimitError):
        """Emit a concise 429 notice to the UI and block the routing thread
        for the retry delay so we don't immediately hit the quota again."""
        import time
        delay = exc.retry_after
        msg   = f"429 RESOURCE_EXHAUSTED — router paused {delay:.0f}s"
        logger.warning(msg)
        self.error_occurred.emit(msg)
        time.sleep(delay)

    def _enrich_user(self, user_text: str, history_snapshot: str = "") -> str:
        """Build a context-enriched prompt for a user-turn message.

        The current message is placed FIRST as the primary directive.
        History follows as labelled background context — this prevents the LLM
        from treating earlier turns as the primary thing to respond to.
        """
        history = history_snapshot or self._log.as_text(max_tokens=800, window=40)
        if not history:
            return user_text
        return (
            "# PRIMARY DIRECTIVE (Respond to this immediately):\n"
            f"> {user_text}\n\n"
            "## Background Context (Reference Only):\n"
            f"{history}\n\n"
            "--- End of Context ---"
        )

    def _enrich_a2a(self, from_id: str, to_id: str) -> str:
        """
        Build a handoff context prompt for the receiving agent.

        Uses last 3 turns for context. The most recent statement is explicitly
        quoted as the DIRECT response target so the agent can't mistake past
        turns as its primary prompt.
        """
        recent    = self._log.last_n(3)
        from_name = self._id_to_p[from_id]["name"]
        to_name   = self._id_to_p[to_id]["name"]

        # The last record is what the agent must directly respond to
        last_entry    = recent[-1] if recent else {}
        last_speaker  = last_entry.get("agent", from_name) if last_entry.get("role") == "agent" else "the user"
        last_statement = last_entry.get("text", "").strip()

        history = "\n".join(
            f"[{e.get('agent', 'User') if e.get('role') == 'agent' else 'User'}]: "
            f"{e.get('text', '')}"
            for e in recent[:-1]  # all but the last (quoted separately)
        )

        prompt = (
            "# HANDOFF ALERT (Direct Action Required):\n"
            f"{last_speaker} yields to you with: \"{last_statement}\"\n\n"
            "## Recent Exchange (For Continuity):\n"
            f"{history}\n\n"
            "## Behavioral Rule:\n"
            "Respond naturally as if you were already part of the flow. "
            "Do NOT mention the handoff or say 'I'll take it from here'."
        )
        return prompt

    def _enrich_roundtable(self, original_query: str, history: str) -> str:
        """Enrichment for roundtable participants after the first speaker."""
        return (
            "# ROUNDTABLE PARTICIPATION (Direct Action Required):\n"
            f"The user asked: \"{original_query}\"\n\n"
            "Several colleagues have already shared their thoughts. It is your turn to "
            "provide your unique perspective while referencing previous points where appropriate.\n\n"
            "## Background Context:\n"
            f"{history}\n\n"
            "## Behavioral Rule:\n"
            "Keep it concise. Do NOT acknowledge the roundtable structure. "
            "Just contribute your expertise to the flow."
        )

    # ── Rolling summariser ────────────────────────────────────────────────────

    def _maybe_summarise(self):
        total     = self._log.turn_count()
        new_turns = total - self._last_summarised_at
        if new_turns < SUMMARISE_EVERY:
            return
        all_recs     = self._log.read_all()
        start_idx    = self._last_summarised_at
        end_idx      = start_idx + SUMMARISE_EVERY
        to_summarise = all_recs[start_idx:end_idx]
        lines = []
        for r in to_summarise:
            role  = r.get("role", "?")
            agent = r.get("agent", "")
            text  = r.get("text", "")
            prefix = f"[{agent}]" if role == "agent" else "[User]"
            lines.append(f"{prefix}: {text}")
        self._last_summarised_at = end_idx
        threading.Thread(
            target=_run_summariser,
            args=(self._log, start_idx, end_idx, "\n".join(lines),
                  self._api_key, self._model),
            daemon=True,
            name=f"summariser-{start_idx}-{end_idx}",
        ).start()