import { useState } from "react";
import { TECHS, RESOURCES } from "./GodBar";

const SLIDERS = ["trade_efficiency", "food_yield", "energy_yield", "chips_yield",
                 "minerals_yield", "space_yield", "ai_aggression", "disinfo_intensity"];

// 右パネルの神介入カード（詳細パラメータ用。HUDはGodBar）
export default function GodCards({ sel, meta, tick, intervene }) {
  const [rate, setRate] = useState(5);
  const [dis, setDis] = useState(1.5);
  const [agg, setAgg] = useState(0.8);
  const [par, setPar] = useState(0.8);
  const [res, setRes] = useState("oil");
  const [qty, setQty] = useState(1);
  const [dres, setDres] = useState("oil");
  const [tech, setTech] = useState("fusion");
  const [banTech, setBanTech] = useState("fusion");
  const [sliders, setSliders] = useState(Object.fromEntries(SLIDERS.map(p => [p, 1])));

  if (!sel.kind) {
    return (
      <>
        <h3>⚡ 神の介入 <span style={{ color: "var(--god)" }}>— 世界パラメータ</span></h3>
        <div className="cardrow">
          <div className="card"><b>💥 世界金利</b>
            <div className="cardrow">
              <label className="sl"><span>利上げ</span>
                <input type="range" min="0" max="15" step="0.5" value={rate}
                       onChange={e => setRate(+e.target.value)} /><output>{rate}%</output>
              </label>
              <button className="godbtn" onClick={() => intervene("rate_hike", { value: rate / 100 })}>利上げを宣告</button>
            </div>
          </div>
          <div className="card"><b>🌍 世界スライダー</b>
            {SLIDERS.map(p => (
              <label className="sl" key={p}><span>{p}</span>
                <input type="range" min="0.3" max="1.8" step="0.05" value={sliders[p]}
                       onChange={e => setSliders(s => ({ ...s, [p]: +e.target.value }))} />
                <output>{sliders[p]}</output>
              </label>
            ))}
            <button className="godbtn" onClick={() =>
              SLIDERS.forEach(p => intervene("global_slider", { param: p, value: sliders[p] }))}>
              全スライダーを適用</button>
          </div>
          <div className="card"><b>🚫 技術の禁止</b>
            <div className="cardrow">
              <select value={banTech} onChange={e => setBanTech(e.target.value)}>
                {TECHS.map(t => <option key={t}>{t}</option>)}
              </select>
              <button className="godbtn" onClick={() => intervene("ban_tech", { tech: banTech })}>全世界で禁止</button>
            </div>
          </div>
        </div>
        <div className="hint">地図の海峡⚓または国家をクリックして介入カードを選べる。何も選んでいないときは世界パラメータ。</div>
      </>
    );
  }

  if (sel.kind === "cp") {
    return (
      <>
        <h3>⚡ 神の介入 <span style={{ color: "var(--god)" }}>— {sel.id}</span></h3>
        <div className="cardrow">
          <div className="card"><b>⛔ 海峡封鎖: {sel.id}</b>
            <div className="cardrow">
              {[6, 12, 24, 60].map(d => (
                <button key={d} className="godbtn"
                        onClick={() => intervene("close_chokepoint", { chokepoint: sel.id, duration: d })}>
                  {d}時間
                </button>
              ))}
              <button onClick={() => intervene("open_chokepoint", { chokepoint: sel.id })}>解除</button>
            </div>
          </div>
        </div>
      </>
    );
  }

  const nid = sel.id;
  const n = tick?.nations?.[nid];
  const name = meta?.geo?.nations?.[nid]?.name || nid;
  return (
    <>
      <h3>⚡ 神の介入 <span style={{ color: "var(--god)" }}>— {name}</span></h3>
      <div className="cardrow">
        <div className="card"><b>📰 偽情報</b>
          <div className="cardrow">
            <label className="sl"><span>強度</span>
              <input type="range" min="0.5" max="3" step="0.25" value={dis}
                     onChange={e => setDis(+e.target.value)} /><output>{dis}</output>
            </label>
            <button className="godbtn" onClick={() => intervene("disinfo", { target: nid, intensity: dis })}>投下</button>
          </div>
        </div>
        <div className="card"><b>🌪 災害</b>
          <div className="cardrow">
            {["drought", "earthquake", "epidemic"].map(k => (
              <button key={k} className="godbtn" onClick={() => intervene("disaster", { nation: nid, kind: k })}>{k}</button>
            ))}
          </div>
        </div>
        <div className="card"><b>🧠 性格書き換え</b>
          <label className="sl"><span>好戦性</span>
            <input type="range" min="0" max="1" step="0.05" value={agg}
                   onChange={e => setAgg(+e.target.value)} /><output>{agg}</output>
          </label>
          <label className="sl"><span>疑心暗鬼</span>
            <input type="range" min="0" max="1" step="0.05" value={par}
                   onChange={e => setPar(+e.target.value)} /><output>{par}</output>
          </label>
          <button className="godbtn" onClick={() => {
            intervene("set_param", { nation: nid, param: "aggression", value: agg });
            intervene("set_param", { nation: nid, param: "paranoia", value: par });
          }}>書き換える</button>
        </div>
        <div className="card"><b>⛏ 資源を創る</b>
          <div className="cardrow">
            <select value={res} onChange={e => setRes(e.target.value)}>
              {RESOURCES.map(r => <option key={r}>{r}</option>)}
            </select>
            <select value={qty} onChange={e => setQty(+e.target.value)}>
              {[1, 2, 3].map(q => <option key={q}>{q}</option>)}
            </select>
            <button className="godbtn" onClick={() => intervene("create_resource", { nation: nid, resource: res, quantity: qty })}>創造</button>
          </div>
        </div>
        <div className="card"><b>💀 資源を消す</b>
          <div className="cardrow">
            <select value={dres} onChange={e => setDres(e.target.value)}>
              {RESOURCES.map(r => <option key={r}>{r}</option>)}
            </select>
            <button onClick={() => intervene("destroy_resource", { nation: nid, resource: dres })}>消滅</button>
          </div>
        </div>
        <div className="card"><b>🏦 救済（ベイルアウト）</b>
          <div className="cardrow">
            <button className="godbtn" onClick={() => intervene("bailout", { nation: nid })}>債務を半減し信用回復</button>
          </div>
        </div>
        <div className="card"><b>🔬 技術を授ける</b>
          <div className="cardrow">
            <select value={tech} onChange={e => setTech(e.target.value)}>
              {TECHS.map(t => <option key={t}>{t}</option>)}
            </select>
            <button className="godbtn" onClick={() => intervene("grant_tech", { nation: nid, tech })}>授与</button>
          </div>
        </div>
      </div>
      {n && (
        <div className="hint">
          現況: GDP {n.gdp.toFixed(1)}兆$ / 債務 {n.debt_gdp.toFixed(0)}% / 信用 {n.credibility.toFixed(0)} / 安定 {n.stability.toFixed(0)} / 破綻 {n.defaults}回
        </div>
      )}
    </>
  );
}
