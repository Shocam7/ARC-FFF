"use client";

import {
  LiveKitRoom,
  RoomAudioRenderer,
  TrackToggle,
  useLocalParticipant,
  useRoomContext,
  useDataChannel,
  useTracks,
  useParticipants,
} from "@livekit/components-react";
import { Track, RoomEvent } from "livekit-client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

// ── Types ─────────────────────────────────────────────────────────────────────
type ChatMessage = {
  id: string;
  from: "user" | "agent" | "system";
  text: string;
  ts: number;
  agentName?: string;
};
type ConnectionState = "disconnected" | "connecting" | "connected";

// ── Agent definitions ──────────────────────────────────────────────────────
const AGENTS = [
  { id: "mark",      name: "Mark",     color: "#4285f4", initials: "M"  },
  { id: "scientist", name: "Dr. Nova", color: "#34a853", initials: "DN" },
  { id: "historian", name: "Prof. Lex",color: "#ea4335", initials: "PL" },
];

// ── Shared styles ─────────────────────────────────────────────────────────────
const MEET_BG    = "#202124";
const TILE_BG    = "#3c4043";
const SURFACE    = "#292b2d";
const CONTROL_BG = "rgba(32,33,36,0.92)";
const ACTIVE_CLR = "#8ab4f8";
const TEXT_PRI   = "#e8eaed";
const TEXT_SEC   = "#9aa0a6";
const BTN_HOVER  = "rgba(255,255,255,0.08)";

// ── Main Page ──────────────────────────────────────────────────────────────────
export default function HomePage() {
  const [displayName, setDisplayName]     = useState("Guest");
  const [connectionState, setConnectionState] = useState<ConnectionState>("disconnected");
  const [messages, setMessages]           = useState<ChatMessage[]>([]);
  const [rawEvents, setRawEvents]         = useState<string[]>([]);
  const [input, setInput]                 = useState("");
  const [imageStatus, setImageStatus]     = useState("idle");
  const [livekitToken, setLivekitToken]   = useState<string | null>(null);
  const [chatOpen, setChatOpen]           = useState(false);
  const [settingsOpen, setSettingsOpen]   = useState(false);
  const [micOn, setMicOn]                 = useState(true);
  const [camOn, setCamOn]                 = useState(true);
  const [activeSpeaker, setActiveSpeaker] = useState<string | null>("mark");
  const chatEndRef = useRef<HTMLDivElement>(null);

  const connected = connectionState === "connected";

  const connect = useCallback(() => {
    if (connectionState !== "disconnected") return;
    setConnectionState("connecting");
    fetch(`/api/livekit?room=bidi-demo-room&username=${encodeURIComponent(displayName)}`)
      .then(r => r.json())
      .then(d => {
        if (d.token) setLivekitToken(d.token);
        else         setConnectionState("disconnected");
      })
      .catch(() => setConnectionState("disconnected"));
  }, [connectionState, displayName]);

  const disconnect = useCallback(() => {
    setConnectionState("disconnected");
    setLivekitToken(null);
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Rotate active speaker for demo feel when not connected
  useEffect(() => {
    if (connected) return;
    const ids = ["mark", "scientist", "historian", null];
    let i = 0;
    const t = setInterval(() => { i = (i + 1) % ids.length; setActiveSpeaker(ids[i]); }, 3000);
    return () => clearInterval(t);
  }, [connected]);

  return (
    <LiveKitRoom
      serverUrl={process.env.NEXT_PUBLIC_LIVEKIT_URL || "wss://arc-m0wlbys4.livekit.cloud"}
      token={livekitToken || ""}
      connect={!!livekitToken}
      audio={true}
      video={false}
      options={{
        audioCaptureDefaults: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, sampleRate: 48000, channelCount: 1 },
        publishDefaults: { audioPreset: { maxBitrate: 96_000 }, dtx: false, red: true },
        webAudioMix: true, adaptiveStream: false, dynacast: false,
      }}
      onConnected={() => {
        setConnectionState("connected");
        setMessages(p => [...p, { id: `sys-${Date.now()}`, from: "system", text: `Joined as ${displayName}`, ts: Date.now() }]);
      }}
      onDisconnected={() => {
        disconnect();
        setMessages(p => [...p, { id: `sys-${Date.now()}`, from: "system", text: "Left the meeting", ts: Date.now() }]);
      }}
      onError={e => {
        setMessages(p => [...p, { id: `err-${Date.now()}`, from: "system", text: `Error: ${e.message}`, ts: Date.now() }]);
      }}
    >
      <DataChannelHandler setMessages={setMessages} setRawEvents={setRawEvents} setImageStatus={setImageStatus} />
      <RoomAudioRenderer />

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;600&family=Google+Sans+Mono&display=swap');

        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        html, body { height: 100%; font-family: 'Google Sans', 'Segoe UI', sans-serif; background: ${MEET_BG}; color: ${TEXT_PRI}; overflow: hidden; }

        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #5f6368; border-radius: 2px; }

        @keyframes pulse-ring {
          0%   { box-shadow: 0 0 0 0 rgba(138,180,248,0.45); }
          70%  { box-shadow: 0 0 0 10px rgba(138,180,248,0);  }
          100% { box-shadow: 0 0 0 0 rgba(138,180,248,0);     }
        }
        @keyframes wave {
          0%, 100% { transform: scaleY(0.5); opacity: 0.5; }
          50%       { transform: scaleY(1.4); opacity: 1;   }
        }
        @keyframes fadeUp {
          from { opacity: 0; transform: translateY(8px); }
          to   { opacity: 1; transform: translateY(0);   }
        }
        @keyframes slideIn {
          from { transform: translateX(100%); opacity: 0; }
          to   { transform: translateX(0);    opacity: 1; }
        }
        @keyframes blink {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.4; }
        }
      `}</style>

      <div style={{ display: "flex", flexDirection: "column", height: "100vh", background: MEET_BG }}>
        {/* ── Top bar ─────────────────────────────────────────────────── */}
        <TopBar connected={connected} displayName={displayName} />

        {/* ── Main content ─────────────────────────────────────────────── */}
        <div style={{ flex: 1, display: "flex", overflow: "hidden", position: "relative" }}>
          {/* Tile grid */}
          <TileGrid agents={AGENTS} activeSpeaker={activeSpeaker} connected={connected} displayName={displayName} />

          {/* Chat panel */}
          {chatOpen && (
            <ChatPanel
              messages={messages}
              input={input}
              setInput={setInput}
              connected={connected}
              displayName={displayName}
              setMessages={setMessages}
              chatEndRef={chatEndRef}
              onClose={() => setChatOpen(false)}
            />
          )}

          {/* Settings panel */}
          {settingsOpen && (
            <SettingsPanel
              displayName={displayName}
              setDisplayName={setDisplayName}
              connected={connected}
              connect={connect}
              disconnect={disconnect}
              connectionState={connectionState}
              onClose={() => setSettingsOpen(false)}
            />
          )}
        </div>

        {/* ── Control bar ─────────────────────────────────────────────── */}
        <ControlBar
          micOn={micOn}
          camOn={camOn}
          connected={connected}
          chatOpen={chatOpen}
          setMicOn={setMicOn}
          setCamOn={setCamOn}
          setChatOpen={setChatOpen}
          setSettingsOpen={setSettingsOpen}
          connect={connect}
          disconnect={disconnect}
          connectionState={connectionState}
          livekitToken={livekitToken}
        />
      </div>
    </LiveKitRoom>
  );
}

// ── Top bar ────────────────────────────────────────────────────────────────────
function TopBar({ connected, displayName }: { connected: boolean; displayName: string }) {
  const [time, setTime] = useState(new Date());
  useEffect(() => { const t = setInterval(() => setTime(new Date()), 1000); return () => clearInterval(t); }, []);
  const fmt = time.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 20px", flexShrink: 0, zIndex: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
          <rect x="2" y="2" width="9" height="9" rx="1.5" fill="#4285f4"/>
          <rect x="13" y="2" width="9" height="9" rx="1.5" fill="#ea4335"/>
          <rect x="2" y="13" width="9" height="9" rx="1.5" fill="#34a853"/>
          <rect x="13" y="13" width="9" height="9" rx="1.5" fill="#fbbc05"/>
        </svg>
        <span style={{ fontSize: 14, fontWeight: 500, color: TEXT_PRI }}>ARC Meeting Room</span>
        {connected && (
          <span style={{
            fontSize: 11, fontWeight: 500, color: "#81c995",
            background: "rgba(52,168,83,0.15)", border: "1px solid rgba(52,168,83,0.3)",
            borderRadius: 99, padding: "2px 10px", animation: "fadeUp 0.3s ease"
          }}>
            ● Live
          </span>
        )}
      </div>
      <span style={{ fontSize: 13, color: TEXT_SEC, fontVariantNumeric: "tabular-nums" }}>{fmt}</span>
    </div>
  );
}

// ── Tile grid ──────────────────────────────────────────────────────────────────
function TileGrid({ agents, activeSpeaker, connected, displayName }: any) {
  const tiles = [
    ...agents,
    { id: "you", name: displayName || "You", color: "#8ab4f8", initials: (displayName || "Y").slice(0, 2).toUpperCase(), isLocal: true },
  ];

  return (
    <div style={{
      flex: 1,
      display: "grid",
      gridTemplateColumns: "repeat(2, 1fr)",
      gridTemplateRows: "repeat(2, 1fr)",
      gap: 6,
      padding: "4px 8px 8px",
      overflow: "hidden",
    }}>
      {tiles.map((t, i) => (
        <ParticipantTile
          key={t.id}
          participant={t}
          isActive={activeSpeaker === t.id}
          isSpeaking={activeSpeaker === t.id}
          isLocal={t.isLocal}
          connected={connected}
        />
      ))}
    </div>
  );
}

// ── Participant tile ──────────────────────────────────────────────────────────
function ParticipantTile({ participant: p, isActive, isSpeaking, isLocal, connected }: any) {
  const [hovered, setHovered] = useState(false);

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        position: "relative",
        borderRadius: 12,
        background: TILE_BG,
        overflow: "hidden",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        transition: "box-shadow 0.3s ease",
        boxShadow: isActive
          ? `0 0 0 3px ${ACTIVE_CLR}, 0 8px 32px rgba(0,0,0,0.4)`
          : "0 2px 12px rgba(0,0,0,0.3)",
        animation: isActive ? "pulse-ring 2s infinite" : "none",
        cursor: "default",
      }}
    >
      {/* Subtle noise texture */}
      <div style={{
        position: "absolute", inset: 0, opacity: 0.04,
        backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")`,
        backgroundSize: "128px",
      }} />

      {/* Gradient overlay */}
      <div style={{
        position: "absolute", inset: 0,
        background: `radial-gradient(ellipse at 40% 35%, ${p.color}18 0%, transparent 65%)`,
      }} />

      {/* Avatar */}
      <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
        <div style={{
          width: 72, height: 72, borderRadius: "50%",
          background: `linear-gradient(135deg, ${p.color}cc, ${p.color}66)`,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 22, fontWeight: 600, color: "#fff",
          boxShadow: `0 4px 20px ${p.color}40`,
          transition: "transform 0.2s ease",
          transform: isSpeaking ? "scale(1.06)" : "scale(1)",
          border: `2px solid ${p.color}44`,
        }}>
          {p.initials}
        </div>

        {/* Speaking bars */}
        {isSpeaking && (
          <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 18 }}>
            {[1.2, 1.8, 1, 1.5, 0.8].map((h, i) => (
              <span key={i} style={{
                display: "block", width: 3, borderRadius: 2,
                background: ACTIVE_CLR, height: `${h * 10}px`,
                animation: `wave ${0.8 + i * 0.1}s ease-in-out infinite`,
                animationDelay: `${i * 0.12}s`,
              }} />
            ))}
          </div>
        )}
      </div>

      {/* Name bar */}
      <div style={{
        position: "absolute", bottom: 0, left: 0, right: 0,
        background: "linear-gradient(to top, rgba(0,0,0,0.75) 0%, transparent 100%)",
        padding: "24px 12px 10px",
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <span style={{ fontSize: 13, fontWeight: 500, color: TEXT_PRI, letterSpacing: "0.01em" }}>
          {p.name}{isLocal ? " (You)" : ""}
        </span>

        <div style={{ display: "flex", gap: 4 }}>
          {/* Mic muted indicator */}
          {!isSpeaking && !isLocal && (
            <div style={{
              width: 26, height: 26, borderRadius: "50%",
              background: "rgba(234,67,53,0.85)",
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.5" strokeLinecap="round">
                <line x1="2" y1="2" x2="22" y2="22"/>
                <path d="M18.89 13.23A7.12 7.12 0 0 0 19 12v-2"/>
                <path d="M5 10v2a7 7 0 0 0 12 5"/>
                <path d="M15 9.34V5a3 3 0 0 0-5.68-1.33"/>
                <path d="M9 9v3a3 3 0 0 0 5.12 2.12"/>
                <line x1="12" y1="19" x2="12" y2="22"/>
                <line x1="8" y1="22" x2="16" y2="22"/>
              </svg>
            </div>
          )}
          {/* Speaking indicator dot */}
          {isSpeaking && (
            <div style={{
              width: 26, height: 26, borderRadius: "50%",
              background: "rgba(138,180,248,0.2)",
              border: "1.5px solid rgba(138,180,248,0.6)",
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={ACTIVE_CLR} strokeWidth="2.5" strokeLinecap="round">
                <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/>
                <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
                <line x1="12" y1="19" x2="12" y2="22"/>
                <line x1="8" y1="22" x2="16" y2="22"/>
              </svg>
            </div>
          )}
        </div>
      </div>

      {/* Hover shine */}
      <div style={{
        position: "absolute", inset: 0, borderRadius: 12,
        background: "linear-gradient(135deg, rgba(255,255,255,0.04) 0%, transparent 50%)",
        opacity: hovered ? 1 : 0, transition: "opacity 0.2s",
        pointerEvents: "none",
      }} />
    </div>
  );
}

// ── Control bar ────────────────────────────────────────────────────────────────
function ControlBar({ micOn, camOn, connected, chatOpen, setMicOn, setCamOn, setChatOpen, setSettingsOpen, connect, disconnect, connectionState, livekitToken }: any) {
  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "10px 24px 16px", flexShrink: 0, gap: 12,
      background: MEET_BG,
    }}>
      {/* Left: meeting info */}
      <div style={{ flex: "0 0 200px", display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{ fontSize: 12, color: TEXT_SEC }}>Team meeting</div>
        <div style={{
          fontSize: 11, color: TEXT_SEC,
          background: SURFACE, borderRadius: 99,
          padding: "3px 10px", fontVariantNumeric: "tabular-nums",
        }}>
          {new Date().toLocaleDateString([], { month: "short", day: "numeric" })}
        </div>
      </div>

      {/* Center: primary controls */}
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <CtrlBtn
          active={micOn} danger={!micOn}
          onClick={() => setMicOn((v: boolean) => !v)}
          label={micOn ? "Mute mic" : "Unmute mic"}
          icon={micOn
            ? <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/>
            : <><line x1="2" y1="2" x2="22" y2="22"/><path d="M18.89 13.23A7.12 7.12 0 0 0 19 12v-2"/><path d="M5 10v2a7 7 0 0 0 12 5"/><path d="M15 9.34V5a3 3 0 0 0-5.68-1.33"/><path d="M9 9v3a3 3 0 0 0 5.12 2.12"/><line x1="12" y1="19" x2="12" y2="22"/><line x1="8" y1="22" x2="16" y2="22"/></>
          }
          extraPaths={!micOn}
        />
        <CtrlBtn
          active={camOn} danger={!camOn}
          onClick={() => setCamOn((v: boolean) => !v)}
          label={camOn ? "Turn off cam" : "Turn on cam"}
          icon={camOn
            ? <><rect x="2" y="7" width="15" height="10" rx="2"/><path d="m22 8-5 4 5 4V8z"/></>
            : <><path d="M10.66 6H14a2 2 0 0 1 2 2v2.34"/><path d="M16 16H7a2 2 0 0 1-2-2V8"/><line x1="2" y1="2" x2="22" y2="22"/></>
          }
        />

        <div style={{ width: 1, height: 32, background: "#5f6368", margin: "0 4px" }} />

        <CtrlBtn label="Captions" icon={<><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></>} />
        <CtrlBtn label="Raise hand" icon={<><path d="M18 11V6a2 2 0 0 0-2-2 2 2 0 0 0-2 2"/><path d="M14 10V4a2 2 0 0 0-2-2 2 2 0 0 0-2 2v2"/><path d="M10 10.5V6a2 2 0 0 0-2-2 2 2 0 0 0-2 2v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/></>} />
        <CtrlBtn label="Emoji" icon={<><circle cx="12" cy="12" r="10"/><path d="M8 13s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></>} />
        <CtrlBtn label="Present" icon={<><path d="M2 3h20v13H2z"/><path d="M8 21h8"/><path d="M12 17v4"/></>} />

        <div style={{ width: 1, height: 32, background: "#5f6368", margin: "0 4px" }} />

        {/* End call / join */}
        {connected ? (
          <button
            onClick={disconnect}
            title="Leave call"
            style={{
              height: 48, padding: "0 24px", borderRadius: 99, border: "none",
              background: "#ea4335", color: "#fff", cursor: "pointer",
              display: "flex", alignItems: "center", gap: 8, fontFamily: "inherit",
              fontSize: 13, fontWeight: 500, transition: "filter 0.15s, transform 0.1s",
            }}
            onMouseEnter={e => (e.currentTarget.style.filter = "brightness(1.15)")}
            onMouseLeave={e => (e.currentTarget.style.filter = "brightness(1)")}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07"/>
              <path d="M2 2l20 20"/>
              <path d="M10.84 6.06a19.73 19.73 0 0 1 9.09 3.86 2 2 0 0 1 .07 2.97l-2.28 2.28c-.39.39-1 .46-1.45.17L13 13"/>
              <path d="M9.75 9.75 7.27 7.27a1 1 0 0 0-1.45.17l-2.28 2.28a2 2 0 0 0 .33 2.97 19.61 19.61 0 0 0 2.88 1.83"/>
            </svg>
            Leave
          </button>
        ) : (
          <button
            onClick={connect}
            disabled={connectionState === "connecting"}
            title="Join call"
            style={{
              height: 48, padding: "0 24px", borderRadius: 99, border: "none",
              background: connectionState === "connecting" ? "#5f6368" : "#34a853",
              color: "#fff", cursor: connectionState === "connecting" ? "wait" : "pointer",
              display: "flex", alignItems: "center", gap: 8, fontFamily: "inherit",
              fontSize: 13, fontWeight: 500, transition: "filter 0.15s",
            }}
          >
            {connectionState === "connecting" ? (
              <span style={{ animation: "blink 1s infinite" }}>Joining…</span>
            ) : "Join now"}
          </button>
        )}
      </div>

      {/* Right: side panel toggles */}
      <div style={{ flex: "0 0 200px", display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 4 }}>
        <CtrlBtn label="Info" icon={<><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></>} />
        <CtrlBtn label="People" badge="4" icon={<><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></>} />
        <CtrlBtn
          label="Chat" active={chatOpen}
          onClick={() => setChatOpen((v: boolean) => !v)}
          icon={<><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></>}
        />
        <CtrlBtn
          label="Settings"
          onClick={() => setSettingsOpen((v: boolean) => !v)}
          icon={<><circle cx="12" cy="12" r="3"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M4.93 4.93a10 10 0 0 0 0 14.14"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2"/></>}
        />
      </div>
    </div>
  );
}

// ── Control button ────────────────────────────────────────────────────────────
function CtrlBtn({ icon, label, onClick, active, danger, badge, extraPaths }: any) {
  const [hov, setHov] = useState(false);
  return (
    <button
      title={label}
      onClick={onClick}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        position: "relative",
        width: 48, height: 48, borderRadius: "50%", border: "none",
        background: danger ? "rgba(234,67,53,0.9)" : active ? "rgba(138,180,248,0.15)" : hov ? BTN_HOVER : "transparent",
        color: danger ? "#fff" : active ? ACTIVE_CLR : TEXT_PRI,
        cursor: onClick ? "pointer" : "default",
        display: "flex", alignItems: "center", justifyContent: "center",
        transition: "background 0.15s, color 0.15s, transform 0.1s",
        transform: hov && onClick ? "scale(1.05)" : "scale(1)",
        flexShrink: 0,
      }}
    >
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        {icon}
      </svg>
      {badge && (
        <span style={{
          position: "absolute", top: 6, right: 6,
          background: ACTIVE_CLR, color: MEET_BG,
          borderRadius: 99, fontSize: 9, fontWeight: 700,
          minWidth: 14, height: 14, lineHeight: "14px", textAlign: "center", padding: "0 3px",
        }}>
          {badge}
        </span>
      )}
    </button>
  );
}

// ── Chat panel ─────────────────────────────────────────────────────────────────
function ChatPanel({ messages, input, setInput, connected, displayName, setMessages, chatEndRef, onClose }: any) {
  const { send } = useDataChannel("chat");

  const sendMsg = useCallback(() => {
    const t = input.trim();
    if (!t || !connected) return;
    setMessages((p: any) => [...p, { id: `u-${Date.now()}`, from: "user", text: t, ts: Date.now() }]);
    const payload = JSON.stringify({ type: "text", text: t });
    send(new TextEncoder().encode(payload), { reliable: true, topic: "chat" }).catch(console.error);
    setInput("");
  }, [input, connected, send, setMessages, setInput]);

  return (
    <div style={{
      position: "absolute", top: 0, right: 0, bottom: 0,
      width: 320, background: SURFACE,
      borderLeft: "1px solid rgba(255,255,255,0.08)",
      display: "flex", flexDirection: "column",
      animation: "slideIn 0.25s cubic-bezier(0.4,0,0.2,1)",
      zIndex: 20,
    }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "16px 16px 12px", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
        <span style={{ fontSize: 15, fontWeight: 500 }}>In-call messages</span>
        <button onClick={onClose} style={{ background: "none", border: "none", color: TEXT_SEC, cursor: "pointer", padding: 4, borderRadius: 4, display: "flex" }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflowY: "auto", padding: "12px 16px", display: "flex", flexDirection: "column", gap: 12 }}>
        {messages.length === 0 && (
          <div style={{ textAlign: "center", color: TEXT_SEC, fontSize: 13, marginTop: 40 }}>
            No messages yet.<br />Start the conversation!
          </div>
        )}
        {messages.map((m: ChatMessage) => (
          <div key={m.id} style={{ display: "flex", flexDirection: "column", gap: 2, animation: "fadeUp 0.2s ease" }}>
            <span style={{ fontSize: 11, color: TEXT_SEC, fontWeight: 500 }}>
              {m.from === "user" ? displayName : m.from === "agent" ? (m as any).agentName || "Agent" : "System"}
              <span style={{ marginLeft: 6, fontWeight: 400 }}>
                {new Date(m.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              </span>
            </span>
            <div style={{
              fontSize: 13, lineHeight: 1.5, color: m.from === "system" ? TEXT_SEC : TEXT_PRI,
              background: m.from === "user" ? "rgba(138,180,248,0.12)" : "rgba(255,255,255,0.04)",
              borderRadius: 8, padding: "8px 12px",
              borderLeft: m.from === "agent" ? `2px solid ${ACTIVE_CLR}` : "none",
            }}>
              {m.text}
            </div>
          </div>
        ))}
        <div ref={chatEndRef} />
      </div>

      {/* Input */}
      <div style={{ padding: 12, borderTop: "1px solid rgba(255,255,255,0.06)" }}>
        <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMsg(); } }}
            placeholder={connected ? "Send a message…" : "Join to chat"}
            disabled={!connected}
            rows={2}
            style={{
              flex: 1, borderRadius: 8, border: "1px solid rgba(255,255,255,0.1)",
              background: "rgba(255,255,255,0.06)", color: TEXT_PRI,
              fontSize: 13, padding: "8px 10px", resize: "none",
              fontFamily: "inherit", outline: "none",
              opacity: connected ? 1 : 0.5,
            }}
          />
          <button
            onClick={sendMsg}
            disabled={!connected || !input.trim()}
            style={{
              width: 36, height: 36, borderRadius: "50%", border: "none",
              background: connected && input.trim() ? "#4285f4" : "rgba(255,255,255,0.08)",
              color: "#fff", cursor: connected && input.trim() ? "pointer" : "default",
              display: "flex", alignItems: "center", justifyContent: "center",
              transition: "background 0.15s", flexShrink: 0,
            }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Settings panel ─────────────────────────────────────────────────────────────
function SettingsPanel({ displayName, setDisplayName, connected, connect, disconnect, connectionState, onClose }: any) {
  return (
    <div style={{
      position: "absolute", top: 0, right: 0, bottom: 0,
      width: 320, background: SURFACE,
      borderLeft: "1px solid rgba(255,255,255,0.08)",
      display: "flex", flexDirection: "column",
      animation: "slideIn 0.25s cubic-bezier(0.4,0,0.2,1)",
      zIndex: 20, padding: 20,
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
        <span style={{ fontSize: 15, fontWeight: 500 }}>Connection</span>
        <button onClick={onClose} style={{ background: "none", border: "none", color: TEXT_SEC, cursor: "pointer", padding: 4, borderRadius: 4, display: "flex" }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>

      <label style={{ fontSize: 12, color: TEXT_SEC, marginBottom: 6 }}>Display name</label>
      <input
        value={displayName}
        onChange={e => setDisplayName(e.target.value)}
        style={{
          borderRadius: 8, border: "1px solid rgba(255,255,255,0.15)",
          background: "rgba(255,255,255,0.06)", color: TEXT_PRI,
          fontSize: 14, padding: "10px 12px", fontFamily: "inherit", outline: "none",
          marginBottom: 20,
        }}
        placeholder="Your name"
      />

      <div style={{
        padding: "12px 14px", borderRadius: 8,
        background: connected ? "rgba(52,168,83,0.1)" : "rgba(255,255,255,0.04)",
        border: `1px solid ${connected ? "rgba(52,168,83,0.3)" : "rgba(255,255,255,0.08)"}`,
        marginBottom: 16,
        fontSize: 13, color: connected ? "#81c995" : TEXT_SEC,
        display: "flex", alignItems: "center", gap: 8,
      }}>
        <div style={{ width: 8, height: 8, borderRadius: "50%", background: connected ? "#34a853" : "#9aa0a6", flexShrink: 0, boxShadow: connected ? "0 0 6px #34a853" : "none" }} />
        {connected ? "Connected to room" : connectionState === "connecting" ? "Connecting…" : "Not connected"}
      </div>

      {connected ? (
        <button
          onClick={disconnect}
          style={{
            width: "100%", padding: "10px 0", borderRadius: 8, border: "none",
            background: "rgba(234,67,53,0.15)", color: "#f28b82",
            outline: "1px solid rgba(234,67,53,0.3)",
            fontSize: 14, fontWeight: 500, cursor: "pointer", fontFamily: "inherit",
          }}
        >
          Leave room
        </button>
      ) : (
        <button
          onClick={connect}
          disabled={connectionState === "connecting"}
          style={{
            width: "100%", padding: "10px 0", borderRadius: 8, border: "none",
            background: "linear-gradient(135deg, #4285f4, #34a853)",
            color: "#fff", fontSize: 14, fontWeight: 500, cursor: "pointer", fontFamily: "inherit",
            opacity: connectionState === "connecting" ? 0.6 : 1,
          }}
        >
          {connectionState === "connecting" ? "Joining…" : "Join room"}
        </button>
      )}
    </div>
  );
}

// ── Data channel handler (unchanged logic) ─────────────────────────────────────
function DataChannelHandler({ setMessages, setRawEvents, setImageStatus }: any) {
  useDataChannel("chat", (msg) => {
    try {
      const data = JSON.parse(new TextDecoder().decode(msg.payload));
      if (data.type === "turn_complete") return;

      let text: string | null = null;
      let from: "agent" | "system" | "user" = "agent";

      if (data.type === "text_chunk" && !data.partial)                text = data.text;
      else if (data.type === "transcription" && data.finished)        { text = data.text; from = data.role === "user" ? "user" : "agent"; }
      else if (data.type === "system")                                 { text = data.text; from = "system"; }
      else if (data.type === "routing")                                { text = `[Routing] ${data.note}`; from = "system"; }
      if (data.type === "image_ready")                                 { setImageStatus("Ready: " + data.path); text = `Image ready: ${data.path}`; from = "system"; }

      if (text) {
        const agentId = data.agent_id as string;
        const agentName = agentId === "mark" ? "Mark" : agentId === "scientist" ? "Dr. Nova" : agentId === "historian" ? "Prof. Lex" : "Agent";
        setMessages((p: any) => [...p, { id: `msg-${Date.now()}-${p.length}`, from, text, ts: Date.now(), agentName }]);
      }

      setRawEvents((p: any) => { const n = [...p, JSON.stringify(data)]; if (n.length > 200) n.shift(); return n; });
    } catch {}
  });
  return null;
}
