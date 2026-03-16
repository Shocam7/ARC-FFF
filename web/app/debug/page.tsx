"use client";

/**
 * LiveKit Room Inspector — drop this into web/app/debug/page.tsx
 * Visit http://localhost:3000/debug to use it.
 *
 * What it shows:
 *  • Every participant in the room (local + remote) with their identity & connection quality
 *  • Every data channel packet on EVERY topic — raw hex + decoded JSON
 *  • One-click test payloads to probe whether your web→PyQt6 pipeline is alive
 *  • A manual send panel: custom topic + payload
 */

import {
  LiveKitRoom,
  RoomAudioRenderer,
  useDataChannel,
  useLocalParticipant,
  useParticipants,
  useRoomContext,
} from "@livekit/components-react";
import { ConnectionQuality } from "livekit-client";
import { useCallback, useEffect, useRef, useState } from "react";

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────
type Packet = {
  id: number;
  ts: number;
  direction: "rx" | "tx";
  topic: string;
  senderIdentity: string;
  rawHex: string;
  decoded: string | null;
  parseError: string | null;
  byteLength: number;
};

type ConnState = "idle" | "connecting" | "connected" | "error";

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────
let packetCounter = 0;
const toHex = (buf: Uint8Array) =>
  Array.from(buf.slice(0, 64))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join(" ") + (buf.length > 64 ? " …" : "");

const tryDecode = (buf: Uint8Array): { decoded: string | null; parseError: string | null } => {
  try {
    const str = new TextDecoder().decode(buf);
    JSON.parse(str); // validate
    return { decoded: str, parseError: null };
  } catch (e: any) {
    try {
      const str = new TextDecoder().decode(buf);
      return { decoded: str, parseError: "Not valid JSON" };
    } catch {
      return { decoded: null, parseError: "Binary / non-UTF8" };
    }
  }
};

const qualityLabel = (q: ConnectionQuality) => {
  switch (q) {
    case ConnectionQuality.Excellent: return { label: "Excellent", color: "#4ade80" };
    case ConnectionQuality.Good:      return { label: "Good",      color: "#a3e635" };
    case ConnectionQuality.Poor:      return { label: "Poor",      color: "#fb923c" };
    default:                          return { label: "Unknown",   color: "#94a3b8" };
  }
};

const QUICK_PROBES = [
  { label: "Echo ping", topic: "chat", payload: JSON.stringify({ type: "ping", from: "inspector", ts: Date.now() }) },
  { label: "Text msg (chat topic)", topic: "chat", payload: JSON.stringify({ type: "text", text: "Hello from LiveKit Inspector" }) },
  { label: "Text msg (message topic)", topic: "message", payload: JSON.stringify({ type: "text", text: "Hello from LiveKit Inspector" }) },
  { label: "Raw text (no topic)", topic: "", payload: "hello world" },
];

// ─────────────────────────────────────────────────────────────────────────────
// Main page
// ─────────────────────────────────────────────────────────────────────────────
export default function DebugPage() {
  const [token, setToken] = useState<string | null>(null);
  const [connState, setConnState] = useState<ConnState>("idle");
  const [connError, setConnError] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState("inspector");
  const [room, setRoom] = useState("bidi-demo-room");

  const connect = useCallback(async () => {
    setConnState("connecting");
    setConnError(null);
    try {
      const res = await fetch(
        `/api/livekit?room=${encodeURIComponent(room)}&username=${encodeURIComponent(displayName)}`
      );
      const data = await res.json();
      if (!data.token) throw new Error(data.error ?? "No token returned");
      setToken(data.token);
    } catch (e: any) {
      setConnError(e.message);
      setConnState("error");
    }
  }, [room, displayName]);

  const disconnect = useCallback(() => {
    setToken(null);
    setConnState("idle");
  }, []);

  return (
    <div style={css.page}>
      {/* ── Header ── */}
      <header style={css.header}>
        <div style={css.headerLeft}>
          <span style={css.headerIcon}>⬡</span>
          <div>
            <div style={css.title}>LiveKit Room Inspector</div>
            <div style={css.subtitle}>
              Full-spectrum data-channel sniffer · all topics · all participants
            </div>
          </div>
        </div>
        <div style={css.connBadge(connState)}>{connState.toUpperCase()}</div>
      </header>

      {/* ── Connect panel ── */}
      {connState !== "connected" && (
        <div style={css.connectPanel}>
          <div style={css.connectRow}>
            <label style={css.fieldLabel}>Room</label>
            <input
              style={css.input}
              value={room}
              onChange={(e) => setRoom(e.target.value)}
              placeholder="bidi-demo-room"
            />
          </div>
          <div style={css.connectRow}>
            <label style={css.fieldLabel}>Identity</label>
            <input
              style={css.input}
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="inspector"
            />
          </div>
          <button
            style={css.connectBtn(connState === "connecting")}
            onClick={connect}
            disabled={connState === "connecting"}
          >
            {connState === "connecting" ? "Connecting…" : "⬡  Join Room"}
          </button>
          {connError && <div style={css.errorBox}>{connError}</div>}
          <div style={css.hint}>
            Make sure <code>LIVEKIT_API_KEY</code> + <code>LIVEKIT_API_SECRET</code> are set in{" "}
            <code>.env.local</code> and that <code>NEXT_PUBLIC_LIVEKIT_URL</code> points to your
            LiveKit server.
          </div>
        </div>
      )}

      {/* ── Room view (only mounts when token present) ── */}
      {token && (
        <LiveKitRoom
          serverUrl={process.env.NEXT_PUBLIC_LIVEKIT_URL ?? "wss://arc-m0wlbys4.livekit.cloud"}
          token={token}
          connect
          audio={false}
          video={false}
          onConnected={() => setConnState("connected")}
          onDisconnected={disconnect}
        >
          <RoomAudioRenderer />
          <RoomInspector onDisconnect={disconnect} />
        </LiveKitRoom>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Inner room component (has access to LiveKit context)
// ─────────────────────────────────────────────────────────────────────────────
function RoomInspector({ onDisconnect }: { onDisconnect: () => void }) {
  const [packets, setPackets] = useState<Packet[]>([]);
  const [paused, setPaused] = useState(false);
  const [filterTopic, setFilterTopic] = useState("");
  const [customTopic, setCustomTopic] = useState("chat");
  const [customPayload, setCustomPayload] = useState(
    JSON.stringify({ type: "text", text: "hello from inspector" }, null, 2)
  );
  const [sendLog, setSendLog] = useState<string[]>([]);
  const logEndRef = useRef<HTMLDivElement>(null);
  const participants = useParticipants();
  const { localParticipant } = useLocalParticipant();
  const room = useRoomContext();

  // ── Listen on ALL topics (pass undefined / no topic to catch everything) ──
  // @livekit/components-react: omitting the topic param catches all topics.
  useDataChannel(undefined as any, (msg) => {
    if (paused) return;
    const { decoded, parseError } = tryDecode(msg.payload);
    const p: Packet = {
      id: packetCounter++,
      ts: Date.now(),
      direction: "rx",
      topic: (msg as any).topic ?? "(none)",
      senderIdentity: msg.from?.identity ?? "(unknown)",
      rawHex: toHex(msg.payload),
      decoded,
      parseError,
      byteLength: msg.payload.byteLength,
    };
    setPackets((prev) => [p, ...prev].slice(0, 500));
  });

  // Auto-scroll send log
  useEffect(() => {
    if (logEndRef.current) logEndRef.current.scrollIntoView({ behavior: "smooth" });
  }, [sendLog]);

  // ── Send helpers ──
  const { send: sendChat } = useDataChannel("chat");

  const sendPacket = useCallback(
    async (topic: string, payload: string) => {
      const encoded = new TextEncoder().encode(payload);
      const ts = new Date().toLocaleTimeString();
      try {
        // LiveKit DataChannel send: we must publish via localParticipant.publishData
        await room.localParticipant.publishData(encoded, {
          reliable: true,
          topic: topic || undefined,
        });
        const echo: Packet = {
          id: packetCounter++,
          ts: Date.now(),
          direction: "tx",
          topic: topic || "(none)",
          senderIdentity: localParticipant?.identity ?? "local",
          rawHex: toHex(encoded),
          decoded: payload,
          parseError: null,
          byteLength: encoded.byteLength,
        };
        setPackets((prev) => [echo, ...prev].slice(0, 500));
        setSendLog((prev) => [...prev, `[${ts}] ✓ Sent ${encoded.byteLength}B on topic "${topic || "(none)"}" — ${payload.slice(0, 80)}`]);
      } catch (e: any) {
        setSendLog((prev) => [...prev, `[${ts}] ✗ FAILED on topic "${topic}": ${e.message}`]);
      }
    },
    [room, localParticipant]
  );

  const visiblePackets = filterTopic
    ? packets.filter((p) => p.topic.toLowerCase().includes(filterTopic.toLowerCase()))
    : packets;

  return (
    <div style={css.inspector}>
      {/* ── Participants strip ── */}
      <section style={css.section}>
        <div style={css.sectionHeader}>
          <span style={css.sectionLabel}>PARTICIPANTS</span>
          <span style={css.badge}>{participants.length}</span>
          <button style={css.leaveBtn} onClick={onDisconnect}>Leave</button>
        </div>
        <div style={css.participantRow}>
          {participants.map((p) => {
            const q = qualityLabel(p.connectionQuality);
            const isLocal = p.identity === localParticipant?.identity;
            return (
              <div key={p.identity} style={css.participantChip(isLocal)}>
                <span style={{ ...css.qualityDot, background: q.color }} />
                <span style={css.participantName}>{p.identity}</span>
                {isLocal && <span style={css.youBadge}>you</span>}
                <span style={{ ...css.qualityLabel_, color: q.color }}>{q.label}</span>
              </div>
            );
          })}
          {participants.length === 0 && (
            <span style={css.dimText}>No other participants yet</span>
          )}
        </div>
      </section>

      <div style={css.twoCol}>
        {/* ── Left: packet log ── */}
        <section style={{ ...css.section, flex: "1 1 0", minWidth: 0 }}>
          <div style={css.sectionHeader}>
            <span style={css.sectionLabel}>DATA CHANNEL LOG</span>
            <span style={css.badge}>{packets.length}</span>
            <input
              style={{ ...css.input, width: 140, fontSize: "0.7rem", padding: "0.2rem 0.5rem" }}
              placeholder="filter topic…"
              value={filterTopic}
              onChange={(e) => setFilterTopic(e.target.value)}
            />
            <button
              style={{ ...css.leaveBtn, color: paused ? "#fb923c" : "#94a3b8" }}
              onClick={() => setPaused((v) => !v)}
            >
              {paused ? "▶ Resume" : "⏸ Pause"}
            </button>
            <button style={css.leaveBtn} onClick={() => setPackets([])}>
              Clear
            </button>
          </div>

          <div style={css.packetLog}>
            {visiblePackets.length === 0 && (
              <div style={css.emptyLog}>
                Waiting for data channel packets…
                <br />
                <span style={{ color: "#64748b", fontSize: "0.7rem" }}>
                  Send a message from the web UI or PyQt6 app and it will appear here.
                </span>
              </div>
            )}
            {visiblePackets.map((p) => (
              <PacketRow key={p.id} packet={p} />
            ))}
          </div>
        </section>

        {/* ── Right: send panel ── */}
        <section style={{ ...css.section, flex: "0 0 340px" }}>
          <div style={css.sectionHeader}>
            <span style={css.sectionLabel}>SEND PROBE</span>
          </div>

          {/* Quick probes */}
          <div style={{ marginBottom: "0.75rem" }}>
            <div style={css.dimText}>Quick probes</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem", marginTop: "0.4rem" }}>
              {QUICK_PROBES.map((probe) => (
                <button
                  key={probe.label}
                  style={css.probeBtn}
                  onClick={() => sendPacket(probe.topic, probe.payload)}
                >
                  {probe.label}
                </button>
              ))}
            </div>
          </div>

          {/* Custom send */}
          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            <div>
              <div style={css.dimText}>Topic (empty = no topic)</div>
              <input
                style={{ ...css.input, marginTop: "0.25rem", width: "100%" }}
                value={customTopic}
                onChange={(e) => setCustomTopic(e.target.value)}
                placeholder="chat"
              />
            </div>
            <div>
              <div style={css.dimText}>Payload</div>
              <textarea
                style={{ ...css.input, marginTop: "0.25rem", width: "100%", minHeight: 90, resize: "vertical", fontFamily: "monospace", fontSize: "0.72rem" }}
                value={customPayload}
                onChange={(e) => setCustomPayload(e.target.value)}
              />
            </div>
            <button
              style={css.connectBtn(false)}
              onClick={() => sendPacket(customTopic, customPayload)}
            >
              ↑ Send
            </button>
          </div>

          {/* Send log */}
          <div style={{ marginTop: "0.75rem" }}>
            <div style={css.dimText}>Send log</div>
            <div style={{ ...css.packetLog, maxHeight: 140, marginTop: "0.4rem" }}>
              {sendLog.map((l, i) => (
                <div key={i} style={{ color: l.includes("✗") ? "#f87171" : "#4ade80", padding: "0.1rem 0", fontSize: "0.68rem", fontFamily: "monospace" }}>
                  {l}
                </div>
              ))}
              <div ref={logEndRef} />
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Packet row
// ─────────────────────────────────────────────────────────────────────────────
function PacketRow({ packet: p }: { packet: Packet }) {
  const [expanded, setExpanded] = useState(false);
  const dir = p.direction === "tx";

  return (
    <div
      style={css.packetRow(dir)}
      onClick={() => setExpanded((v) => !v)}
    >
      <div style={css.packetMeta}>
        <span style={css.dirBadge(dir)}>{p.direction.toUpperCase()}</span>
        <span style={css.topicBadge}>{p.topic}</span>
        <span style={css.dimText}>{p.senderIdentity}</span>
        <span style={{ ...css.dimText, marginLeft: "auto" }}>
          {p.byteLength}B · {new Date(p.ts).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
        </span>
      </div>
      {p.decoded && (
        <div style={css.decodedPreview}>
          {expanded ? p.decoded : p.decoded.slice(0, 120) + (p.decoded.length > 120 ? "…" : "")}
        </div>
      )}
      {p.parseError && !p.decoded && (
        <div style={{ color: "#fb923c", fontSize: "0.65rem", fontFamily: "monospace" }}>
          {p.parseError} · hex: {p.rawHex}
        </div>
      )}
      {expanded && (
        <div style={css.hexRow}>{p.rawHex}</div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Inline styles (keeps this a single-file drop-in)
// ─────────────────────────────────────────────────────────────────────────────
const css = {
  page: {
    minHeight: "100vh",
    background: "#060a12",
    color: "#c9d1d9",
    fontFamily: '"JetBrains Mono", "Fira Code", ui-monospace, monospace',
    padding: "1.5rem",
    display: "flex",
    flexDirection: "column" as const,
    gap: "1.25rem",
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    borderBottom: "1px solid #1e293b",
    paddingBottom: "1rem",
  },
  headerLeft: {
    display: "flex",
    alignItems: "center",
    gap: "0.75rem",
  },
  headerIcon: {
    fontSize: "2rem",
    background: "linear-gradient(135deg, #22d3ee, #818cf8)",
    WebkitBackgroundClip: "text",
    WebkitTextFillColor: "transparent",
  },
  title: {
    fontSize: "1.15rem",
    fontWeight: 700,
    letterSpacing: "0.05em",
    color: "#e2e8f0",
  },
  subtitle: {
    fontSize: "0.72rem",
    color: "#475569",
    marginTop: "0.1rem",
  },
  connBadge: (state: ConnState) => ({
    padding: "0.25rem 0.7rem",
    borderRadius: "4px",
    fontSize: "0.65rem",
    fontWeight: 700,
    letterSpacing: "0.1em",
    background:
      state === "connected" ? "rgba(34,211,238,0.1)" :
      state === "connecting" ? "rgba(251,191,36,0.1)" :
      state === "error" ? "rgba(248,113,113,0.1)" :
      "rgba(100,116,139,0.1)",
    color:
      state === "connected" ? "#22d3ee" :
      state === "connecting" ? "#fbbf24" :
      state === "error" ? "#f87171" :
      "#64748b",
    border: `1px solid ${
      state === "connected" ? "#22d3ee40" :
      state === "connecting" ? "#fbbf2440" :
      state === "error" ? "#f8717140" :
      "#64748b40"
    }`,
  }),
  connectPanel: {
    maxWidth: 480,
    display: "flex",
    flexDirection: "column" as const,
    gap: "0.75rem",
    background: "#0d1520",
    border: "1px solid #1e293b",
    borderRadius: "8px",
    padding: "1.25rem",
  },
  connectRow: {
    display: "flex",
    flexDirection: "column" as const,
    gap: "0.25rem",
  },
  fieldLabel: {
    fontSize: "0.68rem",
    color: "#64748b",
    textTransform: "uppercase" as const,
    letterSpacing: "0.08em",
  },
  input: {
    background: "#0a0f1a",
    border: "1px solid #1e293b",
    borderRadius: "4px",
    color: "#c9d1d9",
    padding: "0.4rem 0.6rem",
    fontSize: "0.8rem",
    fontFamily: "inherit",
    outline: "none",
  } as React.CSSProperties,
  connectBtn: (loading: boolean) => ({
    background: loading ? "#1e293b" : "linear-gradient(90deg, #22d3ee20, #818cf820)",
    border: "1px solid #22d3ee50",
    borderRadius: "4px",
    color: loading ? "#64748b" : "#22d3ee",
    padding: "0.5rem 1rem",
    fontSize: "0.8rem",
    fontFamily: "inherit",
    cursor: loading ? "not-allowed" : "pointer",
    fontWeight: 600,
    letterSpacing: "0.05em",
  } as React.CSSProperties),
  errorBox: {
    background: "rgba(248,113,113,0.08)",
    border: "1px solid #f8717140",
    borderRadius: "4px",
    color: "#f87171",
    fontSize: "0.75rem",
    padding: "0.4rem 0.6rem",
  },
  hint: {
    fontSize: "0.7rem",
    color: "#475569",
    lineHeight: 1.5,
  },
  inspector: {
    display: "flex",
    flexDirection: "column" as const,
    gap: "1rem",
  },
  section: {
    background: "#0d1520",
    border: "1px solid #1e293b",
    borderRadius: "8px",
    padding: "1rem",
    display: "flex",
    flexDirection: "column" as const,
    gap: "0.75rem",
  },
  sectionHeader: {
    display: "flex",
    alignItems: "center",
    gap: "0.5rem",
    flexWrap: "wrap" as const,
  },
  sectionLabel: {
    fontSize: "0.6rem",
    fontWeight: 700,
    letterSpacing: "0.15em",
    color: "#475569",
    textTransform: "uppercase" as const,
  },
  badge: {
    background: "#1e293b",
    color: "#94a3b8",
    borderRadius: "4px",
    padding: "0.05rem 0.4rem",
    fontSize: "0.65rem",
  },
  leaveBtn: {
    background: "none",
    border: "none",
    color: "#64748b",
    fontSize: "0.7rem",
    cursor: "pointer",
    fontFamily: "inherit",
    marginLeft: "auto",
    padding: 0,
  },
  participantRow: {
    display: "flex",
    flexWrap: "wrap" as const,
    gap: "0.5rem",
  },
  participantChip: (isLocal: boolean) => ({
    display: "flex",
    alignItems: "center",
    gap: "0.35rem",
    padding: "0.3rem 0.65rem",
    borderRadius: "4px",
    background: isLocal ? "rgba(129,140,248,0.08)" : "#0a0f1a",
    border: `1px solid ${isLocal ? "#818cf840" : "#1e293b"}`,
    fontSize: "0.75rem",
  } as React.CSSProperties),
  qualityDot: {
    width: 7,
    height: 7,
    borderRadius: "50%",
    flexShrink: 0,
  } as React.CSSProperties,
  participantName: {
    color: "#e2e8f0",
    fontWeight: 500,
  } as React.CSSProperties,
  youBadge: {
    fontSize: "0.55rem",
    background: "#818cf820",
    color: "#818cf8",
    border: "1px solid #818cf840",
    borderRadius: "3px",
    padding: "0.05rem 0.3rem",
    letterSpacing: "0.08em",
  } as React.CSSProperties,
  qualityLabel_: {
    fontSize: "0.6rem",
    marginLeft: "0.1rem",
  } as React.CSSProperties,
  dimText: {
    fontSize: "0.68rem",
    color: "#475569",
  } as React.CSSProperties,
  twoCol: {
    display: "flex",
    gap: "1rem",
    alignItems: "flex-start",
    flexWrap: "wrap" as const,
  },
  packetLog: {
    background: "#060a12",
    border: "1px solid #1e293b",
    borderRadius: "6px",
    maxHeight: 480,
    overflowY: "auto" as const,
    display: "flex",
    flexDirection: "column" as const,
    gap: "1px",
  },
  emptyLog: {
    padding: "2rem",
    textAlign: "center" as const,
    color: "#334155",
    fontSize: "0.78rem",
    lineHeight: 1.7,
  },
  packetRow: (isTx: boolean) => ({
    padding: "0.45rem 0.6rem",
    cursor: "pointer",
    borderLeft: `2px solid ${isTx ? "#818cf8" : "#22d3ee"}`,
    background: isTx ? "rgba(129,140,248,0.04)" : "rgba(34,211,238,0.03)",
    transition: "background 0.1s",
  } as React.CSSProperties),
  packetMeta: {
    display: "flex",
    alignItems: "center",
    gap: "0.4rem",
    flexWrap: "wrap" as const,
  },
  dirBadge: (isTx: boolean) => ({
    fontSize: "0.55rem",
    fontWeight: 700,
    letterSpacing: "0.1em",
    padding: "0.05rem 0.3rem",
    borderRadius: "3px",
    background: isTx ? "rgba(129,140,248,0.15)" : "rgba(34,211,238,0.12)",
    color: isTx ? "#818cf8" : "#22d3ee",
    border: `1px solid ${isTx ? "#818cf840" : "#22d3ee40"}`,
  } as React.CSSProperties),
  topicBadge: {
    fontSize: "0.65rem",
    color: "#fbbf24",
    background: "rgba(251,191,36,0.06)",
    border: "1px solid rgba(251,191,36,0.2)",
    borderRadius: "3px",
    padding: "0.05rem 0.35rem",
  } as React.CSSProperties,
  decodedPreview: {
    marginTop: "0.25rem",
    fontSize: "0.68rem",
    color: "#94a3b8",
    fontFamily: "monospace",
    wordBreak: "break-all" as const,
  },
  hexRow: {
    marginTop: "0.25rem",
    fontSize: "0.6rem",
    color: "#334155",
    fontFamily: "monospace",
    wordBreak: "break-all" as const,
    letterSpacing: "0.05em",
  },
  probeBtn: {
    background: "#0a0f1a",
    border: "1px solid #1e293b",
    borderRadius: "4px",
    color: "#94a3b8",
    fontSize: "0.68rem",
    padding: "0.25rem 0.6rem",
    cursor: "pointer",
    fontFamily: "inherit",
  } as React.CSSProperties,
};
