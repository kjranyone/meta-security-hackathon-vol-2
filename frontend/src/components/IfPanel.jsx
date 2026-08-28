import { useEffect, useState } from "react";
import { TECHS } from "./GodBar";

const IF_RESOURCES = ["oil", "gas", "grain", "fab", "mineral", "orbit", "finance"];
const NATION_JA = { JPN: "日本", USA: "米国", CHN: "中国", EUR: "EU", SAU: "サウジ", RUS: "ロシア",
  IND: "インド", EGY: "エジプト", TWN: "台湾", KOR: "韓国", IRN: "イラン", TUR: "トルコ",
  IDN: "インドネシア", AUS: "豪州", CAN: "カナダ", BRA: "ブラジル" };

// IF史モード: 過去tickに介入を差し込んで歴史を分岐させる（サーバ /api/whatif 経由）
export default function IfPanel({ open, onClose, baseDefault, tickDefault, meta, onLoadReplay }) {
  const [base, setBase] = useState(baseDefault || "");
  const [tick, setTick] = useState(tickDefault ?? 0);
  const [type, setType] = useState("bailout");
  const [nation, setNation] = useState("JPN");
  const [value, setValue] = useState(0.08);
  const [chokepoint, setChokepoint] = useState("Strait of Hormuz");
  const [duration, setDuration] = useState(24);
  const [resource, setResource] = useState("oil");
  const [quantity, setQuantity] = useState(2);
  const [tech, setTech] = useState("fusion");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  // パネルを開くたび: base はURLから自動検出、tickは現在のscrub位置で初期化
  useEffect(() => {
    if (!open) return;
    if (baseDefault) setBase(b => b || baseDefault);
    if (tickDefault != null) setTick(tickDefault);
  }, [open, baseDefault, tickDefault]);

  if (!open) return null;
  const nationIds = meta?.geo ? Object.keys(meta.geo.nations) : ["JPN", "USA"];
  const cps = meta?.geo?.chokepoints?.map(c => c.name) || ["Strait of Hormuz"];

  function buildIv() {
    const p = {};
    if (type === "bailout") p.nation = nation;
    else if (type === "rate_hike") p.value = value;
    else if (type === "close_chokepoint") { p.chokepoint = chokepoint; if (duration) p.duration = duration; }
    else if (type === "create_resource") { p.nation = nation; p.resource = resource; p.quantity = quantity; }
    else if (type === "grant_tech") { p.nation = nation; p.tech = tech; }
    else if (type === "ban_tech") p.tech = tech;
    return type + ":" + Object.entries(p).map(([k, v]) => `${k}=${v}`).join(",");
  }

  async function run() {
    setBusy(true);
    setResult({ busy: true });
    try {
      const res = await fetch("/api/whatif", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ base, tick: +tick, ivs: [buildIv()] }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
      const data = await res.json();
      setResult({ data });
    } catch (e) {
      setResult({ error: e.message });
    } finally {
      setBusy(false);
    }
  }

  const r = result?.data?.report;
  const fmt = x => (x >= 0 ? "+" : "") + (+x).toFixed(1);

  return (
    <div className="ifpanel">
      <h3>IF史モード — 「過去に△△していたら」</h3>
      <label>元の歴史（base run）</label>
      <input type="text" value={base} onChange={e => setBase(e.target.value)}
             placeholder="earth_earth_financial_crisis" />
      <label>分岐するtick</label>
      <input type="number" min="0" value={tick} onChange={e => setTick(e.target.value)} />
      <label>介入カード</label>
      <select value={type} onChange={e => setType(e.target.value)}>
        <option value="bailout">救済（ベイルアウト） nation</option>
        <option value="rate_hike">世界金利引き上げ value</option>
        <option value="close_chokepoint">海峡封鎖 chokepoint, duration</option>
        <option value="create_resource">資源の創造 nation, resource, quantity</option>
        <option value="grant_tech">技術の授与 nation, tech</option>
        <option value="ban_tech">技術の全世界禁止 tech</option>
      </select>
      {type === "bailout" || type === "create_resource" || type === "grant_tech" ? (
        <><label>nation（国家ID）</label>
          <select value={nation} onChange={e => setNation(e.target.value)}>
            {nationIds.map(n => <option key={n}>{n}</option>)}
          </select></>
      ) : null}
      {type === "rate_hike" ? (
        <><label>value（引き上げ幅、例 0.08 = +8%）</label>
          <input type="number" step="0.01" value={value} onChange={e => setValue(e.target.value)} /></>
      ) : null}
      {type === "close_chokepoint" ? (
        <><label>chokepoint（海峡）</label>
          <select value={chokepoint} onChange={e => setChokepoint(e.target.value)}>
            {cps.map(c => <option key={c}>{c}</option>)}
          </select>
          <label>duration（ヶ月、空欄=永続）</label>
          <input type="number" value={duration} onChange={e => setDuration(e.target.value)} /></>
      ) : null}
      {type === "create_resource" ? (
        <><label>resource（資源）</label>
          <select value={resource} onChange={e => setResource(e.target.value)}>
            {IF_RESOURCES.map(x => <option key={x}>{x}</option>)}
          </select>
          <label>quantity（ユニット数）</label>
          <input type="number" value={quantity} onChange={e => setQuantity(e.target.value)} /></>
      ) : null}
      {type === "grant_tech" || type === "ban_tech" ? (
        <><label>tech（技術）</label>
          <select value={tech} onChange={e => setTech(e.target.value)}>
            {TECHS.map(t => <option key={t}>{t}</option>)}
          </select></>
      ) : null}
      <button className="go" onClick={run} disabled={busy}>歴史を分岐させる</button>
      <button onClick={onClose}>閉じる</button>
      <div className="ifresult">
        {result?.busy && <span className="ng">分岐実行中…（決定論再実行、数秒）</span>}
        {result?.error && (<>
          <span className="ng">失敗: {result.error}</span><br />
          <small style={{ color: "var(--dim)" }}>base run 名とサーバ(8788)経由のアクセスを確認してください</small>
        </>)}
        {r && (<>
          <span className="ok">分岐: {result.data.name}</span><br />
          {(result.data.warnings || []).map((w, i) => <span key={i} className="ng">{w}</span>)}
          IF: <b>t{r.fork_tick}</b> で <b>{r.interventions[0].type}</b> {JSON.stringify(r.interventions[0].params)}<br />
          歴史が変わった最初のtick: <b>t{r.first_divergence_tick}</b><br />
          最終差分: GDP {fmt(r.final_metric_deltas.world_gdp)} / デフォルト {fmt(r.final_metric_deltas.defaults)} / 戦争 {fmt(r.final_metric_deltas.wars || 0)}<br />
          {r.only_in_base.length > 0 && (
            <div style={{ marginTop: 6 }}>元の歴史でだけ起きた:
              <ul>{r.only_in_base.map((e, i) => <li key={i}>t{e.tick} {NATION_JA[e.actor] || e.actor} {e.type}</li>)}</ul>
            </div>)}
          {r.only_in_fork.length > 0 && (
            <div>IF世界で新たに起きた:
              <ul>{r.only_in_fork.map((e, i) => <li key={i}>t{e.tick} {NATION_JA[e.actor] || e.actor} {e.type}</li>)}</ul>
            </div>)}
          <button onClick={() => onLoadReplay(location.origin + result.data.replay)}>IF世界をこの画面で開く</button>
        </>)}
      </div>
    </div>
  );
}
