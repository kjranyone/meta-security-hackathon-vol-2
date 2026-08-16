import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import MapCanvas from "../components/MapCanvas";
import StatsTable from "../components/StatsTable";
import EventFeed from "../components/EventFeed";
import GodBar from "../components/GodBar";
import GodCards from "../components/GodCards";
import { VSplit } from "../components/Splitter";
import CreateWorldDialog from "../components/CreateWorldDialog";
import DateBar from "../components/DateBar";
import Toasts, { useToasts } from "../components/Toasts";
import LegendModal from "../components/LegendModal";
import { loadGeojson } from "../lib/geo";
import { pickAt } from "../lib/renderMap";
import { initAudio, beep, toneForTypes, MAJOR_TONES } from "../lib/audio";

export default function GodApp() {
  const [geo, setGeo] = useState(null);
  const [meta, setMeta] = useState(null);
  const [ticks, setTicks] = useState([]);
  const [godEvents, setGodEvents] = useState([]);
  const [cur, setCur] = useState(0);
  const [sel, setSel] = useState({ kind: null, id: null });
  const [status, setStatus] = useState({ running: false, tick: 0, max_ticks: 60 });
  const [muted, setMuted] = useState(false);
  const [flash, setFlash] = useState(0);
  const [sideW, setSideW] = useState(480);
  const [sideTab, setSideTab] = useState("cards");
  const [unread, setUnread] = useState(0);
  const sideTabRef = useRef("cards");
  useEffect(() => { sideTabRef.current = sideTab; }, [sideTab]);

  const eventLog = useMemo(() => ticks.flatMap(t => t.events || []).slice(-300), [ticks]);
  const openTab = t => { setSideTab(t); if (t === "event") setUnread(0); };
  const [preset, setPreset] = useState("earth");
  const [policy, setPolicy] = useState("mock_llm");
  const [seed, setSeed] = useState(42);
  const [rlNation, setRlNation] = useState("");
  const [conn, setConn] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [legendOpen, setLegendOpen] = useState(false);
  const { toasts, push: pushToast } = useToasts();
  const wsRef = useRef(null);
  const tlRef = useRef(null);

  useEffect(() => {
    if (!flash) return;
    const el = tlRef.current;
    if (!el) return;
    el.classList.remove("flashgod");
    void el.offsetWidth;
    el.classList.add("flashgod");
  }, [flash]);

  useEffect(() => { loadGeojson().then(setGeo).catch(console.error); }, []);

  const send = useCallback(obj => {
    if (wsRef.current && wsRef.current.readyState === 1)
      wsRef.current.send(JSON.stringify(obj));
  }, []);

  const intervene = useCallback((type, params) =>
    send({ cmd: "intervene", type, params: params || {} }), [send]);

  const feedback = useCallback(types => {
    setFlash(f => f + 1);
    if (!muted) beep(toneForTypes(types));
  }, [muted]);

  useEffect(() => {
    let ws;
    let closed = false;
    const connect = () => {
      ws = new WebSocket(`ws://${location.host}/ws`);
      wsRef.current = ws;
      ws.onopen = () => setConn(true);
      ws.onmessage = ev => {
        const m = JSON.parse(ev.data);
        if (m.type === "meta") {
          setMeta(m); setTicks([]); setGodEvents([]); setCur(0);
        } else if (m.type === "tick") {
          setTicks(t => [...t, m]);
          if ((m.events || []).length && sideTabRef.current !== "event")
            setUnread(u => Math.min(99, u + m.events.length));
          const majors = (m.events || []).filter(e => MAJOR_TONES[e.type]);
          if (majors.length) {
            feedback(majors.map(e => e.type));
            majors.slice(0, 2).forEach(e => pushToast(e.type, e.text));
          }
        } else if (m.type === "god") {
          if (m.event) {
            setGodEvents(g => [...g, m.event]);
            feedback(["god_intervention"]);
            pushToast("god_intervention", m.event.text);
          }
        } else if (m.type === "status") {
          setStatus({ running: m.running, tick: m.tick, max_ticks: m.max_ticks });
        }
      };
      ws.onclose = () => { setConn(false); if (!closed) setTimeout(connect, 1500); };
    };
    connect();
    return () => { closed = true; ws?.close(); };
  }, [feedback]);

  useEffect(() => {
    const once = () => initAudio();
    document.addEventListener("click", once, { once: true });
    return () => document.removeEventListener("click", once);
  }, []);

  // ライブシミュレーション: 常に最新tickを表示
  useEffect(() => { setCur(ticks.length - 1); }, [ticks.length]);

  async function resetWorld() {
    const body = {
      preset: preset === "gen" ? "default" : preset, policy,
      seed: +seed || 42, ticks: 60,
    };
    if (preset === "gen") body.gen_seed = 7;
    if (rlNation.trim()) body.rl_nation = rlNation.trim();
    await fetch("/api/reset", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    setSel({ kind: null, id: null });
  }

  function onMapClick(mx, my) {
    if (!geo || !meta) return;
    const picked = pickAt(mx, my, geo, meta);
    setSel(picked);
    if (picked.kind) openTab("cards");
  }

  const tick = ticks[Math.min(cur, ticks.length - 1)] || null;
  const counts = {};
  for (const t of ticks) for (const e of t.events || []) counts[e.type] = (counts[e.type] || 0) + 1;
  const countsStr = Object.entries(counts).map(([k, v]) => `${k}:${v}`).join(" ");

  return (
    <div className="app">
      <header>
        <h1>👑 Geopolitics Terrarium — 神の玉座</h1>
        <span id="conn" className={conn ? "ok" : "bad"}>{conn ? "接続中" : "切断"}</span>
        <span className="spacer" />
        <button onClick={() => setCreateOpen(true)}>🌍 世界を創る</button>
        <button className="helpbtn" onClick={() => setLegendOpen(true)}>?</button>
      </header>

      {legendOpen && <LegendModal onClose={() => setLegendOpen(false)} />}

      <CreateWorldDialog open={createOpen} preset={preset} policy={policy} seed={seed}
                         rlNation={rlNation} onPreset={setPreset} onPolicy={setPolicy}
                         onSeed={setSeed} onRlNation={setRlNation}
                         onCreate={resetWorld} onClose={() => setCreateOpen(false)} />

      <div className="main">
        <Toasts toasts={toasts} />
        <MapCanvas tick={tick} geo={geo} meta={meta} god
                   selectedNation={sel.kind === "nation" ? sel.id : null}
                   selectedChokepoint={sel.kind === "cp" ? sel.id : null}
                   onMapClick={onMapClick} />
        <GodBar sel={sel} meta={meta} intervene={intervene} />

        <VSplit
          onMove={ev => setSideW(Math.min(Math.max(window.innerWidth - ev.clientX, 320), window.innerWidth - 420))}
          onReset={() => setSideW(480)} />
        <div className="side" style={{ width: sideW }}>
          <div className="sidetabs">
            <div className={`sidetab${sideTab === "cards" ? " on" : ""}`} onClick={() => openTab("cards")}>⚡ 介入</div>
            <div className={`sidetab${sideTab === "nations" ? " on" : ""}`} onClick={() => openTab("nations")}>👥 NATIONS</div>
            <div className={`sidetab${sideTab === "event" ? " on" : ""}`} onClick={() => openTab("event")}>
              📜 EVENT{unread > 0 && <span className="badge">{unread}</span>}
            </div>
          </div>
          {sideTab === "cards" && (
            <div className="pane" style={{ flex: 1, overflow: "auto" }}>
              <GodCards sel={sel} meta={meta} tick={tick} intervene={intervene} />
            </div>
          )}
          {sideTab === "nations" && (
            <div className="pane" style={{ flex: 1, overflow: "auto" }}>
              <StatsTable tick={tick} selected={sel.kind === "nation" ? sel.id : null}
                          onSelect={nid => setSel(s => (s.kind === "nation" && s.id === nid) ? { kind: null, id: null } : { kind: "nation", id: nid })} />
            </div>
          )}
          {sideTab === "event" && (
            <EventFeed events={eventLog} godEvents={godEvents} counts={countsStr} />
          )}
        </div>
      </div>

      <div className="timeline" ref={tlRef}>
        <button className="tlbtn" onClick={() => send({ cmd: status.running ? "pause" : "play" })}>
          {status.running ? "⏸ 停止" : "▶ 再生"}
        </button>
        <button className="tlbtn" onClick={() => send({ cmd: "step" })}>⏭ 1tick</button>
        <DateBar tick={status.tick} suffix={` / ${status.max_ticks} ${status.running ? "▶" : "⏸"}`} />
        <label className="speedlabel" style={{ flex: 1 }}><span>速度</span>
          <input type="range" min="200" max="3000" defaultValue="1200"
                 onChange={e => send({ cmd: "speed", ms: +e.target.value })} />
          <output>ms</output>
        </label>
        <button className="tlbtn mutebtn" onClick={() => { initAudio(); setMuted(m => !m); }}>
          {muted ? "🔇" : "🔊"}
        </button>
      </div>
    </div>
  );
}
