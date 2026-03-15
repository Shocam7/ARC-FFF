"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

// ── Types ─────────────────────────────────────────────────────────────────────
type ChatMessage = {
  id: string;
  from: "user" | "agent" | "system";
  text: string;
  ts: number;
};

type RawEvent = {
  [key: string]: unknown;
};

type ConnectionState = "disconnected" | "connecting" | "connected";
type AppTab = "text" | "voice";

// ── Helpers ───────────────────────────────────────────────────────────────────
function createIds() {
  const rand = Math.random().toString(36).slice(2, 8);
  const now = Date.now().toString(36);
  const userId = `guest-${rand}`;
  const sessionId = `web-${now}`;
  return { userId, sessionId };
}

// ── PCM Audio Format Helpers ──────────────────────────────────────────────────
// Web Audio API wants Float32 [-1.0, 1.0]. 
// Our Python backend wants/sends Int16 (signed 16-bit) PCM.

function float32ToInt16(float32Array: Float32Array): Int16Array {
  const int16Array = new Int16Array(float32Array.length);
  for (let i = 0; i < float32Array.length; i++) {
    const s = Math.max(-1, Math.min(1, float32Array[i]));
    int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
  }
  return int16Array;
}

function int16ToFloat32(int16Array: Int16Array): Float32Array {
  const float32Array = new Float32Array(int16Array.length);
  for (let i = 0; i < int16Array.length; i++) {
    const s = int16Array[i];
    float32Array[i] = s < 0 ? s / 0x8000 : s / 0x7FFF;
  }
  return float32Array;
}

// ── Main Page ──────────────────────────────────────────────────────────────────
export default function HomePage() {
  const [activeTab, setActiveTab] = useState<AppTab>("text");

  // State
  const [backendBase, setBackendBase] = useState<string>(
    process.env.NEXT_PUBLIC_BIDI_WS_BASE ?? "ws://localhost:8765/ws"
  );
  const [displayName, setDisplayName] = useState<string>("Guest");
  const [{ userId, sessionId }] = useState(() => createIds());
  const [connectionState, setConnectionState] = useState<ConnectionState>("disconnected");
  
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [rawEvents, setRawEvents] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const [imageStatus, setImageStatus] = useState<string>("idle");
  const [micActive, setMicActive] = useState<boolean>(false);

  // Refs
  const wsRef = useRef<WebSocket | null>(null);
  const eventsEndRef = useRef<HTMLDivElement | null>(null);
  const chatEndRef = useRef<HTMLDivElement | null>(null);
  
  // Audio Refs
  const audioCtxRef = useRef<AudioContext | null>(null);
  const captureCtxRef = useRef<AudioContext | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const playbackTimeRef = useRef<number>(0);

  const connected = connectionState === "connected";

  const connectionLabel = useMemo(() => {
    switch (connectionState) {
      case "connected": return "Connected";
      case "connecting": return "Connecting…";
      default: return "Disconnected";
    }
  }, [connectionState]);

  // ── Audio Playback Pipeline ────────────────────────────────────────────────
  const initAudioContext = () => {
    if (!audioCtxRef.current || audioCtxRef.current.state === "closed") {
      audioCtxRef.current = new (window.AudioContext || (window as any).webkitAudioContext)({
        sampleRate: 24000 // Gemini voice output uses 24kHz
      });
      playbackTimeRef.current = audioCtxRef.current.currentTime;
    }
  };

  const playAudioChunk = (int16Data: Int16Array) => {
    if (!audioCtxRef.current) return;
    const ctx = audioCtxRef.current;
    
    // Resume context if browser suspended it
    if (ctx.state === "suspended") ctx.resume();

    const floats = int16ToFloat32(int16Data);
    const audioBuffer = ctx.createBuffer(1, floats.length, 24000);
    audioBuffer.getChannelData(0).set(floats);

    const source = ctx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(ctx.destination);

    // Ensure continuous gapless playback
    const scheduledTime = Math.max(playbackTimeRef.current, ctx.currentTime);
    source.start(scheduledTime);
    playbackTimeRef.current = scheduledTime + audioBuffer.duration;
  };

  // ── Connection Logic ───────────────────────────────────────────────────────
  const connect = useCallback(() => {
    if (wsRef.current || connectionState !== "disconnected") return;
    try {
      const url = `${backendBase.replace(/\/$/, "")}/${encodeURIComponent(userId)}/${encodeURIComponent(sessionId)}`;
      const ws = new WebSocket(url);
      
      // We want array buffers for PCM audio
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;
      
      setConnectionState("connecting");
      initAudioContext();

      ws.onopen = () => {
        setConnectionState("connected");
        setMessages((prev) => [
          ...prev,
          { id: `sys-${Date.now()}`, from: "system", text: `Joined meeting room as ${displayName} (${userId}).`, ts: Date.now() },
        ]);
      };
      
      ws.onclose = () => { wsRef.current = null; setConnectionState("disconnected"); setMicActive(false); };
      ws.onerror = () => { wsRef.current = null; setConnectionState("disconnected"); setMicActive(false); };
      
      ws.onmessage = (event) => {
        // Binary audio chunk routing
        if (event.data instanceof ArrayBuffer) {
           const pcm16 = new Int16Array(event.data);
           playAudioChunk(pcm16);
           return;
        }

        // Text event routing
        try {
          const data: RawEvent = JSON.parse(event.data as string);
          if (data.type === "turn_complete") return; // Ignore pure structural events
          
          let text = null;
          let from: "agent" | "system" | "user" = "agent";

          if (data.type === "text_chunk" && !data.partial) {
             text = data.text as string;
          } else if (data.type === "transcription" && data.finished) {
             text = data.text as string;
             from = data.role === "user" ? "user" : "agent";
          } else if (data.type === "system") {
             text = data.text as string;
             from = "system";
          } else if (data.type === "routing") {
             text = `[Routing] ${data.note}`;
             from = "system";
          }

          if (data.type === "image_ready") {
             setImageStatus("Ready at: " + data.path);
             text = `Image generation complete! Ready at: ${data.path}`;
             from = "system";
          }

          if (text) {
             const finalFrom = from;
             const finalText = text;
             setMessages((prev) => [...prev, { id: `msg-${Date.now()}-${prev.length}`, from: finalFrom, text: finalText, ts: Date.now() }]);
          }

          setRawEvents((prev) => { const next = [...prev, JSON.stringify(data)]; if (next.length > 200) next.shift(); return next; });
        } catch {
          setRawEvents((prev) => { const next = [...prev, String(event.data)]; if (next.length > 200) next.shift(); return next; });
        }
      };
    } catch {
      setConnectionState("disconnected");
    }
  }, [backendBase, connectionState, displayName, sessionId, userId]);

  const disconnect = useCallback(() => {
    if (wsRef.current) { wsRef.current.close(); wsRef.current = null; }
    setConnectionState("disconnected");
    setMicActive(false);
  }, []);

  useEffect(() => { return () => { if (wsRef.current) wsRef.current.close(); }; }, []);
  useEffect(() => { if (eventsEndRef.current) eventsEndRef.current.scrollIntoView({ behavior: "smooth", block: "end" }); }, [rawEvents]);
  useEffect(() => { if (chatEndRef.current) chatEndRef.current.scrollIntoView({ behavior: "smooth", block: "end" }); }, [messages]);

  // ── Mic Capture Pipeline ───────────────────────────────────────────────────
  const toggleMic = async () => {
    if (micActive) {
       // Turn off mic
       if (mediaStreamRef.current) {
          mediaStreamRef.current.getTracks().forEach(t => t.stop());
          mediaStreamRef.current = null;
       }
       if (processorRef.current) {
          processorRef.current.disconnect();
          processorRef.current = null;
       }
       if (captureCtxRef.current) {
          captureCtxRef.current.close().catch(console.error);
          captureCtxRef.current = null;
       }
       setMicActive(false);
       return;
    }

    // Turn on mic
    if (!wsRef.current || connectionState !== "connected") {
       alert("Please connect to the meeting room first!");
       return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: {
         channelCount: 1,
         sampleRate: 16000,
         echoCancellation: true,
         noiseSuppression: true
      }});
      mediaStreamRef.current = stream;

      // Use a dedicated 16kHz AudioContext for capturing so the browser does native downsampling
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      const captureCtx = new AudioCtx({ sampleRate: 16000 });
      captureCtxRef.current = captureCtx;

      const source = captureCtx.createMediaStreamSource(stream);
      // Deprecated but widely supported way to process raw audio fast:
      const processor = ctx.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;

      processor.onaudioprocess = (e) => {
         if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
         
         const float32Array = e.inputBuffer.getChannelData(0);
         // Downsample handling isn't strictly necessary here if getUserMedia honored 16kHz,
         // but a robust app might implement a 48khz -> 16khz resampler here.
         const int16 = float32ToInt16(float32Array);
         wsRef.current.send(int16.buffer); // Send binary
      };

      source.connect(processor);
      
      // We connect the processor to the destination to make it run,
      // but we do NOT want to hear the microphone playback (echo).
      // Since we just capture raw frames, connecting a dummy gain node works.
      const gainNode = captureCtx.createGain();
      gainNode.gain.value = 0; // Mute the local echo
      processor.connect(gainNode);
      gainNode.connect(captureCtx.destination);
      
      setMicActive(true);

    } catch (err) {
      console.error("Mic access denied or failed", err);
      alert("Could not access microphone.");
      setMicActive(false);
    }
  };

  // ── Text Input ─────────────────────────────────────────────────────────────
  const sendText = useCallback((text: string) => {
    const trimmed = text.trim();
    if (!trimmed || !wsRef.current || connectionState !== "connected") return;
    wsRef.current.send(JSON.stringify({ type: "text", text: trimmed }));
    // We rely on the server bouncing back a transcription/text event to show it,
    // but we can controversially append to local chat optimistic tracking:
    // setMessages((prev) => [...prev, { id: `user-${Date.now()}-${prev.length}`, from: "user", text: trimmed, ts: Date.now() }]);
  }, [connectionState]);

  const handleSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;
    sendText(input);
    setInput("");
  }, [input, sendText]);

  const quickAsk = useCallback((prompt: string) => { sendText(prompt); }, [sendText]);

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <main className="app-root">
      <section className="card header">
        <div className="header-title">ARC Meeting Room (Guest)</div>
        <div className="header-subtitle">
          Join as a guest — chat via text or speak live with the AI panel via direct WebSocket audio.
        </div>
      </section>

      <div className="tab-bar">
        <button className={`tab-btn ${activeTab === "text" ? "active" : ""}`} onClick={() => setActiveTab("text")}>
          💬 Text Chat
        </button>
        <button className={`tab-btn ${activeTab === "voice" ? "active" : ""}`} onClick={() => setActiveTab("voice")}>
          🎙 Voice Call
        </button>
      </div>

      <section className="grid">
        <div className="meeting-room card">
          <div className="meeting-video">
             {activeTab === "voice" ? (
               <div style={{ textAlign: "center", padding: "4rem 0" }}>
                 <div style={{ fontSize: "5rem", marginBottom: "1rem" }}>{micActive ? '🗣️' : '🎙️'}</div>
                 <h2>Direct Voice Link</h2>
                 <p className="hint-text">Speak naturally. Audio streams via binary WebSocket direct to ARC.</p>
                 <br />
                 <button 
                  className={`primary-button ${micActive ? "danger" : ""}`}
                  onClick={toggleMic}
                  disabled={!connected}
                 >
                   {micActive ? "🔇 Stop Microphone" : "🎤 Allow Microphone"}
                 </button>
               </div>
             ) : (
                <>
                  <div className="meeting-video-header">
                    <span>Shared meeting room</span>
                    <span className="pill">{connectionState === "connected" ? "Live" : "Waiting for connection"}</span>
                  </div>
                  <div>
                    <div className="agents-row">
                      <span className="agent-pill">Mark (tools: web, computer, images)</span>
                      <span className="agent-pill">Other agents (handoffs)</span>
                    </div>
                    <div className="image-preview">
                      <div>Image generation status: {imageStatus}</div>
                      <div className="hint-text">
                        Ask Mark things like "Generate an image of a cozy meeting room" and the
                        image generation sub-agent will run in the background.
                      </div>
                    </div>
                  </div>
                </>
             )}
          </div>

          <div className="chat-card" style={{ display: activeTab === 'voice' ? 'none' : 'flex' }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ fontSize: "0.9rem", fontWeight: 500 }}>Conversation</div>
              <div className={`status-pill ${connectionState}`}>{connectionLabel}</div>
            </div>

            <div className="chat-log">
              {messages.map((m) => (
                <div key={m.id} className={`message-row ${m.from === "user" ? "user" : m.from === "agent" ? "agent" : ""}`}>
                  <span className={`message-badge ${m.from === "user" ? "user" : m.from === "agent" ? "agent" : ""}`}>
                    {m.from === "user" ? displayName : m.from === "agent" ? "Agent" : "System"}
                  </span>
                  <div className="message-body">
                    <div>{m.text}</div>
                    <div className="message-meta">
                      {new Date(m.ts).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
                    </div>
                  </div>
                </div>
              ))}
              <div ref={chatEndRef} />
            </div>

            <form onSubmit={handleSubmit} className="chat-input-row">
              <textarea
                className="chat-textarea"
                placeholder={connected ? "Ask the agents anything…" : "Connect to the meeting room first, then start chatting."}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                disabled={!connected}
              />
              <button type="submit" className="primary-button" disabled={!connected || !input.trim()}>
                Send
              </button>
            </form>
          </div>
        </div>

        <aside className="sidebar card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div style={{ fontSize: "0.95rem", fontWeight: 500 }}>Connection</div>
          </div>

          <div className="connection-form">
            <div className="field-group">
              <label className="field-label">Backend WebSocket URL</label>
              <input className="field-input" value={backendBase} onChange={(e) => setBackendBase(e.target.value)} placeholder="ws://localhost:8765/ws" />
              <div className="hint-text">Required: Uses port 8765 by default locally. For the internet use an ngrok URL.</div>
            </div>

            <div className="inline-fields">
              <div className="field-group" style={{ flex: 1 }}>
                <label className="field-label">Display name</label>
                <input className="field-input-inline" value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="Guest" />
              </div>
            </div>

            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginTop: "10px" }}>
              {connected ? (
                <button type="button" className="primary-button danger" onClick={disconnect}>Disconnect</button>
              ) : (
                <button type="button" className="primary-button success" onClick={connect}>Join Server</button>
              )}
            </div>
          </div>

          <div style={{ marginTop: "1rem" }}>
            <div style={{ fontSize: "0.9rem", fontWeight: 500, marginBottom: "0.4rem" }}>Quick actions for Mark</div>
            <div className="controls">
              <button type="button" className="control-button" onClick={() => quickAsk("Mark, please search the web and summarize the latest news relevant to this meeting.")} disabled={!connected}>
                Ask Mark to search the web
              </button>
              <button type="button" className="control-button secondary" onClick={() => quickAsk("Mark, use the computer to open a browser and go to google.com")} disabled={!connected}>
                Ask Mark to browse google
              </button>
            </div>
          </div>

          <div style={{ marginTop: "1rem" }}>
            <div style={{ fontSize: "0.9rem", fontWeight: 500, marginBottom: "0.4rem" }}>Live event stream</div>
            <div className="event-log">
              {rawEvents.map((line, idx) => (
                <div key={idx} className="event-line">{line}</div>
              ))}
              <div ref={eventsEndRef} />
            </div>
          </div>
        </aside>
      </section>
    </main>
  );
}
