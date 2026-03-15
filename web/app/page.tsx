"use client";

import {
  LiveKitRoom,
  RoomAudioRenderer,
  TrackToggle,
  useLocalParticipant,
  useRoomContext,
  useDataChannel,
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
  const [displayName, setDisplayName] = useState<string>("Guest");
  const [connectionState, setConnectionState] = useState<ConnectionState>("disconnected");
  
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [rawEvents, setRawEvents] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const [imageStatus, setImageStatus] = useState<string>("idle");
  const [livekitToken, setLivekitToken] = useState<string | null>(null);

  // Refs
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
    if (connectionState !== "disconnected") return;
    setConnectionState("connecting");

    // Fetch LiveKit Token
    fetch(`/api/livekit?room=bidi-demo-room&username=${encodeURIComponent(displayName)}`)
      .then((res) => res.json())
      .then((data) => {
         if (data.token) {
            setLivekitToken(data.token);
         } else {
            console.error("Token fetch failed", data);
            setConnectionState("disconnected");
         }
      })
      .catch((err) => {
          console.error("Failed to fetch LiveKit token", err);
          setConnectionState("disconnected");
      });
  }, [connectionState, displayName]);

  const disconnect = useCallback(() => {
    setConnectionState("disconnected");
    setLivekitToken(null);
  }, []);

  useEffect(() => { if (eventsEndRef.current) eventsEndRef.current.scrollIntoView({ behavior: "smooth", block: "end" }); }, [rawEvents]);
  useEffect(() => { if (chatEndRef.current) chatEndRef.current.scrollIntoView({ behavior: "smooth", block: "end" }); }, [messages]);

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <LiveKitRoom
      serverUrl={process.env.NEXT_PUBLIC_LIVEKIT_URL || "wss://arc-m0wlbys4.livekit.cloud"}
      token={livekitToken || ""}
      connect={!!livekitToken}
      audio={false}
      video={false}
      onDisconnected={disconnect}
      onConnected={() => {
        setConnectionState("connected");
        setMessages((prev) => [
          ...prev,
          { id: `sys-${Date.now()}`, from: "system", text: `Joined meeting room as ${displayName}.`, ts: Date.now() },
        ]);
      }}
    >
      <DataChannelHandler 
         setMessages={setMessages} 
         setRawEvents={setRawEvents} 
         setImageStatus={setImageStatus} 
      />
      <RoomAudioRenderer />
      <LiveKitStatusMonitor />
      <main className="app-root">
      <section className="card header">
        <div className="header-title">ARC Meeting Room (Guest)</div>
        <div className="header-subtitle">
          Join as a guest — chat via text or speak live with the AI panel via direct LiveKit WebRTC.
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
                   <div className="voice-wave-icon" style={{ justifyContent: "center", marginBottom: "1.5rem" }}>
                     <span className="wave-bar" style={{'--i': 1} as any}></span>
                     <span className="wave-bar" style={{'--i': 2} as any}></span>
                     <span className="wave-bar" style={{'--i': 3} as any}></span>
                     <span className="wave-bar" style={{'--i': 4} as any}></span>
                     <span className="wave-bar" style={{'--i': 5} as any}></span>
                   </div>
                   <h2>LiveKit Voice Active</h2>
                   <p className="hint-text">Speak naturally. Audio streams directly via LiveKit WebRTC for zero latency.</p>
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

            <ChatInput 
               connected={connected} 
               input={input} 
               setInput={setInput}
               setMessages={setMessages}
               displayName={displayName}
            />
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
                <button type="button" className="primary-button success" onClick={connect}>Connect to Room</button>
              )}
            </div>
          </div>

          <QuickActions connected={connected} />

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

// ── Components ─────────────────────────────────────────────────────────────

function DataChannelHandler({ setMessages, setRawEvents, setImageStatus }: any) {
  // Bind to the "chat" data channel matching the python backend expected topic
  useDataChannel("chat", (msg) => {
    try {
      const dataStr = new TextDecoder().decode(msg.payload);
      const data = JSON.parse(dataStr);
      
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
         setMessages((prev: any) => [...prev, { id: `msg-${Date.now()}-${prev.length}`, from: finalFrom, text: finalText, ts: Date.now() }]);
      }

      setRawEvents((prev: any) => { const next = [...prev, JSON.stringify(data)]; if (next.length > 200) next.shift(); return next; });
    } catch (err) {
      console.error("Failed handling datachannel msg", err);
    }
  });

  return null;
}

function ChatInput({ connected, input, setInput, setMessages, displayName }: { 
  connected: boolean; 
  input: string; 
  setInput: (v: string) => void;
  setMessages: (updater: (prev: ChatMessage[]) => ChatMessage[]) => void;
  displayName: string;
}) {
  // We use useDataChannel to GET the send function
  const { send } = useDataChannel("chat");
  
  const sendText = useCallback((text: string) => {
    const trimmed = text.trim();
    if (!trimmed || !connected) return;
    
    // Optimistically add the user message to the local conversation
    setMessages((prev) => [
      ...prev,
      { id: `user-${Date.now()}-${prev.length}`, from: "user", text: trimmed, ts: Date.now() },
    ]);

    // Publish via LiveKit Data Channel!
    const payload = JSON.stringify({ type: "text", text: trimmed });
    console.log("[Chat] Sending message via LiveKit data channel:", payload);
    send(new TextEncoder().encode(payload), { reliable: true, topic: "chat" })
      .then(() => console.log("[Chat] Message sent successfully"))
      .catch((err: unknown) => console.error("[Chat] Failed to send message via LiveKit:", err));
    
  }, [connected, send, setMessages]);

  const handleSubmit = useCallback((e: { preventDefault: () => void }) => {
    e.preventDefault();
    if (!input.trim()) return;
    sendText(input);
    setInput("");
  }, [input, sendText]);

  return (
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
  )
}

function QuickActions({ connected }: { connected: boolean }) {
  const { send } = useDataChannel("chat");
  
  const quickAsk = useCallback((prompt: string) => { 
    if (!connected) return;
    const payload = JSON.stringify({ type: "text", text: prompt });
    send(new TextEncoder().encode(payload), { reliable: true, topic: "chat" });
  }, [send, connected]);

  return (
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
  )
}

function LiveKitStatusMonitor() {
  const room = useRoomContext();
  const [status, setStatus] = useState("Disconnected");
  const [participants, setParticipants] = useState(0);

  useEffect(() => {
    const update = () => {
      setStatus(room.state);
      setParticipants(room.remoteParticipants.size + 1);
    };
    room.on("connectionStateChanged", update);
    room.on("participantConnected", update);
    room.on("participantDisconnected", update);
    update();
    return () => {
      room.off("connectionStateChanged", update);
      room.off("participantConnected", update);
      room.off("participantDisconnected", update);
    };
  }, [room]);

  if (room.state === "disconnected") return null;

  return (
    <div style={{
      position: "fixed",
      bottom: "1rem",
      left: "1rem",
      background: "rgba(0,0,0,0.8)",
      color: "white",
      padding: "0.5rem 1rem",
      borderRadius: "8px",
      fontSize: "0.8rem",
      zIndex: 1000,
      border: "1px solid #333"
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <div style={{ 
          width: "8px", 
          height: "8px", 
          borderRadius: "50%", 
          background: room.state === "connected" ? "#4ade80" : "#fbbf24" 
        }} />
        LiveKit: {status} ({participants} present)
      </div>
    </div>
  );
}
