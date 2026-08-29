import { useEffect, useMemo, useRef } from "react";
import { GROUP_OF, GROUP_COLOR, TYPE_JA } from "../lib/eventMeta";
import DateBar from "./DateBar";

// タイムライン上の主要イベントマーカー。
// 色は10種類のイベント型を4分類に集約する — 色だけで意味が読めること:
//   武力(赤): 開戦・動員・崩壊・核取得  経済危機(黄): 価格急騰・為替・債務不履行・GDP急落
//   介入(紫): プレイヤー介入           制度(緑): 同盟参戦・因子放棄
// マーカーは押せる: クリックでそのtickへscrub。ホバーで事件の内訳。

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
  // 未来のネタバレをしない: マーカーは再生ヘッドより過去(既に見たtick)のみ表示。
  // リプレイをゼロから見る者は未来を知らない — 事件は通り過ぎた時に初めて見える
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
    .filter(m => m.idx >= 0 && m.idx <= cur)
    .sort((a, b) => a.tick - b.tick), [major, ticks, cur]);

  const curTick = ticks[cur]?.tick ?? -1;
  return (
    <div className="timeline" ref={tlRef}>
      <button className="tlbtn" onClick={onTogglePlay}>{playing ? "⏸ 停止" : "▶ 再生"}</button>
      <div className="tlwrap">
        <div className="tlmarks">
          {marks.map(m => (
            <button key={m.tick} className={`tlmark${flashCount && m.tick === curTick ? " hit" : ""}`}
                 style={{ left: `calc(7px + (100% - 14px) * ${m.tick / Math.max(1, last)})`,
                          background: m.color, color: m.color }}
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
          <span className="hint">●は既に起きた事件(押すとその時点へ)</span>
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
