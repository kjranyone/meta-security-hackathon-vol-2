import { useEffect, useRef } from "react";
import DateBar from "./DateBar";

// 再生/scrub/マーカー/速度/ミュート。viewer向け（全TICKSが既知）。
// flashCount が増えるたび発光アニメを再生する
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
  const marks = Object.entries(major || {});
  const curTick = ticks[cur]?.tick ?? -1;
  return (
    <div className="timeline" ref={tlRef}>
      <button className="tlbtn" onClick={onTogglePlay}>{playing ? "⏸ 停止" : "▶ 再生"}</button>
      <div className="tlwrap">
        <div className="tlmarks">
          {marks.map(([t, color]) => (
            <div key={t} className={`tlmark${flashCount && +t === curTick ? " hit" : ""}`}
                 style={{ left: `${(100 * t) / last}%`, background: color, color }}
                 title={`t${t}`} />
          ))}
        </div>
        <input type="range" min="0" max={Math.max(0, ticks.length - 1)} value={cur}
               onChange={e => onScrub(+e.target.value)} />
      </div>
      <DateBar tick={ticks[cur]?.tick} frac={playing ? clockFrac : 0} suffix={` / ${last}`} />
      <label className="speedlabel">速度
        <input type="range" min="1" max="10" value={speed} onChange={e => onSpeed(+e.target.value)} />
      </label>
      <button className="tlbtn mutebtn" onClick={onMute} title="イベント音の切替">{muted ? "🔇" : "🔊"}</button>
    </div>
  );
}
