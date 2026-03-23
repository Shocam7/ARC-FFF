"use client";

import {
  LiveKitRoom,
  RoomAudioRenderer,
  useDataChannel,
} from "@livekit/components-react";
import { useCallback, useEffect, useRef, useState } from "react";

// ── Types ─────────────────────────────────────────────────────────────────────
type ChatMessage = {
  id: string;
  from: "user" | "agent" | "system";
  text: string;
  ts: number;
  agentName?: string;
};
type ConnectionState = "disconnected" | "connecting" | "connected";

// ── Agents ────────────────────────────────────────────────────────────────────
const AGENTS = [
  { id: "mark",      name: "Mark",      color: "#4285f4", initials: "M"  },
  { id: "scientist", name: "Dr. Nova",  color: "#34a853", initials: "DN" },
  { id: "historian", name: "Prof. Lex", color: "#ea4335", initials: "PL" },
];

// ── Tokens ────────────────────────────────────────────────────────────────────
const MEET_BG    = "#202124";
const TILE_BG    = "#3c4043";
const SURFACE    = "#292b2d";
const ACTIVE_CLR = "#8ab4f8";
const TEXT_PRI   = "#e8eaed";
const TEXT_SEC   = "#9aa0a6";

// ── Responsive hook ───────────────────────────────────────────────────────────
function useIsMobile() {
  const [mobile, setMobile] = useState(false);
  useEffect(() => {
    const check = () => setMobile(window.innerWidth < 640);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);
  return mobile;
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function HomePage() {
  const isMobile = useIsMobile();

  const [displayName, setDisplayName]         = useState("Guest");
  const [connectionState, setConnectionState] = useState<ConnectionState>("disconnected");
  const [messages, setMessages]               = useState<ChatMessage[]>([]);
  const [rawEvents, setRawEvents]             = useState<string[]>([]);
  const [input, setInput]                     = useState("");
  const [imageStatus, setImageStatus]         = useState("idle");
  const [livekitToken, setLivekitToken]       = useState<string | null>(null);
  const [chatOpen, setChatOpen]               = useState(false);
  const [settingsOpen, setSettingsOpen]       = useState(false);
  const [micOn, setMicOn]                     = useState(true);
  const [camOn, setCamOn]                     = useState(true);
  const [activeSpeaker, setActiveSpeaker]     = useState<string | null>("mark");
  const chatEndRef = useRef<HTMLDivElement>(null);

  const connected = connectionState === "connected";

  const connect = useCallback(() => {
    if (connectionState !== "disconnected") return;
    setConnectionState("connecting");
    fetch(`/api/livekit?room=bidi-demo-room&username=${encodeURIComponent(displayName)}`)
      .then(r => r.json())
      .then(d => { if (d.token) setLivekitToken(d.token); else setConnectionState("disconnected"); })
      .catch(() => setConnectionState("disconnected"));
  }, [connectionState, displayName]);

  const disconnect = useCallback(() => {
    setConnectionState("disconnected");
    setLivekitToken(null);
  }, []);

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  useEffect(() => {
    if (connected) return;
    const ids: (string | null)[] = ["mark", "scientist", "historian", null];
    let i = 0;
    const t = setInterval(() => { i = (i + 1) % ids.length; setActiveSpeaker(ids[i]); }, 3000);
    return () => clearInterval(t);
  }, [connected]);

  // Close overlapping panels on mobile
  useEffect(() => { if (isMobile && chatOpen && settingsOpen) setSettingsOpen(false); }, [chatOpen]);
  useEffect(() => { if (isMobile && chatOpen && settingsOpen) setChatOpen(false); }, [settingsOpen]);

  const tiles = [
    ...AGENTS,
    { id: "you", name: displayName || "You", color: "#8ab4f8", initials: (displayName || "Y").slice(0, 2).toUpperCase(), isLocal: true },
  ];

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
      onError={e => setMessages(p => [...p, { id: `err-${Date.now()}`, from: "system", text: `Error: ${e.message}`, ts: Date.now() }])}
    >
      <DataChannelHandler setMessages={setMessages} setRawEvents={setRawEvents} setImageStatus={setImageStatus} />
      <RoomAudioRenderer />

      {/* ── Global styles ── */}
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;600&display=swap');
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        html, body {
          height: 100%; width: 100%; overflow: hidden;
          font-family: 'Google Sans', 'Segoe UI', sans-serif;
          background: ${MEET_BG}; color: ${TEXT_PRI};
          -webkit-tap-highlight-color: transparent;
          -webkit-text-size-adjust: 100%;
        }
        ::-webkit-scrollbar { width: 3px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #5f6368; border-radius: 2px; }
        button { touch-action: manipulation; font-family: inherit; }
        textarea, input { font-family: inherit; -webkit-appearance: none; }

        @keyframes pulse-ring {
          0%   { box-shadow: 0 0 0 0   rgba(138,180,248,.45); }
          70%  { box-shadow: 0 0 0 10px rgba(138,180,248,0);  }
          100% { box-shadow: 0 0 0 0   rgba(138,180,248,0);   }
        }
        @keyframes wave {
          0%,100% { transform: scaleY(.5); opacity: .5; }
          50%     { transform: scaleY(1.4); opacity: 1; }
        }
        @keyframes fadeUp {
          from { opacity: 0; transform: translateY(6px); }
          to   { opacity: 1; transform: translateY(0);   }
        }
        @keyframes slideRight {
          from { transform: translateX(100%); opacity: 0; }
          to   { transform: translateX(0);    opacity: 1; }
        }
        @keyframes slideUp {
          from { transform: translateY(100%); opacity: 0; }
          to   { transform: translateY(0);    opacity: 1; }
        }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:.4} }
      `}</style>

      {/* ── Root shell ── */}
      <div style={{ display: "flex", flexDirection: "column", height: "100svh", background: MEET_BG }}>

        {/* ── Top bar ── */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: isMobile ? "10px 12px" : "12px 20px", flexShrink: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" style={{ flexShrink: 0 }}>
              <rect x="2"  y="2"  width="9" height="9" rx="1.5" fill="#4285f4"/>
              <rect x="13" y="2"  width="9" height="9" rx="1.5" fill="#ea4335"/>
              <rect x="2"  y="13" width="9" height="9" rx="1.5" fill="#34a853"/>
              <rect x="13" y="13" width="9" height="9" rx="1.5" fill="#fbbc05"/>
            </svg>
            <span style={{ fontSize: isMobile ? 13 : 14, fontWeight: 500 }}>
              {isMobile ? "ARC Meet" : "ARC Meeting Room"}
            </span>
            {connected && (
              <span style={{ fontSize: 11, fontWeight: 500, color: "#81c995", background: "rgba(52,168,83,.15)", border: "1px solid rgba(52,168,83,.3)", borderRadius: 99, padding: "2px 8px", animation: "fadeUp .3s ease", flexShrink: 0 }}>
                ● Live
              </span>
            )}
          </div>
          <Clock />
        </div>

        {/* ── Main area (tiles + panels) ── */}
        <div style={{ flex: 1, position: "relative", display: "flex", minHeight: 0 }}>

          {/* Tile grid */}
          <div style={{
            flex: 1,
            display: "grid",
            gridTemplateColumns: "repeat(2, 1fr)",
            gridTemplateRows: "repeat(2, 1fr)",
            gap: isMobile ? 3 : 6,
            padding: isMobile ? "2px 3px 3px" : "4px 8px 8px",
            minHeight: 0,
            // Shrink grid when side panel is open on desktop
            width: (!isMobile && (chatOpen || settingsOpen)) ? "calc(100% - 320px)" : "100%",
            transition: "width 0.25s cubic-bezier(.4,0,.2,1)",
          }}>
            {tiles.map(t => (
              <Tile
                key={t.id}
                p={t}
                isActive={activeSpeaker === t.id}
                isMobile={isMobile}
              />
            ))}
          </div>

          {/* Side panel — desktop slides from right, mobile covers full screen */}
          {(chatOpen || settingsOpen) && (
            <div style={isMobile
              ? { position: "absolute", inset: 0, zIndex: 30, animation: "slideUp .25s cubic-bezier(.4,0,.2,1)", background: SURFACE, display: "flex", flexDirection: "column" }
              : { width: 320, flexShrink: 0, background: SURFACE, borderLeft: "1px solid rgba(255,255,255,.08)", display: "flex", flexDirection: "column", animation: "slideRight .25s cubic-bezier(.4,0,.2,1)" }
            }>
              {chatOpen && (
                <ChatInner
                  messages={messages} input={input} setInput={setInput}
                  connected={connected} displayName={displayName}
                  setMessages={setMessages} chatEndRef={chatEndRef}
                  onClose={() => setChatOpen(false)}
                />
              )}
              {settingsOpen && (
                <SettingsInner
                  displayName={displayName} setDisplayName={setDisplayName}
                  connected={connected} connect={connect} disconnect={disconnect}
                  connectionState={connectionState} onClose={() => setSettingsOpen(false)}
                />
              )}
            </div>
          )}
        </div>

        {/* ── Control bar ── */}
        {isMobile
          ? (
            /* Mobile: centered essential row */
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8, padding: "8px 10px 20px", background: MEET_BG, flexShrink: 0 }}>
              <IBtn size={52} danger={!micOn} active={micOn} label={micOn ? "Mute" : "Unmute"} onClick={() => setMicOn(v => !v)}>
                {micOn
                  ? <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/>
                  : <><line x1="2" y1="2" x2="22" y2="22"/><path d="M18.89 13.23A7.12 7.12 0 0 0 19 12v-2"/><path d="M5 10v2a7 7 0 0 0 12 5"/><path d="M15 9.34V5a3 3 0 0 0-5.68-1.33"/><path d="M9 9v3a3 3 0 0 0 5.12 2.12"/><line x1="12" y1="19" x2="12" y2="22"/><line x1="8" y1="22" x2="16" y2="22"/></>
                }
              </IBtn>
              <IBtn size={52} danger={!camOn} active={camOn} label={camOn ? "Cam off" : "Cam on"} onClick={() => setCamOn(v => !v)}>
                {camOn
                  ? <><rect x="2" y="7" width="15" height="10" rx="2"/><path d="m22 8-5 4 5 4V8z"/></>
                  : <><path d="M10.66 6H14a2 2 0 0 1 2 2v2.34"/><path d="M16 16H7a2 2 0 0 1-2-2V8"/><line x1="2" y1="2" x2="22" y2="22"/></>
                }
              </IBtn>

              {/* End / Join */}
              {connected
                ? <PillBtn color="#ea4335" onClick={disconnect}>
                    <PhoneOff /> Leave
                  </PillBtn>
                : <PillBtn color="#34a853" disabled={connectionState === "connecting"} onClick={connect}>
                    {connectionState === "connecting"
                      ? <span style={{ animation: "blink 1s infinite" }}>Joining…</span>
                      : "Join now"
                    }
                  </PillBtn>
              }

              <IBtn size={52} active={chatOpen} label="Chat" onClick={() => { setChatOpen(v => !v); setSettingsOpen(false); }}>
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
              </IBtn>
              <IBtn size={52} active={settingsOpen} label="Settings" onClick={() => { setSettingsOpen(v => !v); setChatOpen(false); }}>
                <><circle cx="12" cy="12" r="3"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M4.93 4.93a10 10 0 0 0 0 14.14"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2"/></>
              </IBtn>
            </div>
          ) : (
            /* Desktop: 3-zone layout */
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 24px 16px", flexShrink: 0, background: MEET_BG }}>
              {/* Left */}
              <div style={{ flex: "0 0 200px", display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 12, color: TEXT_SEC }}>Team meeting</span>
                <span style={{ fontSize: 11, color: TEXT_SEC, background: SURFACE, borderRadius: 99, padding: "3px 10px" }}>
                  {new Date().toLocaleDateString([], { month: "short", day: "numeric" })}
                </span>
              </div>
              {/* Center */}
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <IBtn danger={!micOn} active={micOn} label={micOn ? "Mute mic" : "Unmute"} onClick={() => setMicOn(v => !v)}>
                  {micOn
                    ? <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/>
                    : <><line x1="2" y1="2" x2="22" y2="22"/><path d="M18.89 13.23A7.12 7.12 0 0 0 19 12v-2"/><path d="M5 10v2a7 7 0 0 0 12 5"/><path d="M15 9.34V5a3 3 0 0 0-5.68-1.33"/><path d="M9 9v3a3 3 0 0 0 5.12 2.12"/><line x1="12" y1="19" x2="12" y2="22"/><line x1="8" y1="22" x2="16" y2="22"/></>
                  }
                </IBtn>
                <IBtn danger={!camOn} active={camOn} label={camOn ? "Cam off" : "Cam on"} onClick={() => setCamOn(v => !v)}>
                  {camOn
                    ? <><rect x="2" y="7" width="15" height="10" rx="2"/><path d="m22 8-5 4 5 4V8z"/></>
                    : <><path d="M10.66 6H14a2 2 0 0 1 2 2v2.34"/><path d="M16 16H7a2 2 0 0 1-2-2V8"/><line x1="2" y1="2" x2="22" y2="22"/></>
                  }
                </IBtn>
                <Divider />
                <IBtn label="Captions"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></IBtn>
                <IBtn label="Raise hand"><><path d="M18 11V6a2 2 0 0 0-2-2 2 2 0 0 0-2 2"/><path d="M14 10V4a2 2 0 0 0-2-2 2 2 0 0 0-2 2v2"/><path d="M10 10.5V6a2 2 0 0 0-2-2 2 2 0 0 0-2 2v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/></></IBtn>
                <IBtn label="Emoji"><><circle cx="12" cy="12" r="10"/><path d="M8 13s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></></IBtn>
                <IBtn label="Present"><><path d="M2 3h20v13H2z"/><path d="M8 21h8"/><path d="M12 17v4"/></></IBtn>
                <Divider />
                {connected
                  ? <PillBtn color="#ea4335" onClick={disconnect}><PhoneOff /> Leave</PillBtn>
                  : <PillBtn color={connectionState === "connecting" ? "#5f6368" : "#34a853"} disabled={connectionState === "connecting"} onClick={connect}>
                      {connectionState === "connecting" ? <span style={{ animation: "blink 1s infinite" }}>Joining…</span> : "Join now"}
                    </PillBtn>
                }
              </div>
              {/* Right */}
              <div style={{ flex: "0 0 200px", display: "flex", justifyContent: "flex-end", gap: 4 }}>
                <IBtn label="Info"><><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></></IBtn>
                <IBtn label="People" badge="4"><><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></></IBtn>
                <IBtn active={chatOpen} label="Chat" onClick={() => { setChatOpen(v => !v); setSettingsOpen(false); }}><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></IBtn>
                <IBtn active={settingsOpen} label="Settings" onClick={() => { setSettingsOpen(v => !v); setChatOpen(false); }}><><circle cx="12" cy="12" r="3"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M4.93 4.93a10 10 0 0 0 0 14.14"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2"/></></IBtn>
              </div>
            </div>
          )
        }
      </div>
    </LiveKitRoom>
  );
}

// ── Tile ──────────────────────────────────────────────────────────────────────
function Tile({ p, isActive, isMobile }: { p: any; isActive: boolean; isMobile: boolean }) {
  const sz = isMobile ? 46 : 72;
  return (
    <div style={{
      position: "relative", borderRadius: isMobile ? 8 : 12,
      background: TILE_BG, overflow: "hidden",
      display: "flex", alignItems: "center", justifyContent: "center",
      boxShadow: isActive ? `0 0 0 2px ${ACTIVE_CLR}, 0 4px 20px rgba(0,0,0,.4)` : "0 2px 8px rgba(0,0,0,.3)",
      animation: isActive ? "pulse-ring 2s infinite" : "none",
      transition: "box-shadow .3s",
    }}>
      {/* color glow */}
      <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at 40% 35%, ${p.color}18 0%, transparent 65%)` }} />

      {/* avatar */}
      <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "center", gap: 7 }}>
        <div style={{
          width: sz, height: sz, borderRadius: "50%",
          background: `linear-gradient(135deg, ${p.color}cc, ${p.color}66)`,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: isMobile ? 15 : 22, fontWeight: 600, color: "#fff",
          boxShadow: `0 4px 16px ${p.color}40`, border: `2px solid ${p.color}44`,
          transform: isActive ? "scale(1.07)" : "scale(1)", transition: "transform .2s",
        }}>
          {p.initials}
        </div>
        {isActive && (
          <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 13 }}>
            {[1.2, 1.8, 1, 1.5, .8].map((h, i) => (
              <span key={i} style={{ display: "block", width: isMobile ? 2 : 3, borderRadius: 2, background: ACTIVE_CLR, height: `${h * (isMobile ? 6 : 9)}px`, animation: `wave ${.8 + i * .1}s ease-in-out infinite`, animationDelay: `${i * .12}s` }} />
            ))}
          </div>
        )}
      </div>

      {/* name bar */}
      <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, background: "linear-gradient(to top,rgba(0,0,0,.8) 0%,transparent 100%)", padding: isMobile ? "14px 7px 5px" : "24px 12px 10px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontSize: isMobile ? 10 : 13, fontWeight: 500, color: TEXT_PRI, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "72%" }}>
          {p.name}{p.isLocal ? " (You)" : ""}
        </span>
        <MicBadge speaking={isActive} isLocal={p.isLocal} small={isMobile} />
      </div>
    </div>
  );
}

function MicBadge({ speaking, isLocal, small }: { speaking: boolean; isLocal: boolean; small: boolean }) {
  const s = small ? 20 : 26;
  const i = small ? 10 : 13;
  if (isLocal) return null;
  return (
    <div style={{ width: s, height: s, borderRadius: "50%", background: speaking ? "rgba(138,180,248,.2)" : "rgba(234,67,53,.85)", border: speaking ? "1.5px solid rgba(138,180,248,.6)" : "none", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
      {speaking
        ? <svg width={i} height={i} viewBox="0 0 24 24" fill="none" stroke={ACTIVE_CLR} strokeWidth="2.5" strokeLinecap="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/><line x1="8" y1="22" x2="16" y2="22"/></svg>
        : <svg width={i} height={i} viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.5" strokeLinecap="round"><line x1="2" y1="2" x2="22" y2="22"/><path d="M18.89 13.23A7.12 7.12 0 0 0 19 12v-2"/><path d="M5 10v2a7 7 0 0 0 12 5"/><path d="M15 9.34V5a3 3 0 0 0-5.68-1.33"/><path d="M9 9v3a3 3 0 0 0 5.12 2.12"/><line x1="12" y1="19" x2="12" y2="22"/><line x1="8" y1="22" x2="16" y2="22"/></svg>
      }
    </div>
  );
}

// ── Reusable UI atoms ─────────────────────────────────────────────────────────
function Clock() {
  const [t, setT] = useState(new Date());
  useEffect(() => { const id = setInterval(() => setT(new Date()), 1000); return () => clearInterval(id); }, []);
  return <span style={{ fontSize: 13, color: TEXT_SEC, fontVariantNumeric: "tabular-nums", flexShrink: 0 }}>{t.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>;
}

function Divider() {
  return <div style={{ width: 1, height: 32, background: "#5f6368", margin: "0 4px", flexShrink: 0 }} />;
}

function PhoneOff() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
      <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07"/>
      <path d="M2 2l20 20"/>
      <path d="M10.84 6.06a19.73 19.73 0 0 1 9.09 3.86 2 2 0 0 1 .07 2.97l-2.28 2.28c-.39.39-1 .46-1.45.17L13 13"/>
      <path d="M9.75 9.75 7.27 7.27a1 1 0 0 0-1.45.17l-2.28 2.28a2 2 0 0 0 .33 2.97 19.61 19.61 0 0 0 2.88 1.83"/>
    </svg>
  );
}

// Icon button
function IBtn({ children, onClick, active, danger, label, badge, size = 48 }: { children: React.ReactNode; onClick?: () => void; active?: boolean; danger?: boolean; label?: string; badge?: string; size?: number }) {
  const [hov, setHov] = useState(false);
  return (
    <button
      title={label}
      onClick={onClick}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        position: "relative", width: size, height: size, borderRadius: "50%", border: "none",
        background: danger ? "rgba(234,67,53,.9)" : active ? "rgba(138,180,248,.18)" : hov ? "rgba(255,255,255,.08)" : "transparent",
        color: danger ? "#fff" : active ? ACTIVE_CLR : TEXT_PRI,
        cursor: onClick ? "pointer" : "default",
        display: "flex", alignItems: "center", justifyContent: "center",
        transition: "background .15s, transform .1s",
        transform: hov && onClick ? "scale(1.06)" : "scale(1)",
        flexShrink: 0,
      }}
    >
      <svg width={Math.round(size * 0.42)} height={Math.round(size * 0.42)} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        {children}
      </svg>
      {badge && (
        <span style={{ position: "absolute", top: 6, right: 6, background: ACTIVE_CLR, color: MEET_BG, borderRadius: 99, fontSize: 9, fontWeight: 700, minWidth: 14, height: 14, lineHeight: "14px", textAlign: "center", padding: "0 2px" }}>
          {badge}
        </span>
      )}
    </button>
  );
}

// Pill button (end call / join)
function PillBtn({ children, onClick, color, disabled }: { children: React.ReactNode; onClick?: () => void; color: string; disabled?: boolean }) {
  const [hov, setHov] = useState(false);
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        height: 48, padding: "0 20px", borderRadius: 99, border: "none",
        background: color, color: "#fff", cursor: disabled ? "wait" : "pointer",
        display: "flex", alignItems: "center", gap: 7,
        fontSize: 13, fontWeight: 600, flexShrink: 0,
        transition: "filter .15s", filter: hov && !disabled ? "brightness(1.15)" : "brightness(1)",
        opacity: disabled ? .7 : 1,
      }}
    >
      {children}
    </button>
  );
}

// ── Chat inner ────────────────────────────────────────────────────────────────
function ChatInner({ messages, input, setInput, connected, displayName, setMessages, chatEndRef, onClose }: any) {
  const { send } = useDataChannel("chat");

  const sendMsg = useCallback(() => {
    const t = input.trim();
    if (!t || !connected) return;
    setMessages((p: any) => [...p, { id: `u-${Date.now()}`, from: "user", text: t, ts: Date.now() }]);
    send(new TextEncoder().encode(JSON.stringify({ type: "text", text: t })), { reliable: true, topic: "chat" }).catch(console.error);
    setInput("");
  }, [input, connected, send, setMessages, setInput]);

  return (
    <>
      <PanelHeader title="In-call messages" onClose={onClose} />
      <div style={{ flex: 1, overflowY: "auto", padding: "12px 16px", display: "flex", flexDirection: "column", gap: 10, WebkitOverflowScrolling: "touch" } as React.CSSProperties}>
        {messages.length === 0 && (
          <p style={{ textAlign: "center", color: TEXT_SEC, fontSize: 13, marginTop: 40, lineHeight: 1.6 }}>No messages yet.<br />Start the conversation!</p>
        )}
        {messages.map((m: ChatMessage) => (
          <div key={m.id} style={{ display: "flex", flexDirection: "column", gap: 3, animation: "fadeUp .2s ease" }}>
            <span style={{ fontSize: 11, color: TEXT_SEC, fontWeight: 500 }}>
              {m.from === "user" ? displayName : m.from === "agent" ? m.agentName || "Agent" : "System"}
              <span style={{ marginLeft: 6, fontWeight: 400 }}>{new Date(m.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
            </span>
            <div style={{ fontSize: 13, lineHeight: 1.5, color: m.from === "system" ? TEXT_SEC : TEXT_PRI, background: m.from === "user" ? "rgba(138,180,248,.12)" : "rgba(255,255,255,.04)", borderRadius: 8, padding: "8px 12px", borderLeft: m.from === "agent" ? `2px solid ${ACTIVE_CLR}` : "none" }}>
              {m.text}
            </div>
          </div>
        ))}
        <div ref={chatEndRef} />
      </div>
      <div style={{ padding: 12, borderTop: "1px solid rgba(255,255,255,.06)" }}>
        <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMsg(); } }}
            placeholder={connected ? "Send a message…" : "Join to chat"}
            disabled={!connected}
            rows={2}
            style={{ flex: 1, borderRadius: 8, border: "1px solid rgba(255,255,255,.1)", background: "rgba(255,255,255,.06)", color: TEXT_PRI, fontSize: 14, padding: "10px 12px", resize: "none", outline: "none", opacity: connected ? 1 : .5 }}
          />
          <button
            onClick={sendMsg}
            disabled={!connected || !input.trim()}
            style={{ width: 44, height: 44, borderRadius: "50%", border: "none", background: connected && input.trim() ? "#4285f4" : "rgba(255,255,255,.08)", color: "#fff", cursor: connected && input.trim() ? "pointer" : "default", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, transition: "background .15s" }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
          </button>
        </div>
      </div>
    </>
  );
}

// ── Settings inner ────────────────────────────────────────────────────────────
function SettingsInner({ displayName, setDisplayName, connected, connect, disconnect, connectionState, onClose }: any) {
  return (
    <>
      <PanelHeader title="Connection" onClose={onClose} />
      <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 16 }}>
        <div>
          <label style={{ fontSize: 12, color: TEXT_SEC, display: "block", marginBottom: 7 }}>Display name</label>
          <input
            value={displayName}
            onChange={e => setDisplayName(e.target.value)}
            style={{ width: "100%", borderRadius: 8, border: "1px solid rgba(255,255,255,.15)", background: "rgba(255,255,255,.06)", color: TEXT_PRI, fontSize: 15, padding: "11px 13px", outline: "none" }}
            placeholder="Your name"
          />
        </div>
        <div style={{ padding: "12px 14px", borderRadius: 8, background: connected ? "rgba(52,168,83,.1)" : "rgba(255,255,255,.04)", border: `1px solid ${connected ? "rgba(52,168,83,.3)" : "rgba(255,255,255,.08)"}`, fontSize: 13, color: connected ? "#81c995" : TEXT_SEC, display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ width: 8, height: 8, borderRadius: "50%", background: connected ? "#34a853" : "#9aa0a6", flexShrink: 0, boxShadow: connected ? "0 0 6px #34a853" : "none" }} />
          {connected ? "Connected to room" : connectionState === "connecting" ? "Connecting…" : "Not connected"}
        </div>
        {connected ? (
          <button onClick={disconnect} style={{ width: "100%", padding: "13px 0", borderRadius: 10, border: "none", background: "rgba(234,67,53,.15)", color: "#f28b82", outline: "1px solid rgba(234,67,53,.3)", fontSize: 15, fontWeight: 500, cursor: "pointer" }}>
            Leave room
          </button>
        ) : (
          <button onClick={connect} disabled={connectionState === "connecting"} style={{ width: "100%", padding: "13px 0", borderRadius: 10, border: "none", background: "linear-gradient(135deg,#4285f4,#34a853)", color: "#fff", fontSize: 15, fontWeight: 600, cursor: connectionState === "connecting" ? "wait" : "pointer", opacity: connectionState === "connecting" ? .6 : 1 }}>
            {connectionState === "connecting" ? "Joining…" : "Join room"}
          </button>
        )}
      </div>
    </>
  );
}

function PanelHeader({ title, onClose }: { title: string; onClose: () => void }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "15px 16px 12px", borderBottom: "1px solid rgba(255,255,255,.06)", flexShrink: 0 }}>
      <span style={{ fontSize: 15, fontWeight: 500 }}>{title}</span>
      <button onClick={onClose} style={{ background: "none", border: "none", color: TEXT_SEC, cursor: "pointer", padding: 8, borderRadius: "50%", display: "flex", transition: "background .15s" }}
        onMouseEnter={e => (e.currentTarget.style.background = "rgba(255,255,255,.08)")}
        onMouseLeave={e => (e.currentTarget.style.background = "none")}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
      </button>
    </div>
  );
}

// ── Data channel handler ──────────────────────────────────────────────────────
function DataChannelHandler({ setMessages, setRawEvents, setImageStatus }: any) {
  useDataChannel("chat", (msg) => {
    try {
      const data = JSON.parse(new TextDecoder().decode(msg.payload));
      if (data.type === "turn_complete") return;

      let text: string | null = null;
      let from: "agent" | "system" | "user" = "agent";

      if (data.type === "text_chunk" && !data.partial)         text = data.text;
      else if (data.type === "transcription" && data.finished) { text = data.text; from = data.role === "user" ? "user" : "agent"; }
      else if (data.type === "system")                         { text = data.text; from = "system"; }
      else if (data.type === "routing")                        { text = `[Routing] ${data.note}`; from = "system"; }
      if (data.type === "image_ready")                         { setImageStatus("Ready: " + data.path); text = `Image ready: ${data.path}`; from = "system"; }

      if (text) {
        const id = data.agent_id as string;
        const agentName = id === "mark" ? "Mark" : id === "scientist" ? "Dr. Nova" : id === "historian" ? "Prof. Lex" : "Agent";
        setMessages((p: any) => [...p, { id: `msg-${Date.now()}-${p.length}`, from, text, ts: Date.now(), agentName }]);
      }
      setRawEvents((p: any) => { const n = [...p, JSON.stringify(data)]; if (n.length > 200) n.shift(); return n; });
    } catch {}
  });
  return null;
}
