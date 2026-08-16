// 価格・指標チャートの canvas 描画（元実装の移植、2x解像度で鮮明化）
export const SERIES_COLORS = {
  price_energy: "#e3b341", price_food: "#7cb342", price_chips: "#58a6ff",
  mean_stability: "#f778ba", world_gdp: "#a371f7",
};

export function renderChart(ctx, cv, TICKS) {
  const W = cv.width, H = cv.height;
  ctx.clearRect(0, 0, W, H);
  if (!TICKS.length) return;
  const keys = Object.keys(SERIES_COLORS);
  const max = {};
  for (const k of keys) max[k] = Math.max(...TICKS.map(t => t.metrics[k] ?? 0), 1e-9);
  const x0 = 40, x1 = W - 8, y0 = 10, y1 = H - 18;
  ctx.strokeStyle = "#30363d";
  for (let g = 0; g <= 4; g++) {
    const y = y0 + ((y1 - y0) * g) / 4;
    ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke();
  }
  const x = i => x0 + ((x1 - x0) * i) / Math.max(1, TICKS.length - 1);
  const y = (k, v) => y1 - ((y1 - y0) * v) / max[k];
  ctx.font = `${10 * 2}px sans-serif`;
  ctx.fillStyle = "#8b949e";
  ctx.textAlign = "right";
  for (const k of keys) {
    ctx.fillStyle = SERIES_COLORS[k];
    ctx.fillText(fmt(k, max[k]), x0 - 6, y(k, max[k]) + 4);
  }
  for (const k of keys) {
    ctx.strokeStyle = SERIES_COLORS[k];
    ctx.lineWidth = 2.2;
    ctx.beginPath();
    TICKS.forEach((t, i) => {
      const px = x(i), py = y(k, t.metrics[k] ?? 0);
      i ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
    });
    ctx.stroke();
  }
  ctx.fillStyle = "#8b949e";
  ctx.textAlign = "left";
  ctx.fillText(`t${TICKS[0].tick}`, x0, H - 6);
  ctx.textAlign = "right";
  ctx.fillText(`t${TICKS[TICKS.length - 1].tick}`, x1, H - 6);
}

function fmt(k, v) {
  const name = { price_energy: "エネルギー", price_food: "食料", price_chips: "半導体",
                 mean_stability: "安定", world_gdp: "世界GDP" }[k] || k;
  return `${name} ${v >= 100 ? v.toFixed(0) : v.toFixed(1)}`;
}
