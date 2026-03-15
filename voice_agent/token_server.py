"""
voice_agent/token_server.py
───────────────────────────
Minimal token server. The Next.js frontend calls:

  GET /token?room=arc-room&identity=guest-abc123

and receives a short-lived LiveKit JWT that grants publish+subscribe
permissions in the requested room.

Run locally:
  uvicorn token_server:app --port 7890 --reload

Deploy on Railway:
  Set env: LIVEKIT_API_KEY, LIVEKIT_API_SECRET, (optionally) ALLOWED_ORIGIN
"""

import os
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from livekit.api import AccessToken, VideoGrants

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
LIVEKIT_API_KEY    = os.environ["LIVEKIT_API_KEY"]
LIVEKIT_API_SECRET = os.environ["LIVEKIT_API_SECRET"]

# CORS: allow the Vercel frontend origin.  Set ALLOWED_ORIGIN to your Vercel URL
# in production; default "*" is fine for local development.
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")

TOKEN_TTL_SECONDS = 3_600   # 1 hour

app = FastAPI(title="ARC Token Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN] if ALLOWED_ORIGIN != "*" else ["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/token")
async def get_token(
    room:     str = Query(default="arc-room",   description="LiveKit room name"),
    identity: str = Query(default="",           description="Participant identity"),
):
    """Return a short-lived LiveKit JWT for the requested room."""
    try:
        import traceback
        if not identity:
            identity = f"guest-{uuid.uuid4().hex[:8]}"

        grant = VideoGrants(
            room_join=True,
            room=room,
            can_publish=True,
            can_subscribe=True,
        )

        token = (
            AccessToken(api_key=LIVEKIT_API_KEY, api_secret=LIVEKIT_API_SECRET)
            .with_identity(identity)
            .with_name(identity)
            .with_grants(grant)
            .with_ttl(TOKEN_TTL_SECONDS)
            .to_jwt()
        )

        return JSONResponse({"token": token, "identity": identity})
    except Exception as e:
        return JSONResponse(
            {
                "error": str(e),
                "traceback": traceback.format_exc()
            },
            status_code=500
        )


@app.get("/health")
async def health():
    return {"status": "ok"}
