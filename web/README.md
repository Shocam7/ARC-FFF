# ARC Meeting Room — Web Client + Voice Guide

A mobile-friendly web client for the ARC multi-agent meeting room. Guests can:

- 💬 **Text Chat** — send messages to the agents over WebSocket
- 🎙 **Voice Chat** — speak live with the AI panel via direct binary WebSockets

## Multiplayer Game Architecture

The ARC Master application (the PyQt6 app) acts as the **"Game Server"**. It runs on your local PC so that the **Computer Use** subagent can actively move your actual desktop mouse and keyboard.

Web clients are **"Thin Clients"**. They connect to your desktop over a WebSocket to stream audio from their phone microphones directly into the Gemini model running on your PC, and hear the responses streamed back.

```
Browser (Phone / Laptop)
  │
  ├── Text Chat ── JSON ── WebSocket ──────┐
  │                                        ▼
  └── Voice Mic ─ Binary ─ WebSocket ──► ngrok tunnel ──► Local PyQt6 App (:8765)
                                           ▲
                                           │
                                     Gemini Live API
```

---

## 1. Running the Host Server

On your main PC where ARC is installed, start the application:

```bash
cd app
uv run python main.py
```
*The background WebSocket server automatically starts on port 8765.*

---

## 2. Exposing the Server (ngrok)

To allow phones or other computers to connect to your local PC, you need to expose port 8765 to the internet. The easiest way is using ngrok:

1. Install [ngrok](https://ngrok.com/download).
2. Open a new terminal and run:
   ```bash
   ngrok http 8765
   ```
3. Ngrok will provide a "Forwarding" HTTPS URL, for example:
   `https://a1b2c3d4.ngrok-free.app`

Note: WebSockets use `wss://`. Your actual WebSocket URL will simply be:
**`wss://a1b2c3d4.ngrok-free.app/ws`**

*(Keep that terminal running!)*

---

## 3. Running the Web Client

The web client runs on Next.js. You can run it locally or deploy it to Vercel so guests can access it from their phones.

### Running Locally

1. Create a `.env.local` file in the `web` directory:
   ```bash
   NEXT_PUBLIC_BIDI_WS_BASE=ws://localhost:8765/ws
   ```
   *(Or use your `wss://` ngrok URL here if testing over the network).*

2. Start the dev server:
   ```bash
   cd web
   npm install
   npm run dev
   ```

3. Open `http://localhost:3000` in multiple browser tabs to simulate multiple guests!

### Deploying to Vercel (For remote phones)

1. Push your code to GitHub.
2. Import the repository into [Vercel](https://vercel.com).
3. In the Vercel project settings, set the Environment Variable:
   - `NEXT_PUBLIC_BIDI_WS_BASE` = `wss://your-ngrok-url.ngrok-free.app/ws`
4. Deploy!

Now you can open the Vercel URL on your phone, click "Voice Chat", allow microphone access, and you're talking directly to your PC's AI agents. Notice that "Computer Use" commands issued on your phone will execute on your PC's physical screen!
