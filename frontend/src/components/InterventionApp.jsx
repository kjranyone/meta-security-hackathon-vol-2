import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import MapCanvas from "./MapCanvas";
import StatsTable from "./StatsTable";
import EventFeed from "./EventFeed";
import GodBar from "./GodBar";
import InterveneModal from "./InterveneModal";
import NationDetail from "./NationDetail";
import { VSplit } from "./Splitter";
import CreateWorldDialog from "./CreateWorldDialog";
import DateBar from "./DateBar";
import Toasts, { useToasts } from "./Toasts";
import LegendModal from "./LegendModal";
import StatusModal from "./StatusModal";
import ModalClose from "./ModalClose";
import { loadGeojson } from "../lib/geo";
import { pickAt } from "../lib/renderMap";
import { eventsToPulses } from "../lib/pulses";
import { setClock } from "../lib/calendar";
import { initAudio, beep, toneForTypes, MAJOR_TONES } from "../lib/audio";
import { GROUP_OF, GROUP_COLOR } from "../lib/eventMeta";

// ライブ推論モードの共通実装。GodApp(サーバ版・WebSocket)とLiveApp(ブラウザ実行・
// Web Worker + Pyodide)はtransport以外すべて同じUI/状態機械を持つため、
// 差分は mode だけに集約する(DRY)。
//   mode="server":  ws://host/ws 接続・世界再創造はPOST /api/reset
//   mode="browser": Worker(live.worker.js)・起動オーバーレイ・再創造もpostMessage
export default function InterventionApp({ mode = "server" }) {
  const browser = mode === "browser";
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
  const [preset, setPreset] = useState("earth_all");   // 既定は全世界176カ国
  const [policy, setPolicy] = useState("rl");
  const [seed, setSeed] = useState(42);
  const [rlNation, setRlNation] = useState("");
  const [conn, setConn] = useState(false);
  const [boot, setBoot] = useState(browser ? { stage: "init", msg: "準備中…" } : null);
  const [busy, setBusy] = useState(false);   // 週次決定(全政府の推論)でtickが止まっている間
  const [modeOpen, setModeOpen] = useState(browser);   // ブラウザ版: 開いたら世界を選べる
  const [worldSel, setWorldSel] = useState("earth_all");
  const [firstVisit] = useState(
    () => { try { return !localStorage.getItem("terrarium_welcomed"); } catch { return true; } });
  const [welcomeOpen, setWelcomeOpen] = useState(!browser && (() => {
    try { return !localStorage.getItem("terrarium_welcomed"); } catch { return true; }
  })());
  const startWorld = autoplay => {
    try { localStorage.setItem("terrarium_welcomed", "1"); } catch { /* プライベートモード等 */ }
    setPreset(worldSel);
    setSeed(+seed || 42);
    send({ cmd: "reset", world: worldSel, seed: +seed || 42, ticks: 24 * 400, autoplay });
    setModeOpen(false);
  };

  const closeWelcome = () => {
    try { localStorage.setItem("terrarium_welcomed", "1"); } catch { /* プライベートモード等 */ }
    setWelcomeOpen(false);
  };
  const [createOpen, setCreateOpen] = useState(false);
  const [ivModal, setIvModal] = useState(null);   // 開いている介入モーダルのaction
  const [legendOpen, setLegendOpen] = useState(false);
  const [statusOpen, setStatusOpen] = useState(false);
  const { toasts, push: pushToast } = useToasts();
  const busRef = useRef(null);   // WebSocket または Worker(送信先)
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
    const bus = busRef.current;
    if (!bus) return;
    if (browser) bus.postMessage(obj);
    else if (bus.readyState === 1) bus.send(JSON.stringify(obj));
  }, [browser]);

  const intervene = useCallback((type, params) =>
    send({ cmd: "intervene", type, params: params || {} }), [send]);

  const feedback = useCallback(types => {
    setFlash(f => f + 1);
    if (!muted) beep(toneForTypes(types));
  }, [muted]);

  // サーバ版とWorker版で同一のメッセージプロトコル(meta/tick/god/status)を処理
  const onMessage = useCallback(m => {
    if (m.type === "boot") { setBoot(m); return; }            // Workerのみ
    if (m.type === "booted") { setBoot(null); setConn(true); return; }
    if (m.type === "error") {
      pushToast("error", m.message);
      // 起動中の失敗はオーバーレイに表示し、再読み込み以外に抜け道が無い状態を避ける
      setBoot(b => b ? { ...b, error: m.message } : b);
      return;
    }
    if (m.type === "end") {   // max_ticks到達(サーバ版/ブラウザ版とも送信)
      setStatus({ running: m.running, tick: m.tick, max_ticks: m.max_ticks,
                  speed_ms: m.speed_ms, eff_ms: m.eff_ms, model: m.model });
      return;
    }
    if (m.type === "runresult") { window.__lastRun = m; return; }   // 検証フック
    if (m.type === "meta") {
      metaRef.current = m;
      setMeta(m); setTicks([]); setGodEvents([]); setCur(0);
      setPulses([]); pulseResetRef.current++;
      setClock(m.clock?.hours_per_tick ?? 1);
      if (m.status) setStatus(s => ({ ...s, ...m.status }));
    } else if (m.type === "busy") { setBusy(true);   // 週次推論でtick停止中
    } else if (m.type === "tick") {
      setBusy(false);
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
  }, [feedback, pushToast]);

  useEffect(() => {
    if (!browser) {
      // サーバ版: WebSocketに接続(切断は1.5秒で再接続)
      let ws;
      let closed = false;
      const connect = () => {
        ws = new WebSocket(`ws://${location.host}/ws`);
        busRef.current = ws;
        ws.onopen = () => setConn(true);
        ws.onmessage = ev => onMessage(JSON.parse(ev.data));
        ws.onclose = () => { setConn(false); if (!closed) setTimeout(connect, 1500); };
      };
      connect();
      return () => { closed = true; ws?.close(); };
    }
    // ブラウザ実行: Worker上でエンジン+学習モデル1本を起動。
    // SPAのハッシュ(#/live)はbase計算から除外する — さもないとmanifest fetchが
    // index.html自身を拾ってJSONパースが死ぬ
    const w = new Worker(new URL("../lib/live.worker.js", import.meta.url), { type: "module" });
    busRef.current = w;
    w.onmessage = ev => onMessage(ev.data);
    const base = location.href.split("#")[0].replace(/[^/]*$/, "");
    window.__liveSend = obj => w.postMessage(obj);   // 検証用フック
    w.postMessage({ cmd: "boot", base, world: "earth_all", seed: 42, ticks: 24 * 400, autoplay: false });   // 開いた時に勝手に動かさない
    return () => { w.terminate(); busRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [browser]);

  useEffect(() => {
    const once = () => initAudio();
    document.addEventListener("click", once, { once: true });
    return () => document.removeEventListener("click", once);
  }, []);

  // ライブシミュレーション: 常に最新tickを表示
  useEffect(() => { setCur(ticks.length - 1); }, [ticks.length]);

  function resetWorld() {
    if (browser) {
      // 同じ学習モデル1本でseed/世界だけ差し替える(サーバ不要)
      send({ cmd: "reset", world: preset === "gen" ? "default" : preset,
             seed: +seed || 42, ticks: 24 * 400, autoplay: false });   // 作っても停止。▶で開始
    } else {
      const body = {
        preset: preset === "gen" ? "default" : preset, policy,
        seed: +seed || 42, ticks: 24 * 400, autoplay: false,
      };   // 作っても停止。▶で開始
      if (preset === "gen") body.gen_seed = +seed || 42;   // 生成世界の初期値もseed欄で差し替え
      fetch("/api/reset", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }).catch(e => pushToast("error", "サーバに接続できません: " + e.message));
    }
    setSel({ kind: null, id: null });
  }

  function onMapClick(mx, my) {
    if (!geo || !meta) return;
    const picked = pickAt(mx, my, geo, meta);
    setSel(picked);
    if (picked.kind === "nation") openTab("nations");
  }

  const tick = ticks[Math.min(cur, ticks.length - 1)] || null;
  // 分類別の日本語集計(生のsnake_case識別子は審査官に伝わらない)
  const counts = {};
  let minorCount = 0;
  for (const t of ticks) for (const e of t.events || []) {
    const g = GROUP_OF[e.type];
    if (g) counts[g] = (counts[g] || 0) + 1;
    else minorCount++;
  }
  const countsStr = (Object.keys(GROUP_COLOR).filter(g => counts[g]).map(g => `${g}${counts[g]}`).join("・")
    + (minorCount ? `${counts && Object.keys(counts).length ? "・" : ""}政策など${minorCount}` : "")).trim();

  return (
    <div className="app">
      {browser && modeOpen && !boot && conn && (
        <div className="modal-back" style={{ zIndex: 45 }}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <ModalClose onClose={() => startWorld(false)} />
            <h2>ライブ推論モード — 世界を選ぶ</h2>
            {firstVisit && (
              <div className="kvcol">
                <div className="kv"><span>この画面</span><b>このブラウザ内(WASM)で学習モデル1本が毎週推論し、世界が動き続けます</b></div>
                <div className="kv"><span>介入</span><b>海峡をクリック→封鎖／国をクリック→救済・災害・性格の書き換えなど</b></div>
              </div>
            )}
            <label className="modalfield">世界
              <div className="radioopts">
                <label className="radioopt">
                  <input type="radio" name="wsel" checked={worldSel === "earth_all"}
                         onChange={() => setWorldSel("earth_all")} />
                  <span className="radioopt-body"><b>全世界 176カ国</b>
                    <small>既定・重厚。週次(168時間ごと)の全政府推論で数秒tickが止まります</small></span>
                </label>
                <label className="radioopt">
                  <input type="radio" name="wsel" checked={worldSel === "earth"}
                         onChange={() => setWorldSel("earth")} />
                  <span className="radioopt-body"><b>軽量版 16カ国</b>
                    <small>快適に観測。世界と介入の仕組みは同じ</small></span>
                </label>
              </div>
            </label>
            <label className="modalfield">seed
              <input type="number" value={seed} onChange={e => setSeed(e.target.value)} />
            </label>
            <div className="modalbtns">
              <button onClick={() => startWorld(false)}>停止状態で開く</button>
              <button className="go" onClick={() => startWorld(true)}>▶ 再生して開く</button>
            </div>
          </div>
        </div>
      )}
      {!browser && welcomeOpen && !boot && conn && (
        <div className="modal-back" style={{ zIndex: 45 }}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <ModalClose onClose={closeWelcome} />
            <h2>ライブ推論モードへようこそ</h2>
            <div className="kvcol">
              <div className="kv"><span>この画面</span><b>{browser ? "このブラウザ内(WASM)で" : "サーバ上で"}学習モデル1本が毎週推論し、世界が動き続けます（既定は全世界176カ国。 lightweightな16カ国版は「新しいシミュレーション」から）</b></div>
              <div className="kv"><span>始め方</span><b>下部の「▶ 再生」で開始（速度スライダーで早送り、停止中は「+1時間」で少しずつ）</b></div>
              <div className="kv"><span>介入</span><b>海峡をクリック→封鎖／国をクリック→救済・災害・性格の書き換えなど</b></div>
              <div className="kv"><span>調べる</span><b>海峡・国にホバーで状態と依存関係、タイトルクリックで新しいシミュレーション（seed・世界の差し替え）</b></div>
            </div>
            <div className="modalbtns">
              <button onClick={closeWelcome}>閉じる</button>
              <button className="go" onClick={() => { send({ cmd: "play" }); closeWelcome(); }}>▶ 再生して始める</button>
            </div>
          </div>
        </div>
      )}
      {boot && (
        <div className="modal-back" style={{ zIndex: 50 }}>
          <div className="modal" style={{ textAlign: "center" }}>
            <h2>{boot.error ? "起動に失敗しました" : "ブラウザでシミュレーションを起動中"}</h2>
            {boot.error ? (
              <>
                <p className="modalsub" style={{ color: "var(--bad)", wordBreak: "break-all" }}>{boot.error}</p>
                <p style={{ fontSize: 12, color: "var(--dim)", margin: "8px 0" }}>
                  ランタイム(CDN)または学習モデルの取得に失敗した可能性があります。ネットワークを確認して再試行してください。
                </p>
                <div className="modalbtns" style={{ justifyContent: "center" }}>
                  <button className="go" onClick={() => location.reload()}>再読み込み</button>
                </div>
              </>
            ) : (
              <>
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
              </>
            )}
          </div>
        </div>
      )}
      <header>
        <h1 onClick={() => setStatusOpen(true)}>Geopolitics Terrarium</h1>
        <span id="conn" className={conn ? "ok" : "bad"} onClick={() => setStatusOpen(true)}
              title={browser ? "状態と配備モデルを見る(ブラウザ内実行)" : "状態と配備モデルを見る"}>
          {browser || conn ? "●" : "● 切断"}
        </span>

        <span className="spacer" />
        <button onClick={() => setSel(s => (s.kind === "world" ? { kind: null, id: null } : { kind: "world", id: null }))}>世界</button>
        <button className="helpbtn" onClick={() => setLegendOpen(true)}>?</button>
      </header>

      <div className="main">
        <Toasts toasts={toasts} />
        <MapCanvas tick={tick} geo={geo} meta={meta} god pulses={pulses}
                   selectedNation={sel.kind === "nation" ? sel.id : null}
                   selectedChokepoint={sel.kind === "cp" ? sel.id : null}
                   onMapClick={onMapClick} />
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
        {busy && <span className="busychip" title="全政府(176カ国)の週次推論を実行中 — 数秒〜数十秒tickが止まります">週次推論中…</span>}
        <label className="speedlabel" style={{ flex: 1 }}><span>速度</span>
          <input type="range" min="30" max="3000" value={3030 - (status.speed_ms || 1200)}
                 onChange={e => send({ cmd: "speed", ms: 3030 - +e.target.value })} />
          <output title={browser
            ? "推論はブラウザ内(WASM)で走るため、要求速度に計算が追いつかない場合は実効値が下がる"
            : "推論はサーバCPUで走るため、要求速度に計算が追いつかない場合は実効値が下がる(世界サイズとマシン性能依存)"}>{(() => {
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

          <CreateWorldDialog open={createOpen} preset={preset} policy={policy} seed={seed}
                             rlNation={rlNation} modelInfo={status.model} onPreset={setPreset} onPolicy={setPolicy}
                             policyLocked={browser} noGen={browser}
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
            <StatusModal onClose={() => setStatusOpen(false)} conn={conn} status={status}
                         serverLabel={browser ? "ブラウザ内で実行中(Pyodide WASM — ネットワーク不使用)" : undefined}
                         onNewSim={() => { setStatusOpen(false); setCreateOpen(true); }}
                         tick={tick} meta={meta} preset={preset} policy={policy} seed={seed} />
          )}
    </div>
  );
}
