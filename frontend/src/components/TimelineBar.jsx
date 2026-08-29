import { useEffect, useMemo, useRef } from "react";
import DateBar from "./DateBar";

// タイムライン上の主要イベントマーカー。
// 色は10種類のイベント型を4分類に集約する — 色だけで意味が読めること:
//   武力(赤): 開戦・動員・崩壊・核取得  経済危機(黄): 価格急騰・為替・債務不履行・GDP急落
//   介入(紫): プレイヤー介入           制度(緑): 同盟参戦・因子放棄
// マーカーは押せる: クリックでそのtickへscrub。ホバーで事件の内訳。
const GROUP_OF = {
  war_start: "武力", mobilization: "武力", collapse: "武力", factor_acquired: "武力",
  price_spike: "経済危機", fx_crisis: "経済危機", sovereign_default: "経済危機",
  crash: "経済危機", collective_sanction: "経済危機",
  god_intervention: "介入",
  alliance_activation: "制度", factor_relinquished: "制度",
};
const GROUP_COLOR = { 武力: "#f85149", 経済危機: "#e3b341", 介入: "#a371f7", 制度: "#7ee787" };
const TYPE_JA = {
  war_start: "開戦", mobilization: "動員", collapse: "国家崩壊", factor_acquired: "因子取得",
  price_spike: "価格急騰", fx_crisis: "為替危機", sovereign_default: "債務不履行",
  crash: "GDP急落", collective_sanction: "集団制裁", god_intervention: "介入",
  alliance_activation: "同盟参戦", factor_relinquished: "因子放棄",
};

export default function TimelineBar({ playing, onTogglePlay, cur, ticks, major,
                                      onScrub, speed, onSpeed, muted, onMute, flashCount, clockFrac = 0 }) {
  const tlRef = useRef(null);
  useEffect(() => {
    if (!flashCount) return;
    const el = tlRef.current;
    if (!el) return;
    el.classList.remove("flash");
    void el.offsetWidth;
    el.classList.add("flash");
  }, [flashCount]);

  const last = ticks.length ? ticks[ticks.length - 1].tick : 1;
  const marks = useMemo(() => Object.entries(major || {})
    .map(([t, type]) => {
      const tick = +t;
      const idx = ticks.findIndex(x => x.tick === tick);
      // そのtickの主要イベント内訳(ホバー用)
      const ev = (ticks[idx]?.events || []).filter(e => GROUP_OF[e.type]);
      const counts = {};
      ev.forEach(e => { counts[e.type] = (counts[e.type] || 0) + 1; });
      const summary = Object.entries(counts)
        .map(([ty, n]) => `${TYPE_JA[ty] || ty}${n > 1 ? `×${n}` : ""}`).join("・");
      const group = GROUP_OF[type] || "経済危機";
      return { tick, idx, group, color: GROUP_COLOR[group], summary };
    })
    .filter(m => m.idx >= 0)
    .sort((a, b) => a.tick - b.tick), [major, ticks]);

  const curTick = ticks[cur]?.tick ?? -1;
  return (
    <div className="timeline" ref={tlRef}>
      <button className="tlbtn" onClick={onTogglePlay}>{playing ? "⏸ 停止" : "▶ 再生"}</button>
      <div className="tlwrap">
        <div className="tlmarks">
          {marks.map(m => (
            <button key={m.tick} className={`tlmark${flashCount && m.tick === curTick ? " hit" : ""}`}
                 style={{ left: `${(100 * m.tick) / last}%`, background: m.color, color: m.color }}
                 title={`t${m.tick} — ${m.summary || GROUP_OF[major?.[m.tick]] || ""}`}
                 onClick={() => onScrub(m.idx)} />
          ))}
        </div>
        <input type="range" min="0" max={Math.max(0, ticks.length - 1)} value={cur}
               onChange={e => onScrub(+e.target.value)} />
        <div className="tllegend">
          {Object.entries(GROUP_COLOR).map(([g, c]) => (
            <span key={g}><i style={{ background: c }} />{g}</span>
          ))}
          <span className="hint">●を押すとその時点へ</span>
        </div>
      </div>
      <DateBar tick={ticks[cur]?.tick} suffix={` / ${last}`} />
      <label className="speedlabel">速度
        <input type="range" min="1" max="10" value={speed} onChange={e => onSpeed(+e.target.value)} />
      </label>
      <button className="tlbtn mutebtn" onClick={onMute} title="イベント音の切替">{muted ? "♪" : "♪♪"}</button>
    </div>
  );
}
