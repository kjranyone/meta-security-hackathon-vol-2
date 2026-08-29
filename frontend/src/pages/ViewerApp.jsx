import { useEffect, useRef, useState, useCallback } from "react";
import MapCanvas from "../components/MapCanvas";
import StatsTable from "../components/StatsTable";
import EventFeed from "../components/EventFeed";
import PriceChart from "../components/PriceChart";
import TimelineBar from "../components/TimelineBar";
import IfPanel from "../components/IfPanel";
import Toasts, { useToasts } from "../components/Toasts";
import LegendModal from "../components/LegendModal";
import { VSplit, HSplit } from "../components/Splitter";

import { loadGeojson } from "../lib/geo";
import { ingestReplay, computeMajor } from "../lib/replay";
import { initAudio, beep, MAJOR_TONES } from "../lib/audio";
import { setClock } from "../lib/calendar";
import { eventsToPulses } from "../lib/pulses";
import PageTitle from "../components/PageTitle";

export default function ViewerApp({ params }) {
  const [geo, setGeo] = useState(null);
  const [meta, setMeta] = useState(null);
  const [ticks, setTicks] = useState([]);
  const [cur, setCur] = useState(0);
  const [selected, setSelected] = useState(null);
  const [showRoutes, setShowRoutes] = useState(false);
  const [pulses, setPulses] = useState([]);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(5);
  const [muted, setMuted] = useState(false);
  const [flash, setFlash] = useState(0);
  const [urlInput, setUrlInput] = useState("");
  const [ifOpen, setIfOpen] = useState(false);
  const [legendOpen, setLegendOpen] = useState(false);
  const [openOpen, setOpenOpen] = useState(false);   // リプレイを開く(URL/ファイル)モーダル
  const { toasts, push: pushToast } = useToasts();
  const [clockFrac, setClockFrac] = useState(0.5);
  const [sideW, setSideW] = useState(460);
  const [statsH, setStatsH] = useState(200);
  const [chartsH, setChartsH] = useState(170);
  const playTimer = useRef(null);
  const clockTimer = useRef(null);
  const lastBeep = useRef(-1);
  const statDrag = useRef(null);
  const chartDrag = useRef(null);

  useEffect(() => { loadGeojson().then(setGeo).catch(console.error); }, []);

  const loadReplayText = useCallback((text, initialTick) => {
    const { META, TICKS } = ingestReplay(text);
    if (!TICKS.length) { alert("replay.jsonl に tick がありません"); return; }
    setMeta(META); setTicks(TICKS); setCur(0); setSelected(null); setPlaying(false);
    if (initialTick != null) {
      const t0 = Math.max(0, Math.min(TICKS.length - 1, parseInt(initialTick, 10) || 0));
      if (t0 > 0) setCur(t0);   // デイープリンク: 指定tickを即表示(イベント発光も即時)
    }
    // リプレイの時計(1tick=何時間か)を暦表示に反映。旧月次リプレイは720
    setClock(META?.spec?.hours_per_tick ?? 720);
  }, []);

  const loadUrl = useCallback(async (url, initialTick) => {
    try {
      loadReplayText(await (await fetch(url)).text(), initialTick);
      setUrlInput(url);
    } catch (e) { alert("読み込み失敗: " + e.message); }
  }, [loadReplayText]);

  // ?replay= auto-load
  useEffect(() => {
    const q = params || new URLSearchParams(location.search);
    const r = q.get("replay");
    if (r) loadUrl(r, q.get("t"));
  }, [loadUrl, params]);

  // drag & drop
  useEffect(() => {
    const prevent = e => e.preventDefault();
    const drop = e => {
      e.preventDefault();
      const f = e.dataTransfer.files[0];
      if (!f) return;
      const rd = new FileReader();
      rd.onload = () => loadReplayText(rd.result);
      rd.readAsText(f);
    };
    window.addEventListener("dragover", prevent);
    window.addEventListener("drop", drop);
    return () => { window.removeEventListener("dragover", prevent); window.removeEventListener("drop", drop); };
  }, [loadReplayText]);

  const major = ticks.length ? computeMajor(ticks) : {};

  const majorEventAt = useCallback(i => {
    const t = ticks[i];
    if (!t || !major[t.tick]) return null;
    const ev = (t.events || []).find(e => MAJOR_TONES[e.type]);
    return ev || { type: "crash", text: `世界GDP急落 t${t.tick}` };
  }, [ticks, major]);

  const scrub = useCallback(i => {
    setCur(i);
    lastBeep.current = -1;
    const ev = majorEventAt(i);
    if (ev) {
      setFlash(f => f + 1);
      if (!muted) beep(MAJOR_TONES[ev.type] || 330);
      pushToast(ev.type, ev.text);
    }
  }, [majorEventAt, muted, pushToast]);

  const period = 1100 - speed * 100;
  useEffect(() => {
    if (!playing || !ticks.length) return;
    playTimer.current = setInterval(() => {
      const c = curRef.current;
      if (c + 1 >= ticks.length) { setPlaying(false); return; }   // 末尾で停止(最初へ戻らない)
      const next = c + 1;
      setCur(next);
      const t = ticks[next]?.tick;
      if (major[t] && lastBeep.current !== t) {
        lastBeep.current = t;
        setFlash(f => f + 1);
        if (!muted) beep(MAJOR_TONES[majorEventAt(next)?.type] || 330);
        const ev = majorEventAt(next);
        if (ev) pushToast(ev.type, ev.text);
      }
    }, period);
    const t0 = Date.now();
    clockTimer.current = setInterval(() =>
      setClockFrac(((Date.now() - t0) % period) / period), 300);
    return () => { clearInterval(playTimer.current); clearInterval(clockTimer.current); };
  }, [playing, period, ticks.length, major, muted]);

  const tick = ticks[cur] || null;
  const baseName = (urlInput.match(/logs\/([^/]+)\/replay\.jsonl/) || [])[1] || "";
  const curRef = useRef(0);   // 再生タイマーから読む現在位置(ループ停止判定に使う)
  curRef.current = cur;

  // 現在tickのイベントを地図上の発光パルスに(scrubでも再生でも、そのtickを
  // 見た瞬間に関係が光り、約4秒で消える — 常時表示との差別化)
  useEffect(() => {
    if (!tick) return;
    setPulses(eventsToPulses(tick.events || [], meta));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick]);

  // 縦分割ペーンのリサイズ(統計表とチャートで同じ挙動 — DRYに1ヘルパ化)
  const vdrag = (ref, h, set, reset) => ({
    onStart: ev => { ref.current = { y: ev.clientY, h }; },
    onMove: ev => {
      if (!ref.current) return;
      const maxH = document.querySelector(".side").getBoundingClientRect().height - 180;
      set(Math.min(Math.max(ref.current.h + ev.clientY - ref.current.y, 70), Math.max(maxH, 70)));
    },
    onEnd: () => { ref.current = null; },
    onReset: () => set(reset),
  });

  return (
    <div className="app">
      <header>
        <PageTitle small="Real-World Viewer" />
        <span className="spacer" />
        <button onClick={() => setOpenOpen(o => !o)}>リプレイを開く</button>
        <button className={showRoutes ? "on" : ""} onClick={() => setShowRoutes(s2 => !s2)}>航路</button>
        <button onClick={() => { initAudio(); setIfOpen(o => !o); }}>IF史</button>
        <button className="helpbtn" onClick={() => setLegendOpen(true)}>?</button>
      </header>


      <div className="main">
        <Toasts toasts={toasts} />
        {tick ? (
          <>
            <MapCanvas tick={tick} geo={geo} meta={meta}
                       selectedNation={selected} showRoutes={showRoutes}
                       pulses={pulses} />
          </>
        ) : (
          <div className="mapwrap">
            <div className="drophint">replay.jsonl をドロップ / URLで読み込み</div>
          </div>
        )}

        <VSplit
          onMove={ev => setSideW(Math.min(Math.max(window.innerWidth - ev.clientX, 300), window.innerWidth - 420))}
          onReset={() => setSideW(460)} />
        <div className="side" style={{ width: sideW }}>
          <div id="statspane" style={{ height: statsH, overflow: "auto", flex: "none", borderBottom: "1px solid var(--border)", padding: "8px 10px" }}>
            <StatsTable tick={tick} selected={selected} onSelect={setSelected} showStocks />
          </div>
<HSplit {...vdrag(statDrag, statsH, setStatsH, 200)} />
          <div id="chartspane" style={{ height: chartsH, overflow: "auto", flex: "none", borderBottom: "1px solid var(--border)", padding: "8px 10px" }}>
            <h3 style={{ fontSize: 11, color: "var(--dim)", textTransform: "uppercase", marginBottom: 6 }}>Prices &amp; Stability</h3>
            <PriceChart ticks={ticks} />
          </div>
<HSplit {...vdrag(chartDrag, chartsH, setChartsH, 170)} />
          <EventFeed events={tick?.events || []} />
        </div>
      </div>

      {openOpen && (
        <div className="modal-back" onClick={() => setOpenOpen(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h2>リプレイを開く</h2>
            <label className="modalfield">replay.jsonl のURL
              <input type="text" value={urlInput} onChange={e => setUrlInput(e.target.value)}
                     placeholder="replays/rl_earth_hormuz/replay.jsonl" />
            </label>
            <div className="modalbtns" style={{ justifyContent: "space-between" }}>
              <button onClick={() => { setOpenOpen(false); document.getElementById("file").click(); }}>
                ファイルを選択…
              </button>
              <button className="go" onClick={() => { loadUrl(urlInput); setOpenOpen(false); }}>読み込む</button>
            </div>
            <input type="file" id="file" accept=".jsonl" style={{ display: "none" }}
                   onChange={e => {
                     const f = e.target.files[0];
                     if (!f) return;
                     const rd = new FileReader();
                     rd.onload = () => loadReplayText(rd.result);
                     rd.readAsText(f);
                   }} />
            <p style={{ fontSize: 12, color: "var(--dim)", marginTop: 10 }}>
              この画面へ replay.jsonl をドラッグ＆ドロップしても読み込めます。
            </p>
          </div>
        </div>
      )}
      <TimelineBar
        playing={playing}
        onTogglePlay={() => {
          initAudio();
          // 末尾で停止した後の再生は最初から(そのまま再生すると即停止してしまうため)
          if (!playing && ticks.length && cur >= ticks.length - 1) { setCur(0); lastBeep.current = -1; }
          setPlaying(p => !p);
        }}
        cur={cur} ticks={ticks} major={major} onScrub={scrub}
        speed={speed} onSpeed={setSpeed}
        muted={muted} onMute={() => { initAudio(); setMuted(m => !m); }}
        flashCount={flash} clockFrac={clockFrac}
      />


      {legendOpen && <LegendModal onClose={() => setLegendOpen(false)} />}

      <IfPanel
        open={ifOpen}
        onClose={() => setIfOpen(false)}
        baseDefault={baseName}
        tickDefault={tick?.tick ?? 0}
        meta={meta}
        onLoadReplay={url => loadUrl(url)}
      />
    </div>
  );
}
