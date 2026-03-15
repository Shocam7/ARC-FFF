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

import asyncio
import logging
import os

from dotenv import load_dotenv

# ── Load env ──────────────────────────────────────────────────────────────────
load_dotenv()          # loads voice_agent/.env when running locally

from livekit.agents import (
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    cli,
    llm,
)
from livekit.agents.voice_assistant import VoiceAssistant
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


# ── Agent entrypoint ──────────────────────────────────────────────────────────
async def entrypoint(ctx: JobContext):
    """Called once per LiveKit room job."""
    logger.info("ARC voice agent starting in room: %s", ctx.room.name)

    # Connect to the room, auto-subscribe to all tracks
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Initial greeting (sent as text-to-speech before the guest speaks)
    initial_ctx = llm.ChatContext().append(
        role="system",
        text=ARC_SYSTEM_PROMPT,
    )

    # Build the pipeline:
    #  silero VAD  →  Google STT  →  Gemini LLM  →  Google TTS
    assistant = VoiceAssistant(
        vad=silero.VAD.load(),
        stt=google.STT(),
        llm=google.LLM(
            model="gemini-2.0-flash-live-001",   # Gemini Live — native audio model
        ),
        tts=google.TTS(),
        chat_ctx=initial_ctx,
    )

    assistant.start(ctx.room)

    # Greet the first participant that joins
    await asyncio.sleep(1)
    await assistant.say(
        "Welcome to the ARC meeting room! I'm your AI panel host. "
        "Feel free to ask me anything.",
        allow_interruptions=True,
    )


# ── Worker entrypoint ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
        )
    )
