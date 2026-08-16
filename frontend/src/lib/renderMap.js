import { project, unproject } from "./projection";
import { computeTrustEdges } from "./trust";

export const COMMO_COLOR = {
  energy: "rgba(227,179,65,.5)", food: "rgba(124,179,66,.5)", chips: "rgba(88,166,255,.5)",
  minerals: "rgba(210,168,255,.5)", space: "rgba(63,222,255,.5)",
};
const COMMO_CLOSED = "rgba(248,81,73,.65)";

// 統一地図レンダラ（神の玉座・リプレイビューア共通）
// opts: { geo, meta, selectedNation, selectedChokepoint, showRoutes }
export function renderMap(ctx, cv, tick, opts) {
  const { geo, meta, selectedNation, selectedChokepoint, showRoutes = true } = opts;
  ctx.clearRect(0, 0, cv.width, cv.height);
  ctx.fillStyle = "#0e2233";
  ctx.fillRect(0, 0, cv.width, cv.height);
  if (!geo || !meta?.geo) return;

  const nations = tick.nations;
  const claim = new Map();
  for (const [nid, info] of Object.entries(meta.geo.nations))
    for (const g of info.geo_ids || []) {
      const idx = geo.byName[g];
      if (idx !== undefined) claim.set(idx, nid);
    }
  const collapsed = new Set(Object.entries(nations).filter(([, n]) => n.collapsed).map(([id]) => id));

  // 陸地（領土塗り。崩壊国は暗転）
  ctx.strokeStyle = "rgba(13,17,23,.9)";
  ctx.lineWidth = 1;
  geo.features.forEach((f, idx) => {
    const nid = claim.get(idx);
    ctx.beginPath();
    for (const ring of f.rings)
      ring.forEach(([lon, lat], k) => {
        const [x, y] = project(lon, lat);
        k ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      });
    ctx.closePath();
    if (nid && nations[nid]) {
      ctx.fillStyle = nations[nid].color;
      ctx.fill();
      if (collapsed.has(nid)) { ctx.fillStyle = "rgba(13,17,23,.55)"; ctx.fill(); }
    } else {
      ctx.fillStyle = "#22303c";
      ctx.fill();
    }
    ctx.stroke();
  });

  // 航路
  if (showRoutes) {
    for (const r of meta.geo.routes) {
      const imp = meta.geo.nations[r.importer], exp = meta.geo.nations[r.exporter];
      if (!imp || !exp) continue;
      const anyClosed = (r.chokepoints || []).some(n => tick.chokepoints?.[n]);
      const [x1, y1] = project(...exp.centroid), [x2, y2] = project(...imp.centroid);
      const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
      const lift = Math.min(60, Math.hypot(x2 - x1, y2 - y1) * 0.18);
      const sign = my < cv.height / 2 ? -1 : 1;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.quadraticCurveTo(mx, my + lift * sign, x2, y2);
      if (anyClosed) {
        ctx.strokeStyle = COMMO_CLOSED; ctx.setLineDash([5, 4]); ctx.lineWidth = 1.8;
      } else {
        ctx.strokeStyle = COMMO_COLOR[r.commodity] || "rgba(200,200,200,.35)";
        ctx.setLineDash([]); ctx.lineWidth = 1.2;
      }
      ctx.stroke(); ctx.setLineDash([]);
    }
  }

  // 友好度グラフ
  for (const e of computeTrustEdges(tick, meta.geo.nations, selectedNation)) {
    const { a: [x1, y1], b: [x2, y2] } = e;
    const lift = Math.min(50, Math.hypot(x2 - x1, y2 - y1) * 0.16);
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.quadraticCurveTo((x1 + x2) / 2, (y1 + y2) / 2 - lift, x2, y2);
    ctx.strokeStyle = e.color; ctx.lineWidth = e.width;
    ctx.setLineDash(e.dash || []); ctx.stroke(); ctx.setLineDash([]);
  }

  // 海峡（円輪。封鎖=赤+斜線、選択=白強調）
  for (const cp of meta.geo.chokepoints) {
    const [x, y] = project(cp.lon, cp.lat);
    const closed = !!tick.chokepoints?.[cp.name];
    const selHere = selectedChokepoint === cp.name;
    ctx.beginPath();
    ctx.arc(x, y, 8, 0, Math.PI * 2);
    ctx.strokeStyle = selHere ? "#ffffff" : closed ? "#f85149" : "rgba(255,255,255,.55)";
    ctx.lineWidth = selHere ? 2.4 : closed ? 2 : 1.2;
    ctx.stroke();
    if (closed) {
      ctx.beginPath();
      ctx.moveTo(x - 5.5, y + 5.5);
      ctx.lineTo(x + 5.5, y - 5.5);
      ctx.strokeStyle = "#f85149";
      ctx.stroke();
    }
    ctx.lineWidth = 1;
  }

  // 国家ラベル（選択=白輪・戦争=赤輪・破綻=橙輪・崩壊=ラベル減光）
  for (const [nid, n] of Object.entries(nations)) {
    const info = meta.geo.nations[nid];
    if (!info) continue;
    const [x, y] = project(...info.centroid);
    const hasLand = (info.geo_ids || []).some(g => geo.byName[g] !== undefined);
    if (!hasLand) {
      ctx.beginPath(); ctx.arc(x, y, 9, 0, Math.PI * 2);
      ctx.fillStyle = n.color; ctx.fill();
      ctx.strokeStyle = "rgba(255,255,255,.6)"; ctx.stroke();
    }
    ctx.font = "600 11px sans-serif"; ctx.textAlign = "center";
    ctx.fillStyle = "rgba(255,255,255,.9)";
    ctx.fillText(n.name, x, y + 20);
    if (selectedNation === nid) {
      ctx.beginPath(); ctx.arc(x, y, 16, 0, Math.PI * 2);
      ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 2; ctx.stroke(); ctx.lineWidth = 1;
    } else if (n.at_war_with?.length) {
      ctx.beginPath(); ctx.arc(x, y, 14, 0, Math.PI * 2);
      ctx.strokeStyle = "#f85149"; ctx.lineWidth = 1.4; ctx.stroke(); ctx.lineWidth = 1;
    }
    if (n.defaults > 0) {
      ctx.beginPath(); ctx.arc(x, y, 11, 0, Math.PI * 2);
      ctx.strokeStyle = "#ff6b35"; ctx.lineWidth = 1.2; ctx.stroke(); ctx.lineWidth = 1;
    }
    if (n.collapsed) ctx.fillStyle = "rgba(139,148,158,.75)";
  }
}

// クリック位置から国家/海峡を解決（神UIの選択ロジック）
// returns {kind:"cp", id} | {kind:"nation", id} | {kind:null, id:null}
export function pickAt(mx, my, geo, meta, cvScale = 1) {
  let best = null, bd = 14;
  for (const cp of meta.geo.chokepoints || []) {
    const [x, y] = project(cp.lon, cp.lat);
    const d = Math.hypot(x - mx, y - my);
    if (d < bd) { bd = d; best = cp; }
  }
  if (best) return { kind: "cp", id: best.name };
  best = null; bd = 16;
  for (const [nid, info] of Object.entries(meta.geo.nations)) {
    const [x, y] = project(...info.centroid);
    const d = Math.hypot(x - mx, y - my);
    if (d < bd) { bd = d; best = nid; }
  }
  if (best) return { kind: "nation", id: best };
  const [lon, lat] = unproject(mx, my);
  const idx = geo.features.findIndex(f => f.rings.some(ring => pointInRing(lon, lat, ring)));
  if (idx >= 0) {
    const claim = new Map();
    for (const [nid, info] of Object.entries(meta.geo.nations))
      for (const g of info.geo_ids || []) {
        const gi = geo.byName[g];
        if (gi !== undefined) claim.set(gi, nid);
      }
    const nid = claim.get(idx);
    if (nid) return { kind: "nation", id: nid };
  }
  return { kind: null, id: null };
}

export function pointInRing(x, y, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
