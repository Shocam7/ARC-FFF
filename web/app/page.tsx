"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  LiveKitRoom,
  useLocalParticipant,
  useRoomInfo,
  useTracks,
  AudioTrack,
} from "@livekit/components-react";
import { Track } from "livekit-client";
import "@livekit/components-styles";

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

const DEFAULT_TOKEN_SERVER =
  process.env.NEXT_PUBLIC_TOKEN_SERVER_URL ?? "http://localhost:7890";
const DEFAULT_LIVEKIT_URL =
  process.env.NEXT_PUBLIC_LIVEKIT_URL ?? "wss://your-project.livekit.cloud";

// ── Voice Room inner component ─────────────────────────────────────────────────
function VoiceRoomInner() {
  const { localParticipant } = useLocalParticipant();
  const [muted, setMuted] = useState(false);
  const roomInfo = useRoomInfo();

  // Subscribe to all remote audio tracks (agent voice)
  const agentTracks = useTracks([{ source: Track.Source.Microphone, withPlaceholder: false }], {
    onlySubscribed: true,
  }).filter((t) => !t.participant.isLocal);

  const toggleMute = useCallback(async () => {
    const next = !muted;
    await localParticipant.setMicrophoneEnabled(!next);
    setMuted(next);
  }, [localParticipant, muted]);

  return (
    <div className="voice-room-inner">
      {/* Render agent audio tracks (plays through browser speaker automatically) */}
      {agentTracks.map((track) => (
        <AudioTrack key={track.publication?.trackSid} trackRef={track} />
      ))}

      <div className="voice-status-row">
        <div className="voice-wave-icon" aria-label="Voice active">
          <span className="wave-bar" style={{ "--i": 0 } as React.CSSProperties} />
          <span className="wave-bar" style={{ "--i": 1 } as React.CSSProperties} />
          <span className="wave-bar" style={{ "--i": 2 } as React.CSSProperties} />
          <span className="wave-bar" style={{ "--i": 3 } as React.CSSProperties} />
          <span className="wave-bar" style={{ "--i": 4 } as React.CSSProperties} />
        </div>
        <div className="voice-room-label">
          {roomInfo.name ? `Room: ${roomInfo.name}` : "Connected to ARC voice room"}
        </div>
      </div>

      <p className="voice-hint">
        🎙 Speak naturally — the AI agent will respond in audio.
      </p>

      <button
        className={`mute-button ${muted ? "muted" : ""}`}
        onClick={toggleMute}
        aria-pressed={muted}
      >
        {muted ? "🔇 Unmute microphone" : "🎙 Mute microphone"}
      </button>
    </div>
  );
}

// ── Voice tab component ────────────────────────────────────────────────────────
function VoiceTab() {
  const [tokenServerUrl, setTokenServerUrl] = useState(DEFAULT_TOKEN_SERVER);
  const [livekitUrl, setLivekitUrl] = useState(DEFAULT_LIVEKIT_URL);
  const [roomName, setRoomName] = useState("arc-room");
  const [displayName, setDisplayName] = useState("Guest");
  const [token, setToken] = useState<string | null>(null);
  const [joining, setJoining] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);

  const joinRoom = useCallback(async () => {
    setJoining(true);
    setError(null);
    try {
      const identity = `${displayName.replace(/\s+/g, "-").toLowerCase()}-${Math.random()
        .toString(36)
        .slice(2, 6)}`;
      const url = `${tokenServerUrl.replace(/\/$/, "")}/token?room=${encodeURIComponent(
        roomName
      )}&identity=${encodeURIComponent(identity)}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`Token server returned ${res.status}`);
      const data = await res.json();
      setToken(data.token);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(`Failed to get token: ${msg}`);
    } finally {
      setJoining(false);
    }
  }, [tokenServerUrl, roomName, displayName]);

  const leaveRoom = useCallback(() => {
    setToken(null);
    setConnected(false);
  }, []);

  return (
    <div className="voice-tab">
      {!token ? (
        <div className="voice-config card">
          <div className="voice-config-header">
            <h2 className="voice-config-title">🎙 Join Voice Room</h2>
            <p className="voice-config-sub">
              Speak directly to the ARC AI panel via WebRTC. Uses LiveKit Cloud
              + Gemini Live API.
            </p>
          </div>

          <div className="voice-fields">
            <div className="field-group">
              <label className="field-label">Display name</label>
              <input
                className="field-input"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="Guest"
              />
            </div>

            <div className="field-group">
              <label className="field-label">Room name</label>
              <input
                className="field-input"
                value={roomName}
                onChange={(e) => setRoomName(e.target.value)}
                placeholder="arc-room"
              />
            </div>

            <div className="field-group">
              <label className="field-label">LiveKit URL</label>
              <input
                className="field-input"
                value={livekitUrl}
                onChange={(e) => setLivekitUrl(e.target.value)}
                placeholder="wss://your-project.livekit.cloud"
              />
              <div className="hint-text">
                From your{" "}
                <a
                  href="https://cloud.livekit.io"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="link"
                >
                  LiveKit Cloud
                </a>{" "}
                project settings.
              </div>
            </div>

            <div className="field-group">
              <label className="field-label">Token server URL</label>
              <input
                className="field-input"
                value={tokenServerUrl}
                onChange={(e) => setTokenServerUrl(e.target.value)}
                placeholder="http://localhost:7890"
              />
              <div className="hint-text">
                Your deployed Railway URL (or localhost for local dev).
              </div>
            </div>
          </div>

          {error && <div className="error-box">{error}</div>}

          <button
            className="primary-button voice-join-btn"
            onClick={joinRoom}
            disabled={joining || !livekitUrl || !tokenServerUrl}
          >
            {joining ? "Connecting…" : "🎙 Join Voice Room"}
          </button>
        </div>
      ) : (
        <div className="voice-room-container card">
          <LiveKitRoom
            audio={true}
            video={false}
            token={token}
            serverUrl={livekitUrl}
            onConnected={() => setConnected(true)}
            onDisconnected={leaveRoom}
            className="livekit-room"
          >
            <VoiceRoomInner />
          </LiveKitRoom>

          <button className="leave-button" onClick={leaveRoom}>
            📴 Leave voice room
          </button>
        </div>
      )}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────
export default function HomePage() {
  const [activeTab, setActiveTab] = useState<AppTab>("text");

  // ── Text-chat state (unchanged from original) ──────────────────────────────
  const [backendBase, setBackendBase] = useState<string>(
    process.env.NEXT_PUBLIC_BIDI_WS_BASE ?? "ws://localhost:8000/ws"
  );
  const [displayName, setDisplayName] = useState<string>("Guest");
  const [{ userId, sessionId }] = useState(() => createIds());

  const [connectionState, setConnectionState] = useState<ConnectionState>("disconnected");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [rawEvents, setRawEvents] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const [imageStatus, setImageStatus] = useState<string>("idle");

  const wsRef = useRef<WebSocket | null>(null);
  const eventsEndRef = useRef<HTMLDivElement | null>(null);
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  const connected = connectionState === "connected";

  const connectionLabel = useMemo(() => {
    switch (connectionState) {
      case "connected":   return "Connected";
      case "connecting":  return "Connecting…";
      default:            return "Disconnected";
    }
  }, [connectionState]);

  const connect = useCallback(() => {
    if (wsRef.current || connectionState !== "disconnected") return;
    try {
      const url = `${backendBase.replace(/\/$/, "")}/${encodeURIComponent(userId)}/${encodeURIComponent(sessionId)}`;
      const ws = new WebSocket(url);
      wsRef.current = ws;
      setConnectionState("connecting");

      ws.onopen = () => {
        setConnectionState("connected");
        setMessages((prev) => [
          ...prev,
          { id: `sys-${Date.now()}`, from: "system", text: `Joined meeting room as ${displayName} (${userId}).`, ts: Date.now() },
        ]);
      };
      ws.onclose = () => { wsRef.current = null; setConnectionState("disconnected"); };
      ws.onerror = () => { wsRef.current = null; setConnectionState("disconnected"); };
      ws.onmessage = (event) => {
        try {
          const data: RawEvent = JSON.parse(event.data as string);
          const text = extractTextFromEvent(data);
          const imageUpdate = extractImageStatusFromEvent(data);
          if (text) {
            setMessages((prev) => [...prev, { id: `agent-${Date.now()}-${prev.length}`, from: "agent", text, ts: Date.now() }]);
          }
          if (imageUpdate) setImageStatus(imageUpdate);
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
  }, []);

  useEffect(() => { return () => { if (wsRef.current) wsRef.current.close(); }; }, []);
  useEffect(() => { if (eventsEndRef.current) eventsEndRef.current.scrollIntoView({ behavior: "smooth", block: "end" }); }, [rawEvents]);
  useEffect(() => { if (chatEndRef.current) chatEndRef.current.scrollIntoView({ behavior: "smooth", block: "end" }); }, [messages]);

  const sendText = useCallback((text: string) => {
    const trimmed = text.trim();
    if (!trimmed || !wsRef.current || connectionState !== "connected") return;
    wsRef.current.send(JSON.stringify({ type: "text", text: trimmed }));
    setMessages((prev) => [...prev, { id: `user-${Date.now()}-${prev.length}`, from: "user", text: trimmed, ts: Date.now() }]);
  }, [connectionState]);

  const handleSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;
    sendText(input);
    setInput("");
  }, [input, sendText]);

  const quickAsk = useCallback((prompt: string) => { sendText(prompt); }, [sendText]);

  return (
    <main className="app-root">
      <section className="card header">
        <div className="header-title">ARC Meeting Room (Guest)</div>
        <div className="header-subtitle">
          Join as a guest — chat via text or speak live with the AI panel.
        </div>
      </section>

      {/* ── Tab switcher ────────────────────────────────────────────────────── */}
      <div className="tab-bar">
        <button
          className={`tab-btn ${activeTab === "text" ? "active" : ""}`}
          onClick={() => setActiveTab("text")}
        >
          💬 Text Chat
        </button>
        <button
          className={`tab-btn ${activeTab === "voice" ? "active" : ""}`}
          onClick={() => setActiveTab("voice")}
        >
          🎙 Voice Chat
        </button>
      </div>

      {/* ── Text Chat tab ────────────────────────────────────────────────────── */}
      {activeTab === "text" && (
        <section className="grid">
          {/* Meeting room + chat */}
          <div className="meeting-room card">
            <div className="meeting-video">
              <div className="meeting-video-header">
                <span>Shared meeting room</span>
                <span className="pill">
                  {connectionState === "connected" ? "Live" : "Waiting for connection"}
                </span>
              </div>
              <div>
                <div className="agents-row">
                  <span className="agent-pill">Mark (tools: web, computer, images)</span>
                  <span className="agent-pill">Other agents (handoffs)</span>
                </div>
                <div className="image-preview">
                  <div>Image generation status: {imageStatus}</div>
                  <div className="hint-text">
                    Ask Mark things like &quot;Generate an image of a cozy meeting room&quot; and the
                    image generation sub-agent will run in the background.
                  </div>
                </div>
              </div>
              <div className="room-footer">
                <span className="hint-text">
                  This view reflects the shared state of the ARC meeting, not a webcam feed.
                </span>
              </div>
            </div>

            <div className="chat-card">
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

          {/* Sidebar */}
          <aside className="sidebar card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ fontSize: "0.95rem", fontWeight: 500 }}>Connection</div>
            </div>

            <div className="connection-form">
              <div className="field-group">
                <label className="field-label">Backend WebSocket base URL</label>
                <input className="field-input" value={backendBase} onChange={(e) => setBackendBase(e.target.value)} placeholder="ws://localhost:8000/ws" />
                <div className="hint-text">Your FastAPI ADK server, e.g. <code>wss://your-domain.com/ws</code>.</div>
              </div>

              <div className="inline-fields">
                <div className="field-group" style={{ flex: 1 }}>
                  <label className="field-label">Display name</label>
                  <input className="field-input-inline" value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="Guest" />
                </div>
              </div>

              <div className="inline-fields">
                <div className="field-group" style={{ flex: 1 }}>
                  <label className="field-label">User ID</label>
                  <input className="field-input-inline" value={userId} readOnly />
                </div>
                <div className="field-group" style={{ flex: 1 }}>
                  <label className="field-label">Session ID</label>
                  <input className="field-input-inline" value={sessionId} readOnly />
                </div>
              </div>

              <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                {connected ? (
                  <button type="button" className="primary-button" onClick={disconnect}>Disconnect</button>
                ) : (
                  <button type="button" className="primary-button" onClick={connect}>Join meeting room</button>
                )}
              </div>
            </div>

            <div style={{ marginTop: "0.5rem" }}>
              <div style={{ fontSize: "0.9rem", fontWeight: 500, marginBottom: "0.4rem" }}>Quick actions for Mark</div>
              <div className="controls">
                <button type="button" className="control-button" onClick={() => quickAsk("Mark, please search the web and summarize the latest news relevant to this meeting.")} disabled={!connected}>
                  Ask Mark to search the web
                </button>
                <button type="button" className="control-button secondary" onClick={() => quickAsk("Mark, use the computer to open the relevant dashboard and check on our current metrics.")} disabled={!connected}>
                  Ask Mark to use the computer
                </button>
                <button type="button" className="control-button" onClick={() => quickAsk("Mark, generate an image that visualizes this meeting as a futuristic control room.")} disabled={!connected}>
                  Ask Mark to generate an image
                </button>
              </div>
            </div>

            <div style={{ marginTop: "0.75rem" }}>
              <div style={{ fontSize: "0.9rem", fontWeight: 500, marginBottom: "0.4rem" }}>Live event stream</div>
              <div className="event-log">
                {rawEvents.map((line, idx) => (
                  <div key={idx} className="event-line">{line}</div>
                ))}
                <div ref={eventsEndRef} />
              </div>
            </div>

            <div className="hint-text" style={{ marginTop: "0.5rem" }}>
              This UI is a thin client on top of your existing ADK FastAPI backend.
            </div>
          </aside>
        </section>
      )}

      {/* ── Voice Chat tab ───────────────────────────────────────────────────── */}
      {activeTab === "voice" && <VoiceTab />}
    </main>
  );
}

// ── Event helpers (unchanged) ─────────────────────────────────────────────────
function extractTextFromEvent(ev: RawEvent): string | null {
  if (!ev || typeof ev !== "object") return null;
  if (typeof ev["text"] === "string") return ev["text"] as string;
  if (typeof ev["data"] === "string") return ev["data"] as string;
  if (typeof ev["message"] === "string") return ev["message"] as string;
  return null;
}

function extractImageStatusFromEvent(_ev: RawEvent): string | null {
  return null;
}
