// ライブ推論モードWorker: Pyodide(CPython+WASM)上で本物のterrariumエンジンと
// RL推論(numpy, deep_bc 50MB)を走らせる。サーバ版Sessionと同じメッセージ
// プロトコル(meta/tick/status/god/end)をpostMessageで流す — UI(GodApp流用)は
// サーバ版と同じJSONで動く。力学の移植はないのでネイティブ実行と同じ決定論。
const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v0.27.2/full/pyodide.mjs";

let py = null;            // pyodide instance
let session = null;       // driver.LiveSession (PyProxy)
let dumps = null;         // python json.dumps helper
let timer = null;
let speedMs = 1200;
let running = false;
let tickTimes = [];
let effMs = null;
let base = "/";           // ページのbase(相対fetch用)

const post = obj => self.postMessage(obj);

async function fetchBin(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`fetch failed: ${url} (${r.status})`);
  return new Uint8Array(await r.arrayBuffer());
}

async function boot(cfg) {
  post({ type: "boot", stage: "pyodide", msg: "Python(WASM)ランタイムを読み込み中…" });
  const { loadPyodide } = await import(/* @vite-ignore */ PYODIDE_URL);
  py = await loadPyodide({ indexURL: PYODIDE_URL.replace(/pyodide\.mjs$/, "") });
  post({ type: "boot", stage: "numpy", msg: "numpyを読み込み中…" });
  await py.loadPackage("numpy");

  post({ type: "boot", stage: "code", msg: "シミュレーションエンジンを読み込み中…" });
  const manifest = await (await fetch(`${base}pyworker/manifest.json`)).json();
  console.log("[worker] manifest ok:", manifest.py.length, "py files");
  py.FS.mkdirTree("/pw/worlds");
  for (const rel of manifest.py) {
    const bin = await fetchBin(`${base}pyworker/${rel}`);
      py.FS.mkdirTree(`/pw/${rel.split("/").slice(0, -1).join("/")}` || "/pw");
    py.FS.writeFile(`/pw/${rel}`, bin);
  }
  console.log("[worker] py files done");
  for (const w of manifest.worlds) {
    const bin = await fetchBin(`${base}pyworker/worlds/${w}.json`);
    py.FS.writeFile(`/pw/worlds/${w}.json`, bin);
  }
  console.log("[worker] worlds done");
  py.runPython(
    "import sys; sys.path.insert(0, '/pw')\n" +
    "import json\n" +
    "def dumps(x):\n    return json.dumps(x, ensure_ascii=False)\n");
  dumps = py.globals.get("dumps");
  console.log("[worker] python helpers ok");

  post({ type: "boot", stage: "weights", msg: "学習モデル(約50MB)を読み込み中…", pct: 0 });
  const wurl = `${base}${manifest.weights}`;
  const wr = await fetch(wurl);
  if (!wr.ok) throw new Error(`weights fetch failed (${wr.status})`);
  const total = +(wr.headers.get("content-length") || 50968788);
  const reader = wr.body.getReader();
  const chunks = [];
  let got = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value); got += value.length;
    if (total) post({ type: "boot", stage: "weights", msg: "学習モデル(約50MB)を読み込み中…",
                     pct: Math.round(100 * got / total) });
  }
  const wbuf = new Uint8Array(got);
  let off = 0;
  for (const c of chunks) { wbuf.set(c, off); off += c.length; }
  py.FS.mkdirTree("/pw/models");
  py.FS.writeFile("/pw/models/model.npz", wbuf);
  console.log("[worker] weights written", wbuf.length);

  console.log("[worker] importing driver…");
  const driver = py.pyimport("driver");
  console.log("[worker] driver imported");
  post({ type: "boot", stage: "world", msg: "世界を構築中…" });
  session = driver.new_session(
    py.FS.readFile(`/pw/worlds/${cfg.world}.json`, { encoding: "utf8" }),
    cfg.seed, cfg.ticks, "/pw/models/model.npz");
  running = !!cfg.autoplay;
  restartTimer();
  post({ type: "booted" });
  post(JSON.parse(dumps(session.meta())));
  post(statusMsg());
}

function statusMsg() {
  return { type: "status", running, speed_ms: speedMs, eff_ms: effMs,
           tick: session ? session.t : 0, max_ticks: session ? session.max_ticks : 0,
           model: session ? JSON.parse(dumps(session.model_info)) : null };
}

function doStep() {
  if (!session) return;
  const t0 = performance.now();
  const out = dumps(session.step());
  if (out === "null") {           // max_ticks到達
    running = false;
    restartTimer();
    post({ type: "end", ...statusMsg() });
    return;
  }
  tickTimes.push(performance.now());
  if (tickTimes.length > 20) tickTimes = tickTimes.slice(-20);
  effMs = (tickTimes[tickTimes.length - 1] - tickTimes[0]) / (tickTimes.length - 1);
  post(JSON.parse(out));
  post(statusMsg());
}

function restartTimer() {
  if (timer) clearInterval(timer);
  timer = setInterval(() => { if (running) doStep(); }, speedMs);
}

self.onmessage = async ev => {
  const m = ev.data;
  try {
    if (m.cmd === "boot") {
      base = m.base || "/";
      await boot(m);
    } else if (m.cmd === "reset") {
      if (!py) return;
      const driver = py.pyimport("driver");
      session = driver.new_session(
        py.FS.readFile(`/pw/worlds/${m.world}.json`, { encoding: "utf8" }),
        m.seed, m.ticks, "/pw/models/model.npz");
      tickTimes = []; effMs = null;
      running = !!m.autoplay;
      restartTimer();
      post(JSON.parse(dumps(session.meta())));
      post(statusMsg());
    } else if (m.cmd === "play") {
      running = true; post(statusMsg());
    } else if (m.cmd === "pause") {
      running = false; post(statusMsg());
    } else if (m.cmd === "speed") {
      speedMs = Math.max(30, Math.min(5000, +m.ms || 1200));
      restartTimer(); post(statusMsg());
    } else if (m.cmd === "step") {
      doStep();
    } else if (m.cmd === "intervene") {
      if (!session) return;
      post(JSON.parse(dumps(session.intervene(m.type, JSON.stringify(m.params || {})))));
    } else if (m.cmd === "run") {
      // 検証用: 同期的にN tick進め、tickごとのmetricsを返す(パリティ検査で使用)
      if (!session) return;
      const metrics = [];
      for (let i = 0; i < m.ticks; i++) {
        const out = dumps(session.step());
        if (out === "null") break;
        const s = JSON.parse(out);
        metrics.push(s.metrics);
      }
      post({ type: "runresult", metrics, status: statusMsg() });
    }
  } catch (e) {
    console.error("[worker] command failed:", e);
    post({ type: "error", message: String(e && e.message || e) });
  }
};
