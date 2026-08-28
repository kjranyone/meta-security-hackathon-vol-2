import { MAJOR_COLOR } from "./audio";

// replay.jsonl テキスト → { META, TICKS }
export function ingestReplay(text) {
  let META = null;
  const TICKS = [];
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    let obj;
    try { obj = JSON.parse(line); } catch { continue; }
    if (obj.type === "meta") META = obj;
    else if (obj.type === "tick") TICKS.push(obj);
  }
  return { META, TICKS };
}

// 主要イベントtick → マーカー色（破綻/開戦/崩壊/急騰/介入/月次GDP急落-1.5%超）
export function computeMajor(TICKS) {
  const MAJOR = {};
  let prevGdp = null;
  for (const t of TICKS) {
    for (const e of t.events || []) {
      if (MAJOR_COLOR[e.type]) { MAJOR[t.tick] = MAJOR_COLOR[e.type]; break; }
    }
    if (!MAJOR[t.tick] && prevGdp !== null && t.metrics?.world_gdp < prevGdp * 0.985)
      MAJOR[t.tick] = MAJOR_COLOR.crash;
    prevGdp = t.metrics?.world_gdp ?? prevGdp;
  }
  return MAJOR;
}
