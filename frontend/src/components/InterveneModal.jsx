import { useEffect, useState } from "react";
import { TECHS, RESOURCES, RESOURCE_JA } from "./GodBar";

const P = (label, hint) => <label className="modalfield">{label}{hint ? <small style={{ color: "var(--dim)", display: "block" }}>{hint}</small> : null}</label>;

// HUDボタン → パラメータモーダルの定義
// run(params) で実行。fields: range / select / number
const ACTIONS = {
  close_chokepoint: {
    title: "海峡封鎖", sub: c => `${c} を封鎖する期間`,
    fields: [
      { k: "duration", label: "期間（時間）", type: "select", options: [6, 12, 24, 60, 0], optionLabel: v => v === 0 ? "無期限" : `${v}時間`, def: 12 },
    ],
    build: (v, ctx) => ({ chokepoint: ctx, ...(v.duration ? { duration: v.duration } : {}) }),
  },
  disinfo: {
    title: "偽情報", sub: t => `${t} へ投下する偽情報の強度`,
    fields: [
      { k: "intensity", label: "強度", type: "range", min: 0.5, max: 3, step: 0.25, def: 1.5 },
    ],
    build: (v, ctx) => ({ target: ctx, intensity: +v.intensity }),
  },
  disaster: {
    title: "災害", sub: t => `${t} に降り注ぐ災害`,
    fields: [
      // 効き目の数字はエンジン側の実装(engine.pyの災害分岐)と対応。変える時は両方
      { k: "kind", label: "種類", type: "radio", def: "drought",
        options: [
          { value: "drought", label: "旱魃", hint: "食料生産−60%が6ヶ月間 — 長期じわじわ型" },
          { value: "earthquake", label: "大地震", hint: "安定−10・GDP−2% — 一撃型" },
          { value: "epidemic", label: "疫病", hint: "人口−2%・安定−8%" },
        ] },
    ],
    build: (v, ctx) => ({ nation: ctx, kind: v.kind }),
  },
  create_resource: {
    title: "資源の創造", sub: t => `${t} に新たに生み出す資源`,
    fields: [
      { k: "resource", label: "資源", type: "select", options: RESOURCES, optionLabel: v => RESOURCE_JA[v] || v },
      { k: "quantity", label: "数量", type: "range", min: 1, max: 3, step: 1, def: 2 },
    ],
    build: (v, ctx) => ({ nation: ctx, resource: v.resource, quantity: +v.quantity }),
  },
  destroy_resource: {
    title: "資源の消滅", sub: t => `${t} から消し去る資源`,
    fields: [
      { k: "resource", label: "資源", type: "select", options: RESOURCES, optionLabel: v => RESOURCE_JA[v] || v },
    ],
    build: (v, ctx) => ({ nation: ctx, resource: v.resource }),
  },
  grant_tech: {
    title: "技術の授与", sub: t => `${t} に授ける技術`,
    fields: [
      { k: "tech", label: "技術", type: "select", options: TECHS },
    ],
    build: (v, ctx) => ({ nation: ctx, tech: v.tech }),
  },
  ban_tech: {
    title: "技術の全世界禁止",
    fields: [
      { k: "tech", label: "技術", type: "select", options: TECHS },
    ],
    build: v => ({ tech: v.tech }),
  },
  set_params: {
    title: "性格の書き換え", sub: t => `${t} の性格`,
    fields: [
      { k: "aggression", label: "好戦性", type: "range", min: 0, max: 1, step: 0.05, def: 0.8 },
      { k: "paranoia", label: "疑心暗鬼", type: "range", min: 0, max: 1, step: 0.05, def: 0.8 },
    ],
    build: (v, ctx) => ({ nation: ctx, aggression: +v.aggression, paranoia: +v.paranoia }),
  },
  grant_factor: {
    title: "因子の授与", sub: t => `${t} に既成事実として与える因子`,
    fields: [
      { k: "factor", label: "因子", type: "select",
        options: ["nuclear", "nuclear_umbrella", "export_control", "currency_bloc"],
        optionLabel: v => ({ nuclear: "核兵器", nuclear_umbrella: "核傘",
                             export_control: "輸出規制レジーム", currency_bloc: "通貨ブロック" }[v]) },
    ],
    build: (v, ctx) => ({ nation: ctx, factor: v.factor }),
  },
  fog: {
    title: "霧（情報の不確実性）",
    fields: [
      { k: "value", label: "濃さ", type: "range", min: 0, max: 0.5, step: 0.05, def: 0,
        fmt: v => `${Math.round(v * 200)}%` },
    ],
    build: v => ({ param: "fog_of_war", value: +v.value }),
  },
  rate_hike: {
    title: "世界金利",
    fields: [
      { k: "value", label: "利上げ幅", type: "range", min: 0, max: 0.15, step: 0.005, def: 0.05, fmt: v => `${(v * 100).toFixed(1)}%` },
    ],
    build: v => ({ value: +v.value }),
  },
};

const SLIDERS = ["trade_efficiency", "food_yield", "energy_yield", "chips_yield",
                 "minerals_yield", "space_yield", "ai_aggression", "disinfo_intensity"];

export default function InterveneModal({ action, target, onRun, onClose }) {
  const def = ACTIONS[action];
  const [vals, setVals] = useState(() =>
    action === "global_sliders"
      ? Object.fromEntries(SLIDERS.map(p => [p, 1]))
      : Object.fromEntries((def?.fields || []).map(f => [f.k,
          f.def ?? (typeof f.options[0] === "object" ? f.options[0].value : f.options[0])])));
  const [ready, setReady] = useState(false);
  useEffect(() => { setReady(true); }, []);

  useEffect(() => {
    if (!ready) return;
    const onKey = e => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [ready, onClose]);

  if (!action) return null;

  function run() {
    if (action === "global_sliders") {
      SLIDERS.forEach(p => onRun("global_slider", { param: p, value: +vals[p] }));
    } else {
      onRun(action, def.build(vals, target));
    }
    onClose();
  }

  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        {action === "global_sliders" ? (
          <>
            <h2>世界パラメータ</h2>
            {SLIDERS.map(p => (
              <div key={p}>
                {P(p)}
                <input type="range" min="0.3" max="1.8" step="0.05" value={vals[p]}
                       onChange={e => setVals(v => ({ ...v, [p]: +e.target.value }))} />
                <b style={{ fontSize: 12 }}>{vals[p].toFixed(2)}</b>
              </div>
            ))}
          </>
        ) : (
          <>
            <h2>{def.title}</h2>
            {def.sub && <p className="modalsub">{def.sub(target ?? "")}</p>}
            {def.fields.map(f => (
              <div key={f.k}>
                {P(f.label)}
                {f.type === "range" ? (
                  <>
                    <input type="range" min={f.min} max={f.max} step={f.step}
                           value={vals[f.k]}
                           onChange={e => setVals(v => ({ ...v, [f.k]: +e.target.value }))} />
                    <b style={{ fontSize: 13 }}>{f.fmt ? f.fmt(vals[f.k]) : vals[f.k]}</b>
                  </>
                ) : f.type === "radio" ? (
                  <div className="radioopts">
                    {f.options.map(o => {
                      const val = typeof o === "object" ? o.value : o;
                      const label = typeof o === "object" ? o.label : (f.optionLabel ? f.optionLabel(o) : o);
                      const hint = typeof o === "object" ? o.hint : null;
                      return (
                        <label key={val} className="radioopt">
                          <input type="radio" name={f.k} checked={vals[f.k] === val}
                                 onChange={() => setVals(v => ({ ...v, [f.k]: val }))} />
                          <span className="radioopt-body">
                            <b>{label}</b>
                            {hint && <small>{hint}</small>}
                          </span>
                        </label>
                      );
                    })}
                  </div>
                ) : (
                  <select value={vals[f.k]}
                          onChange={e => setVals(v => ({ ...v, [f.k]: f.type === "select" ? e.target.value : +e.target.value }))}>
                    {f.options.map(o => (
                      <option key={o} value={o}>{f.optionLabel ? f.optionLabel(o) : o}</option>
                    ))}
                  </select>
                )}
              </div>
            ))}
          </>
        )}
        <div className="modalbtns">
          <button onClick={onClose}>やめる</button>
          <button className="go" onClick={run}>実行</button>
        </div>
      </div>
    </div>
  );
}
