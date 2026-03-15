"""
voice_agent/agent.py
────────────────────
ARC Voice Agent — LiveKit ↔ Gemini Live API bridge.

The agent joins every ARC voice room as the host AI.  When a web guest
enters the room, the agent's pipeline:

  Browser mic  →  LiveKit Cloud  →  STT/VAD  →  Gemini Live API
  Browser speaker  ←  LiveKit Cloud  ←  TTS  ←  Gemini Live API

Run locally (dev mode — connects to LiveKit Cloud):
  python agent.py dev

Deploy on Railway / Fly.io:
  python agent.py start
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

# ── Load env ──────────────────────────────────────────────────────────────────
load_dotenv()          # loads voice_agent/.env when running locally

from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    RoomInputOptions,
    WorkerOptions,
    cli,
)
from livekit.plugins import google, silero

logger = logging.getLogger("arc.voice_agent")

# ── Persona ───────────────────────────────────────────────────────────────────
ARC_SYSTEM_PROMPT = """\
You are ARC — a collaborative panel of AI experts hosted in the ARC Meeting Room.
You can answer questions across science, history, technology, arts, and current events.
You have a warm, engaging personality. Keep responses concise and conversational.
You are speaking with a web guest who has joined the meeting room via voice chat.
When you don't know something, say so honestly.
"""


# ── Agent definition ──────────────────────────────────────────────────────────
class ARCAgent(Agent):
    def __init__(self):
        super().__init__(
            instructions=ARC_SYSTEM_PROMPT,
        )

    async def on_enter(self):
        """Greet the participant when the agent first joins."""
        await self.session.say(
            "Welcome to the ARC meeting room! I'm your AI panel host. "
            "Feel free to ask me anything.",
            allow_interruptions=True,
        )


# ── Agent entrypoint ──────────────────────────────────────────────────────────
async def entrypoint(ctx: JobContext):
    """Called once per LiveKit room job."""
    logger.info("ARC voice agent starting in room: %s", ctx.room.name)

    await ctx.connect()

    session = AgentSession(
        vad=silero.VAD.load(),
        stt=google.STT(),
        llm=google.LLM(
            model="gemini-2.0-flash-live-001",   # Gemini Live — native audio model
        ),
        tts=google.TTS(),
    )

    await session.start(
        room=ctx.room,
        agent=ARCAgent(),
        room_input_options=RoomInputOptions(),
    )


# ── Worker entrypoint ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
        )
    )
