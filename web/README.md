# ARC Meeting Room — Web Client + Voice Guide

A mobile-friendly web client for the ARC multi-agent meeting room. Guests can:

- 💬 **Text Chat** — send messages to the agents over WebSocket (original feature)
- 🎙 **Voice Chat** — speak live with the AI panel over WebRTC via LiveKit Cloud + Gemini Live API *(new)*

Deployed on **Vercel** so you can join from any phone, tablet, or desktop.

---

## Architecture

```
Browser (Vercel)
  │── Text tab  ──WebSocket──────────────────► FastAPI ADK backend (your desktop)
  │
  └── Voice tab ──WebRTC──► LiveKit Cloud ──► voice_agent/agent.py ──► Gemini Live API
                                ▲
                     Token from voice_agent/token_server.py
                         (deployed on Railway)
```

---

## 1. Prerequisites

| Service | What you need | Where to sign up |
|---|---|---|
| **LiveKit Cloud** | Project URL, API Key, API Secret | [cloud.livekit.io](https://cloud.livekit.io) — free, no credit card |
| **Railway** | Account for hosting the Python voice service | [railway.app](https://railway.app) — free hobby tier |
| **Vercel** | Account for hosting the Next.js frontend | [vercel.com](https://vercel.com) — free |
| **Gemini API** | `GOOGLE_API_KEY` | [aistudio.google.com](https://aistudio.google.com/app/apikey) |

---

## 2. LiveKit Cloud Setup (5 min)

1. Go to [cloud.livekit.io](https://cloud.livekit.io) and create a free account.
2. Create a new **Project**.
3. In **Project Settings → Keys**, generate a new API Key + Secret.
4. Note down three values — you'll need them everywhere:
   - **WebSocket URL**: `wss://your-project.livekit.cloud`
   - **API Key**: `APIxxxxxxxxxxxxxx`
   - **API Secret**: `xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`

---

## 3. Deploy the Voice Agent Service on Railway

The `voice_agent/` folder contains two Python processes:

| Process | What it does |
|---|---|
| `token_server.py` | FastAPI server that mints short-lived LiveKit room tokens for browser guests |
| `agent.py` | Long-running LiveKit agent worker that joins rooms and routes audio to Gemini |

### 3.1. Push to GitHub

If your repository isn't on GitHub yet:

```bash
git add voice_agent/
git commit -m "feat: add LiveKit voice agent service"
git push
```

### 3.2. Create a Railway project

1. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**.
2. Select your repository, set the **Root Directory** to `voice_agent`.
3. Railway will detect the `Procfile` and start both processes automatically.

### 3.3. Set environment variables in Railway

In **Project → Variables**, add:

| Variable | Value |
|---|---|
| `LIVEKIT_URL` | `wss://your-project.livekit.cloud` |
| `LIVEKIT_API_KEY` | Your LiveKit API Key |
| `LIVEKIT_API_SECRET` | Your LiveKit API Secret |
| `GOOGLE_API_KEY` | Your Gemini API key |
| `ALLOWED_ORIGIN` | *(leave blank for now; fill in after you deploy to Vercel)* |

### 3.4. Get the token server URL

After deployment Railway will give you a public URL like:
```
https://your-service.railway.app
```

Test it works:
```bash
curl "https://your-service.railway.app/token?room=arc-room&identity=test"
# Should return {"token":"eyJ...","identity":"test"}
```

Save this URL — you'll need it for Vercel and for setting `ALLOWED_ORIGIN`.

### 3.5. Restrict CORS to your Vercel domain (after Vercel step)

Once you have your Vercel URL (step 4), update the `ALLOWED_ORIGIN` Railway variable:

```
ALLOWED_ORIGIN=https://your-project.vercel.app
```

Then redeploy Railway (it redeploys automatically on variable change).

---

## 4. Deploy the Next.js Frontend to Vercel

### 4.1. Create a Vercel project

1. Go to [vercel.com](https://vercel.com) → **New Project** → import your repository.
2. Set the **Root Directory** to `web`.
3. Vercel auto-detects Next.js. Leave build settings as-is.

### 4.2. Set environment variables in Vercel

In **Project → Settings → Environment Variables**, add:

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_LIVEKIT_URL` | `wss://your-project.livekit.cloud` |
| `NEXT_PUBLIC_TOKEN_SERVER_URL` | `https://your-service.railway.app` |
| `NEXT_PUBLIC_BIDI_WS_BASE` | `wss://your-adk-backend-domain.com/ws` *(optional — for text tab)* |

### 4.3. Deploy

Click **Deploy**. Vercel will build and publish the site. You'll get a URL like:
```
https://your-project.vercel.app
```

Open it on your phone or any device — you should see the ARC Meeting Room with a **Text Chat** tab and a **🎙 Voice Chat** tab.

---

## 5. Local Development

### 5.1. Voice agent service (Python)

```bash
# Clone the repo and install
cd voice_agent
pip install -r requirements.txt

# Copy and fill in env file
cp .env.example .env
# → edit .env with your LiveKit and Gemini credentials

# Terminal 1 — Token server
uvicorn token_server:app --port 7890 --reload

# Terminal 2 — Voice agent worker
python agent.py dev
```

The `dev` flag makes the agent connect to a local LiveKit server or LiveKit Cloud (based on your `LIVEKIT_URL` in `.env`) and restart automatically on code changes.

### 5.2. Next.js frontend

```bash
cd web

# Create local env file
cat > .env.local << 'EOF'
NEXT_PUBLIC_LIVEKIT_URL=wss://your-project.livekit.cloud
NEXT_PUBLIC_TOKEN_SERVER_URL=http://localhost:7890
NEXT_PUBLIC_BIDI_WS_BASE=ws://localhost:8000/ws
EOF

npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

---

## 6. Using the Voice Chat

1. Switch to the **🎙 Voice Chat** tab.
2. Fill in your **display name** (default: Guest).
3. Confirm the **LiveKit URL** and **Token server URL** are correct (pre-filled from env).
4. Click **🎙 Join Voice Room**.
5. Grant microphone permission when the browser asks.
6. The ARC AI agent will greet you within a second or two.
7. **Speak naturally** — the agent listens and responds in audio.
8. Click **🎙 Mute microphone** to mute yourself, or **📴 Leave voice room** to hang up.

> Both the **Text Chat** and **Voice Chat** tabs work independently. You can use them simultaneously in different browser tabs if you want.

---

## 7. Production Tips

- **HTTPS is required** for microphone access on mobile browsers. Vercel provides HTTPS automatically.
- **CORS**: Set `ALLOWED_ORIGIN` in Railway to your Vercel domain to prevent unauthorized use of your token server.
- **Multiple guests**: LiveKit Cloud supports multiple participants in the same room simultaneously — each gets their own WebRTC connection, and the agent will hear and respond to all of them.
- **Rooms**: You can create separate rooms for different meetings by changing the **Room name** field in the Voice Chat panel.
- **Agent persona**: Edit `voice_agent/agent.py` to change the AI's system prompt, voice, or model.

---

## 8. How It Works

```
1. Browser fetches a short-lived JWT from token_server.py
2. Browser connects to LiveKit Cloud room (WebRTC, UDP)
   └── Publishes mic track
3. agent.py (connected to the same room):
   └── Subscribes to guest mic track
   └── Runs Silero VAD (voice activity detection)
   └── Streams detected speech to Google STT
   └── Sends transcript to Gemini Live API
   └── Streams Gemini audio response to Google TTS
   └── Publishes TTS audio track back to the room
4. Browser subscribes to the agent's audio track and plays it
```

All audio routing stays within LiveKit Cloud — your browser never sends audio directly to Google. The Python agent bridges the room audio to the Gemini API.

---

## 9. File Reference

```
voice_agent/
├── agent.py           LiveKit agent worker (bridges room audio ↔ Gemini)
├── token_server.py    FastAPI token server (mints room JWTs for guests)
├── requirements.txt   Python dependencies
├── Procfile           Railway deployment config (runs both processes)
└── .env.example       Template — copy to .env and fill in your values

web/
├── app/
│   ├── page.tsx       Main page (Text Chat + Voice Chat tabs)
│   ├── globals.css    All styles including voice UI
│   └── layout.tsx     Root layout
├── next.config.mjs    Next.js config (env var documentation)
├── package.json       Node dependencies (includes LiveKit packages)
└── .env.local         Local dev env (not in git — create from step 5.2)
```
