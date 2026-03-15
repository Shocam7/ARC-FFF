"use client";

import {
  LiveKitRoom,
  RoomAudioRenderer,
  TrackToggle,
  useLocalParticipant,
  useRoomContext,
  useTracks,
  AudioTrack
} from "@livekit/components-react";
import { Track } from "livekit-client";
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
  const [livekitToken, setLivekitToken] = useState<string | null>(null);

  // Refs
  const wsRef = useRef<WebSocket | null>(null);
  const eventsEndRef = useRef<HTMLDivElement | null>(null);
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  const connected = connectionState === "connected";

  const connectionLabel = useMemo(() => {
    switch (connectionState) {
      case "connected": return "Connected";
      case "connecting": return "Connecting…";
      default: return "Disconnected";
    }
  }, [connectionState]);

  // ── Connection Logic ───────────────────────────────────────────────────────
  const connect = useCallback(() => {
    if (wsRef.current || connectionState !== "disconnected") return;
    try {
      const url = `${backendBase.replace(/\/$/, "")}/${encodeURIComponent(userId)}/${encodeURIComponent(sessionId)}`;
      const ws = new WebSocket(url);
      
      wsRef.current = ws;
      
      setConnectionState("connecting");

      // Fetch LiveKit Token
      fetch(`/api/livekit?room=bidi-demo-room&username=${encodeURIComponent(displayName)}`)
        .then((res) => res.json())
        .then((data) => {
           if (data.token) {
              setLivekitToken(data.token);
           }
        })
        .catch((err) => console.error("Failed to fetch LiveKit token", err));

      ws.onopen = () => {
        setConnectionState("connected");
        setMessages((prev) => [
          ...prev,
          { id: `sys-${Date.now()}`, from: "system", text: `Joined meeting room as ${displayName} (${userId}).`, ts: Date.now() },
        ]);
      };
      
      ws.onclose = () => { wsRef.current = null; setConnectionState("disconnected"); setLivekitToken(null); };
      ws.onerror = () => { wsRef.current = null; setConnectionState("disconnected"); setLivekitToken(null); };
      
      ws.onmessage = (event) => {
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
    setLivekitToken(null);
  }, []);

  useEffect(() => { return () => { if (wsRef.current) wsRef.current.close(); }; }, []);
  useEffect(() => { if (eventsEndRef.current) eventsEndRef.current.scrollIntoView({ behavior: "smooth", block: "end" }); }, [rawEvents]);
  useEffect(() => { if (chatEndRef.current) chatEndRef.current.scrollIntoView({ behavior: "smooth", block: "end" }); }, [messages]);
  const sendText = useCallback((text: string) => {
    const trimmed = text.trim();
    if (!trimmed || !wsRef.current || connectionState !== "connected") return;
    wsRef.current.send(JSON.stringify({ type: "text", text: trimmed }));
    // We rely on the server bouncing back a transcription/text event to show it,
    // but we can controversially append to local chat optimistic tracking.
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
    <LiveKitRoom
      serverUrl={process.env.NEXT_PUBLIC_LIVEKIT_URL || "wss://arc-m0wlbys4.livekit.cloud"}
      token={livekitToken || ""}
      connect={!!livekitToken}
      audio={false}
      video={false}
    >
      <RoomAudioRenderer />
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
                   <div style={{ fontSize: "5rem", marginBottom: "1rem" }}>🎙️</div>
                   <h2>LiveKit Voice Active</h2>
                   <p className="hint-text">Speak naturally. Audio streams directly via LiveKit WebRTC for zero latency.</p>
                   {livekitToken && <RoomAudioRenderer />}
                   <br />
                   {connected && !livekitToken && (
                     <div style={{ color: "orange" }}>Generating LiveKit token... Make sure LIVEKIT_API_KEY is in .env.local</div>
                   )}
                   {connected && livekitToken && (
                     <div style={{ marginTop: "2rem" }}>
                       <TrackToggle
                         source={Track.Source.Microphone}
                         className="primary-button"
                       >
                         Microphone
                       </TrackToggle>
                     </div>
                   )}
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
            <div style={{ fontSize: "0.75rem", color: livekitToken ? "#4ade80" : "#94a3b8" }}>
              LiveKit: {livekitToken ? "Active" : "Idle"}
            </div>
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
    </LiveKitRoom>
  );
}
