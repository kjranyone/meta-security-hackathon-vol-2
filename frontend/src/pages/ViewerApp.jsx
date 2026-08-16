import { useEffect, useRef, useState, useCallback } from "react";
import MapCanvas from "../components/MapCanvas";
import StatsTable from "../components/StatsTable";
import EventFeed from "../components/EventFeed";
import PriceChart from "../components/PriceChart";
import DateBar from "../components/DateBar";
import TimelineBar from "../components/TimelineBar";
import IfPanel from "../components/IfPanel";
import { VSplit, HSplit } from "../components/Splitter";
import HelpModal from "../components/HelpModal";
import Tip from "../components/Tooltip";
import { loadGeojson } from "../lib/geo";
import { ingestReplay, computeMajor } from "../lib/replay";
import { initAudio, beep, toneForColor } from "../lib/audio";

export default function ViewerApp() {
  const [geo, setGeo] = useState(null);
  const [meta, setMeta] = useState(null);
  const [ticks, setTicks] = useState([]);
  const [cur, setCur] = useState(0);
  const [selected, setSelected] = useState(null);
  const [showRoutes, setShowRoutes] = useState(true);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(5);
  const [muted, setMuted] = useState(false);
  const [flash, setFlash] = useState(0);
  const [urlInput, setUrlInput] = useState("");
  const [ifOpen, setIfOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(() => !localStorage.getItem("terrarium_help_viewer"));
  const [clockFrac, setClockFrac] = useState(0.5);
  const [sideW, setSideW] = useState(460);
  const [statsH, setStatsH] = useState(200);
  const [chartsH, setChartsH] = useState(170);
  const playTimer = useRef(null);
  const clockTimer = useRef(null);
  const lastBeep = useRef(-1);

  useEffect(() => { loadGeojson().then(setGeo).catch(console.error); }, []);

  const loadReplayText = useCallback(text => {
    const { META, TICKS } = ingestReplay(text);
    if (!TICKS.length) { alert("replay.jsonl に tick がありません"); return; }
    setMeta(META); setTicks(TICKS); setCur(0); setSelected(null); setPlaying(false);
  }, []);

  const loadUrl = useCallback(async url => {
    try { loadReplayText(await (await fetch(url)).text()); setUrlInput(url); }
    catch (e) { alert("読み込み失敗: " + e.message); }
  }, [loadReplayText]);

  // ?replay= auto-load
  useEffect(() => {
    const q = new URLSearchParams(location.search).get("replay");
    if (q) loadUrl(q);
  }, [loadUrl]);

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

  const scrub = useCallback(i => {
    setCur(i);
    lastBeep.current = -1;
    if (major[ticks[i]?.tick]) {
      setFlash(f => f + 1);
      if (!muted) beep(toneForColor(major[ticks[i].tick]));
    }
  }, [major, ticks, muted]);

  const period = 1100 - speed * 100;
  useEffect(() => {
    if (!playing || !ticks.length) return;
    playTimer.current = setInterval(() => {
      setCur(c => {
        const next = c + 1 >= ticks.length ? 0 : c + 1;
        const t = ticks[next]?.tick;
        if (major[t] && lastBeep.current !== t) {
          lastBeep.current = t;
          setFlash(f => f + 1);
          if (!muted) beep(toneForColor(major[t]));
        }
        return next;
      });
    }, period);
    const t0 = Date.now();
    clockTimer.current = setInterval(() =>
      setClockFrac(((Date.now() - t0) % period) / period), 300);
    return () => { clearInterval(playTimer.current); clearInterval(clockTimer.current); };
  }, [playing, period, ticks.length, major, muted]);

  const tick = ticks[cur] || null;
  const baseName = (urlInput.match(/logs\/([^/]+)\/replay\.jsonl/) || [])[1] || "";

  return (
    <div className="app">
      <header>
        <h1>🌐 Geopolitics Terrarium — Real-World Viewer</h1>
        <span className="spacer" />
        <Tip title="replayのURL" text="server/logs/<run>/replay.jsonl を指定して実行済みの歴史を読み込む。?replay= パラメータでも自動読込。">
          <input type="text" value={urlInput} onChange={e => setUrlInput(e.target.value)}
                 placeholder="http://localhost:8787/server/logs/earth_hormuz/replay.jsonl" />
        </Tip>
        <Tip title="読み込み" text="URLからreplay.jsonlを取得して再生できるようにする。">
          <button onClick={() => loadUrl(urlInput)}>読み込み</button>
        </Tip>
        <Tip title="ファイルを開く" text="ローカルのreplay.jsonlを開く（画面へのドラッグ＆ドロップでも可）。">
          <button onClick={() => document.getElementById("file").click()}>ファイルを開く</button>
        </Tip>
        <input type="file" id="file" accept=".jsonl" style={{ display: "none" }}
               onChange={e => {
                 const f = e.target.files[0];
                 if (!f) return;
                 const rd = new FileReader();
                 rd.onload = () => loadReplayText(rd.result);
                 rd.readAsText(f);
               }} />
        <Tip title="航路の表示ON/OFF" text="海峡を経由する貿易航路の弧（琥珀=エネルギー 緑=食料 青=半導体 紫=地下 水色=宇宙）の表示を切替。封鎖航路は赤破線。">
          <button className={showRoutes ? "on" : ""} onClick={() => setShowRoutes(s => !s)}>航路</button>
        </Tip>
        <Tip title="IF史モード" text="「過去、●●年に△△していたら」: 分岐tickと介入を1つ選び、決定論エンジンで歴史を分岐させる。">
          <button onClick={() => { initAudio(); setIfOpen(o => !o); }}>⏪ IF史</button>
        </Tip>
        <Tip title="操作ガイド" text="地図の読み方・タイムライン・IF史の使い方をもう一度見る。">
          <button className="helpbtn" onClick={() => setHelpOpen(true)}>?</button>
        </Tip>
      </header>

      {helpOpen && (
        <HelpModal page="viewer" onClose={() => {
          setHelpOpen(false);
          localStorage.setItem("terrarium_help_viewer", "1");
        }} />
      )}

      <div className="main">
        {tick ? (
          <>
            <MapCanvas tick={tick} geo={geo} meta={meta}
                       selectedNation={selected} showRoutes={showRoutes} />
            <DateBar tick={tick.tick} maxTick={ticks[ticks.length - 1].tick}
                     frac={playing ? clockFrac : 0.5} visible />
            <div className="legend">
              色付き国=国家 ・ ⚓/⛔ 海峡 ・ 実線=航路（琥珀=エネルギー 緑=食料 青=チップ 紫=地下資源 水色=宇宙）・ ⚔️ 戦争 ・ 💀 崩壊 ・ 橙枠=債務不履行 ・ 水色枠=未来技術の創発
              <br /><span style={{ color: "#3fb950" }}>緑=高信頼</span> / 灰=中立 / <span style={{ color: "#f85149" }}>赤=敵対</span> = 友好度線（国選択中=その国の関係全域、未選択=主要関係）
            </div>
          </>
        ) : (
          <div className="mapwrap">
            <div className="drophint">
              replay.jsonl をドラッグ＆ドロップ または URL/ファイルで読み込み<br />
              <small>例: <code>cd server && uv run python -m terrarium.runner.headless --preset earth --scenario scenarios/earth_hormuz.yaml</code></small>
            </div>
          </div>
        )}

        <VSplit
          onMove={ev => setSideW(Math.min(Math.max(window.innerWidth - ev.clientX, 300), window.innerWidth - 420))}
          onReset={() => setSideW(460)} />
        <div className="side" style={{ width: sideW }}>
          <div id="statspane" style={{ height: statsH, overflow: "auto", flex: "none", borderBottom: "1px solid var(--border)", padding: "8px 10px" }}>
            <StatsTable tick={tick} selected={selected} onSelect={setSelected} showStocks />
          </div>
          <HSplit
            onMove={ev => {
              const el = document.getElementById("statspane");
              const top = el.getBoundingClientRect().top;
              const maxH = document.querySelector(".side").getBoundingClientRect().height - 180;
              setStatsH(Math.min(Math.max(ev.clientY - top, 70), Math.max(maxH, 70)));
            }}
            onReset={() => setStatsH(200)} />
          <div id="chartspane" style={{ height: chartsH, overflow: "auto", flex: "none", borderBottom: "1px solid var(--border)", padding: "8px 10px" }}>
            <h3 style={{ fontSize: 11, color: "var(--dim)", textTransform: "uppercase", marginBottom: 6 }}>Prices &amp; Stability</h3>
            <PriceChart ticks={ticks} />
          </div>
          <HSplit
            onMove={ev => {
              const el = document.getElementById("chartspane");
              const top = el.getBoundingClientRect().top;
              const maxH = document.querySelector(".side").getBoundingClientRect().height - 180;
              setChartsH(Math.min(Math.max(ev.clientY - top, 70), Math.max(maxH, 70)));
            }}
            onReset={() => setChartsH(170)} />
          <EventFeed events={tick?.events || []} />
        </div>
      </div>

      <TimelineBar
        playing={playing}
        onTogglePlay={() => { initAudio(); setPlaying(p => !p); }}
        cur={cur} ticks={ticks} major={major} onScrub={scrub}
        speed={speed} onSpeed={setSpeed}
        muted={muted} onMute={() => { initAudio(); setMuted(m => !m); }}
        flashCount={flash}
      />

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
