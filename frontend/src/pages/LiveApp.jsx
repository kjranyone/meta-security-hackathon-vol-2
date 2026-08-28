import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import MapCanvas from "../components/MapCanvas";
import StatsTable from "../components/StatsTable";
import EventFeed from "../components/EventFeed";
import GodBar from "../components/GodBar";
import InterveneModal from "../components/InterveneModal";
import NationDetail from "../components/NationDetail";
import { VSplit } from "../components/Splitter";
import CreateWorldDialog from "../components/CreateWorldDialog";
import DateBar from "../components/DateBar";
import Toasts, { useToasts } from "../components/Toasts";
import LegendModal from "../components/LegendModal";
import StatusModal from "../components/StatusModal";
import { loadGeojson } from "../lib/geo";
import { pickAt } from "../lib/renderMap";
import { eventsToPulses } from "../lib/pulses";
import { setClock } from "../lib/calendar";
import { initAudio, beep, toneForTypes, MAJOR_TONES } from "../lib/audio";

export default function LiveApp() {
  const [geo, setGeo] = useState(null);
  const [meta, setMeta] = useState(null);
  const [pulses, setPulses] = useState([]);
  const metaRef = useRef(null);
  const pulseResetRef = useRef(0);
  const [ticks, setTicks] = useState([]);
  const [godEvents, setGodEvents] = useState([]);
  const [cur, setCur] = useState(0);
  const [sel, setSel] = useState({ kind: null, id: null });
  const [status, setStatus] = useState({ running: false, tick: 0, max_ticks: 60 });
  const [muted, setMuted] = useState(false);
  const [flash, setFlash] = useState(0);
  const [sideW, setSideW] = useState(480);
  const [sideTab, setSideTab] = useState("nations");
  const [unread, setUnread] = useState(0);
  const sideTabRef = useRef("nations");
  useEffect(() => { sideTabRef.current = sideTab; }, [sideTab]);

  const eventLog = useMemo(() => ticks.flatMap(t => t.events || []).slice(-300), [ticks]);
  const openTab = t => { setSideTab(t); if (t === "event") setUnread(0); };
  const [preset, setPreset] = useState("earth");
  const [policy, setPolicy] = useState("rl");
  const [seed, setSeed] = useState(42);
  const [rlNation, setRlNation] = useState("");
  const [conn, setConn] = useState(false);
  const [boot, setBoot] = useState({ stage: "init", msg: "準備中…" });
  const [createOpen, setCreateOpen] = useState(false);
  const [ivModal, setIvModal] = useState(null);   // 開いている介入モーダルのaction
  const [legendOpen, setLegendOpen] = useState(false);
  const [statusOpen, setStatusOpen] = useState(false);
  const { toasts, push: pushToast } = useToasts();
  const wsRef = useRef(null);
  const tlRef = useRef(null);
  const statusRef = useRef(status);
  useEffect(() => { statusRef.current = status; }, [status]);

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
    if (wsRef.current) wsRef.current.postMessage(obj);
  }, []);

  const intervene = useCallback((type, params) =>
    send({ cmd: "intervene", type, params: params || {} }), [send]);

  const feedback = useCallback(types => {
    setFlash(f => f + 1);
    if (!muted) beep(toneForTypes(types));
  }, [muted]);

  useEffect(() => {
    const w = new Worker(new URL("../lib/live.worker.js", import.meta.url), { type: "module" });
    wsRef.current = w;
    const base = location.href.replace(/[^/]*$/, "");
    w.onmessage = ev => {
      const m = ev.data;
      if (m.type === "boot") { setBoot(m); return; }
      if (m.type === "booted") { setBoot(null); setConn(true); return; }
      if (m.type === "error") { pushToast("error", m.message); return; }
      if (m.type === "runresult") { window.__lastRun = m; return; }   // 検証用(パリティテスト)
      if (m.type === "meta") {
        metaRef.current = m;
        setMeta(m); setTicks([]); setGodEvents([]); setCur(0);
        setPulses([]); pulseResetRef.current++;
        setClock(m.clock?.hours_per_tick ?? 1);
        if (m.status) setStatus(s => ({ ...s, ...m.status }));
      } else if (m.type === "tick") {
        setTicks(t => [...t, m]);
        if ((m.events || []).length && sideTabRef.current !== "event")
          setUnread(u => Math.min(99, u + m.events.length));
        const ps = eventsToPulses(m.events || [], metaRef.current);
        if (ps.length) setPulses(ps);
        const majors = (m.events || []).filter(e => MAJOR_TONES[e.type]);
        if (majors.length) {
          feedback(majors.map(e => e.type));
          majors.slice(0, 2).forEach(e => pushToast(e.type, e.text));
        }
      } else if (m.type === "god") {
        if (m.event) {
          const gps = eventsToPulses([m.event], metaRef.current);
          if (gps.length) setPulses(gps);
          setGodEvents(g => [...g, m.event]);
          feedback(["god_intervention"]);
          pushToast("god_intervention", m.event.text);
        }
      } else if (m.type === "status") {
        setStatus({ running: m.running, tick: m.tick, max_ticks: m.max_ticks,
                    speed_ms: m.speed_ms, eff_ms: m.eff_ms, model: m.model });
      }
    };
    window.__liveSend = obj => w.postMessage(obj);   // 検証用フック
    w.postMessage({ cmd: "boot", base, world: "earth", seed: 42, ticks: 24 * 400, autoplay: true });
    return () => { w.terminate(); wsRef.current = null; };
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps


  // ライブシミュレーション: 常に最新tickを表示
  useEffect(() => { setCur(ticks.length - 1); }, [ticks.length]);

  function resetWorld() {
    // ブラウザ実行: サーバ不要。同じ学習モデル1本でseed/世界だけ差し替える
    send({ cmd: "reset", world: preset === "gen" ? "default" : preset,
           seed: +seed || 42, ticks: 24 * 400, autoplay: true });
    setSel({ kind: null, id: null });
  }

  function onMapClick(mx, my) {
    if (!geo || !meta) return;
    const picked = pickAt(mx, my, geo, meta);
    setSel(picked);
    if (picked.kind === "nation") openTab("nations");
  }

  const tick = ticks[Math.min(cur, ticks.length - 1)] || null;
  const counts = {};
  for (const t of ticks) for (const e of t.events || []) counts[e.type] = (counts[e.type] || 0) + 1;
  const countsStr = Object.entries(counts).map(([k, v]) => `${k}:${v}`).join(" ");

  return (
    <div className="app">
      {boot && (
        <div className="modal-back" style={{ zIndex: 50 }}>
          <div className="modal" style={{ textAlign: "center" }}>
            <h2>ブラウザでシミュレーションを起動中</h2>
            <p className="modalsub">{boot.msg}</p>
            {boot.stage === "weights" && (
              <div style={{ height: 6, background: "var(--bg)", borderRadius: 3, overflow: "hidden", margin: "10px 0" }}>
                <div style={{ width: `${boot.pct || 0}%`, height: "100%", background: "var(--accent)" }} />
              </div>
            )}
            <p style={{ fontSize: 12, color: "var(--dim)", marginTop: 8 }}>
              Python(WASM)ランタイム + 学習モデル(約50MB)を一度だけ読み込みます。
              以降はネットワークなしで、このページ内でエンジンと推論が完結します。
            </p>
          </div>
        </div>
      )}
      <header>
        <h1 onClick={() => setStatusOpen(true)}>Geopolitics Terrarium — 神の玉座(ブラウザ実行)</h1>
        <span id="conn" className={conn ? "ok" : "bad"} onClick={() => setStatusOpen(true)}
              title="状態と配備モデルを見る(ブラウザ内実行)">●</span>

        <span className="spacer" />
        <button onClick={() => setCreateOpen(true)}>世界を創る</button>
        <button onClick={() => setSel(s => (s.kind === "world" ? { kind: null, id: null } : { kind: "world", id: null }))}>世界</button>
        <button className="helpbtn" onClick={() => setLegendOpen(true)}>?</button>
      </header>



      <div className="main">
        <Toasts toasts={toasts} />
        <MapCanvas tick={tick} geo={geo} meta={meta} god pulses={pulses}
                   selectedNation={sel.kind === "nation" ? sel.id : null}
                   selectedChokepoint={sel.kind === "cp" ? sel.id : null}
                   onMapClick={onMapClick}>
      <CreateWorldDialog open={createOpen} preset={preset} policy={policy} seed={seed}
                         rlNation={rlNation} modelInfo={status.model} onPreset={setPreset} onPolicy={setPolicy}
                         policyLocked noGen
                         onSeed={setSeed} onRlNation={setRlNation}
                         onCreate={resetWorld} onClose={() => setCreateOpen(false)} />
      <InterveneModal action={ivModal}
                      target={sel.kind === "nation" ? (meta?.geo?.nations?.[sel.id]?.name || sel.id)
                                : sel.kind === "cp" ? sel.id : undefined}
                      onRun={(type, params) => {
                  if (type === "set_params") {
                    intervene("set_param", { nation: params.nation, param: "aggression", value: params.aggression });
                    intervene("set_param", { nation: params.nation, param: "paranoia", value: params.paranoia });
                  } else intervene(type, params);
                }}
                      onClose={() => setIvModal(null)} />
      {legendOpen && <LegendModal onClose={() => setLegendOpen(false)} />}
      {statusOpen && (
        <StatusModal onClose={() => setStatusOpen(false)} conn={conn} status={status} serverLabel="ブラウザ内で実行中(Pyodide WASM — ネットワーク不使用)"
                     tick={tick} meta={meta} preset={preset} policy={policy} seed={seed} />
      )}
        </MapCanvas>
        <GodBar sel={sel} meta={meta} intervene={intervene} onModal={setIvModal} />

        <VSplit
          onMove={ev => setSideW(Math.min(Math.max(window.innerWidth - ev.clientX, 320), window.innerWidth - 420))}
          onReset={() => setSideW(480)} />
        <div className="side" style={{ width: sideW }}>
          <div className="sidetabs">
            <div className={`sidetab${sideTab === "nations" ? " on" : ""}`} onClick={() => openTab("nations")}>NATIONS</div>
            <div className={`sidetab${sideTab === "event" ? " on" : ""}`} onClick={() => openTab("event")}>
              EVENT{unread > 0 && <span className="badge">{unread}</span>}
            </div>
          </div>
          {sideTab === "nations" && (
            <div className="pane" style={{ flex: 1, overflow: "auto" }}>
              {sel.kind === "nation" && tick?.nations?.[sel.id] && (
                <NationDetail n={tick.nations[sel.id]} meta={meta}
                              onSelect={nid => setSel({ kind: "nation", id: nid })} />
              )}
              <StatsTable tick={tick} selected={sel.kind === "nation" ? sel.id : null} showStocks
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
        <button className="tlbtn" onClick={() => send({ cmd: "step" })}
                title="停止中にシミュレーション時間で1時間だけ進める(介入の因果を少しずつ観察)">+1時間</button>
        <DateBar tick={status.tick} suffix={` / ${status.max_ticks} ${status.running ? "▶" : "⏸"}`} />
        <label className="speedlabel" style={{ flex: 1 }}><span>速度</span>
          <input type="range" min="30" max="3000" value={3030 - (status.speed_ms || 1200)}
                 onChange={e => send({ cmd: "speed", ms: 3030 - +e.target.value })} />
          <output title="推論はサーバCPUで走るため、要求速度に計算が追いつかない場合は実効値が下がる(世界サイズとマシン性能依存)">{(() => {
            const ms = status.speed_ms || 1200;
            const fmt = v => `×${v >= 10 ? Math.round(v) : v.toFixed(1).replace(/\.0$/, "")}`;
            const eff = status.eff_ms;
            if (eff && eff > ms * 1.25) return `${fmt(1200 / ms)} (実効${fmt(1200 / eff)})`;
            return fmt(1200 / ms);
          })()}</output>
        </label>
        <button className="tlbtn mutebtn" onClick={() => { initAudio(); setMuted(m => !m); }}>
          {muted ? "♪" : "♪♪"}
        </button>
      </div>
    </div>
  );
}
