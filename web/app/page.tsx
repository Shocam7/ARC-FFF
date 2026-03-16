"use client";

import {
  LiveKitRoom,
  RoomAudioRenderer,
  TrackToggle,
  useLocalParticipant,
  useRoomContext,
  useDataChannel,
  useTracks,
} from "@livekit/components-react";
import { Track, RoomEvent } from "livekit-client";
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
      audio={true}
      video={false}
      options={{
        // CRITICAL: Aggressive audio processing causes metallic/robotic sound
        audioCaptureDefaults: {
          echoCancellation: false,        // Disable - can cause metallic artifacts
          noiseSuppression: false,        // Disable - can cause robotic sound
          autoGainControl: false,         // Disable - can cause volume pumping
          // Explicit sample rate to avoid resampling
          sampleRate: 48000,              // 48kHz - standard for WebRTC
          channelCount: 1,                // Mono for voice
        },
        publishDefaults: {
          audioPreset: {
            maxBitrate: 96_000,           // Increased to 96kbps for better quality
          },
          // Disable DTX (discontinuous transmission) which can cause choppiness
          dtx: false,
          // Use RED (Redundant Encoding) for packet loss recovery
          red: true,
        },
        // CRITICAL: Configure jitter buffer to prevent stuttering
        webAudioMix: true,
        adaptiveStream: false,             // Disable - can cause quality fluctuations
        dynacast: false,                   // Disable - can cause switching artifacts
      }}
      onDisconnected={() => {
        disconnect();
        setMessages((prev) => [
          ...prev,
          { id: `sys-${Date.now()}`, from: "system", text: "Disconnected from meeting room.", ts: Date.now() },
        ]);
      }}
      onConnected={() => {
        setConnectionState("connected");
        setMessages((prev) => [
          ...prev,
          { id: `sys-${Date.now()}`, from: "system", text: `Joined meeting room as ${displayName}.`, ts: Date.now() },
        ]);
      }}
      onError={(error) => {
        console.error("LiveKit error:", error);
        setMessages((prev) => [
          ...prev,
          { id: `err-${Date.now()}`, from: "system", text: `Connection error: ${error.message}`, ts: Date.now() },
        ]);
      }}
    >
      <DataChannelHandler
        setMessages={setMessages}
        setRawEvents={setRawEvents}
        setImageStatus={setImageStatus}
      />
      <CustomAudioRenderer />
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
                    <span className="wave-bar" style={{ '--i': 1 } as any}></span>
                    <span className="wave-bar" style={{ '--i': 2 } as any}></span>
                    <span className="wave-bar" style={{ '--i': 3 } as any}></span>
                    <span className="wave-bar" style={{ '--i': 4 } as any}></span>
                    <span className="wave-bar" style={{ '--i': 5 } as any}></span>
                  </div>
                  <h2>LiveKit Voice Active</h2>
                  <p className="hint-text">Speak naturally. Audio optimized for clarity and low latency.</p>
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
                  <AudioDebugPanel />
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

// ── Custom Audio Renderer with Jitter Buffer Control ──────────────────────────
function CustomAudioRenderer() {
  const room = useRoomContext();
  const [audioError, setAudioError] = useState<string | null>(null);
  const audioElementsRef = useRef<Map<string, HTMLAudioElement>>(new Map());

  useEffect(() => {
    const handleTrackSubscribed = (track: any, publication: any, participant: any) => {
      if (track.kind !== Track.Kind.Audio) return;

      console.log("[Audio] Track subscribed:", {
        sid: track.sid,
        participant: participant.identity,
      });

      // Attach track to audio element with optimized settings
      track.attach().then((element: HTMLAudioElement) => {
        if (!element) return;

        // CRITICAL: Configure audio element for low-latency playback
        element.autoplay = true;
        (element as any).playsInline = true;

        // Minimize buffering to reduce latency and stuttering
        if ('sinkId' in element) {
          // Use default audio output
          (element as any).setSinkId('default').catch((err: any) => {
            console.warn('[Audio] Failed to set sink ID:', err);
          });
        }

        // Add to DOM (hidden)
        element.style.display = 'none';
        document.body.appendChild(element);

        // Store reference
        audioElementsRef.current.set(track.sid, element);

        // Monitor playback
        element.addEventListener('play', () => {
          console.log('[Audio] Playback started:', track.sid);
        });

        element.addEventListener('stalled', () => {
          console.warn('[Audio] Playback stalled:', track.sid);
          setAudioError('Audio playback stalled - reconnecting...');

          // Try to resume
          element.play().catch(err => console.error('[Audio] Resume failed:', err));
        });

        element.addEventListener('waiting', () => {
          console.warn('[Audio] Waiting for data:', track.sid);
        });

        // Force play (in case autoplay is blocked)
        element.play().catch(err => {
          console.warn('[Audio] Autoplay prevented, user interaction needed:', err);
        });

        setAudioError(null);
      }).catch((err: any) => {
        console.error('[Audio] Failed to attach track:', err);
        setAudioError(`Failed to attach audio: ${err.message}`);
      });
    };

    const handleTrackUnsubscribed = (track: any) => {
      if (track.kind !== Track.Kind.Audio) return;

      console.log("[Audio] Track unsubscribed:", track.sid);

      // Clean up audio element
      const element = audioElementsRef.current.get(track.sid);
      if (element) {
        element.pause();
        element.srcObject = null;
        element.remove();
        audioElementsRef.current.delete(track.sid);
      }
    };

    room.on(RoomEvent.TrackSubscribed, handleTrackSubscribed);
    room.on(RoomEvent.TrackUnsubscribed, handleTrackUnsubscribed);

    // Cleanup on unmount
    return () => {
      room.off(RoomEvent.TrackSubscribed, handleTrackSubscribed);
      room.off(RoomEvent.TrackUnsubscribed, handleTrackUnsubscribed);

      // Clean up all audio elements
      audioElementsRef.current.forEach(element => {
        element.pause();
        element.srcObject = null;
        element.remove();
      });
      audioElementsRef.current.clear();
    };
  }, [room]);

  return (
    <>
      {/* Still render default but our custom handler takes priority */}
      <RoomAudioRenderer />
      {audioError && (
        <div style={{
          position: "fixed",
          top: "1rem",
          right: "1rem",
          background: "#ef4444",
          color: "white",
          padding: "0.75rem 1rem",
          borderRadius: "8px",
          fontSize: "0.875rem",
          zIndex: 1000,
          maxWidth: "300px"
        }}>
          {audioError}
        </div>
      )}
    </>
  );
}

// ── Audio Debug Panel ──────────────────────────────────────────────────────────
function AudioDebugPanel() {
  const room = useRoomContext();
  const tracks = useTracks([Track.Source.Microphone], { onlySubscribed: false });
  const [stats, setStats] = useState<any>(null);
  const [remoteTracks, setRemoteTracks] = useState<number>(0);

  useEffect(() => {
    const interval = setInterval(async () => {
      // Local track stats
      if (room.localParticipant) {
        const audioTracks = room.localParticipant.audioTrackPublications;
        if (audioTracks.size > 0) {
          const track = Array.from(audioTracks.values())[0];
          if (track.track) {
            try {
              const rtpStats = await track.track.getRTCStatsReport();
              setStats({
                enabled: track.track.mediaStreamTrack.enabled,
                muted: track.isMuted,
                bitrate: track.track.currentBitrate,
              });
            } catch (err) {
              console.error("Failed to get audio stats:", err);
            }
          }
        }
      }

      // Count remote audio tracks
      let remoteCount = 0;
      room.remoteParticipants.forEach(participant => {
        participant.audioTrackPublications.forEach(pub => {
          if (pub.isSubscribed) remoteCount++;
        });
      });
      setRemoteTracks(remoteCount);
    }, 2000);

    return () => clearInterval(interval);
  }, [room]);

  return (
    <div style={{
      marginTop: "2rem",
      padding: "1rem",
      background: "rgba(255,255,255,0.05)",
      borderRadius: "8px",
      fontSize: "0.85rem",
      textAlign: "left",
      maxWidth: "400px",
      margin: "2rem auto 0"
    }}>
      <div style={{ fontWeight: 600, marginBottom: "0.5rem" }}>Audio Debug Info:</div>
      <div>Local tracks: {tracks.length}</div>
      <div>Remote tracks: {remoteTracks}</div>
      {stats && (
        <>
          <div>Enabled: {stats.enabled ? "Yes" : "No"}</div>
          <div>Muted: {stats.muted ? "Yes" : "No"}</div>
          <div>Bitrate: {stats.bitrate ? `${Math.round(stats.bitrate / 1000)} kbps` : "N/A"}</div>
        </>
      )}
      <div style={{ marginTop: "0.5rem", fontSize: "0.75rem", color: "#94a3b8" }}>
        Audio processing disabled for clarity
      </div>
    </div>
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
  }, [input, sendText, setInput]);

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
        <button type="button" className="control-button secondary" onClick={() => quickAsk("Mark, use the computer to browse google.com")} disabled={!connected}>
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