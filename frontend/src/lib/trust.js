import { project } from "./projection";

// 友好度 → 色。20=中立(薄灰)を挟んで 0=敵対(赤) ~ 100=友好(緑)
export function trustColor(t) {
  const d = t - 20;
  const hue = d >= 0 ? Math.min(120, d * 1.5) : 0;
  const sat = Math.min(95, 15 + Math.abs(d) * 1.1);
  const light = d >= 0 ? 45 - Math.min(18, d * 0.2) : 48;
  return `hsla(${hue}, ${sat}%, ${light}%, ${Math.min(0.9, 0.25 + Math.abs(d) / 90)})`;
}

// 描画用エッジリストを計算（renderMap が弧を引く）
// selected: 国家ID | null。未選択なら主要な友好・対抗関係のみ。
export function computeTrustEdges(tick, geoNations, selected) {
  const nations = tick.nations;
  if (!geoNations || !Object.values(nations).some(n => n.trust)) return [];
  const pos = {};
  for (const [nid, info] of Object.entries(geoNations))
    if (nations[nid] && !nations[nid].collapsed) pos[nid] = project(...info.centroid);

  const out = [];
  if (selected && nations[selected]) {
    for (const [oid, t] of Object.entries(nations[selected].trust || {}))
      if (pos[oid])
        out.push({ a: selected, b: oid, color: trustColor(t), width: 0.8 + Math.abs(t - 20) / 45 });
    return out;
  }
  const pairs = [];
  for (const a of Object.keys(pos)) {
    const tr = nations[a].trust || {};
    for (const b of Object.keys(tr))
      if (a < b && pos[b])
        pairs.push({ a, b, mean: (tr[b] + (nations[b].trust?.[a] ?? 20)) / 2 });
  }
  pairs.sort((x, y) => y.mean - x.mean);
  for (const p of pairs.slice(0, 6))
    out.push({ ...p, color: trustColor(p.mean), width: 2.2, dash: [7, 5] });
  for (const p of pairs.slice(-6))
    if (p.mean < 20) out.push({ ...p, color: trustColor(p.mean), width: 2.2 });
  return out.filter(e => pos[e.a] && pos[e.b]).map(e => ({
    ...e, a: pos[e.a], b: pos[e.b],
  }));
}
