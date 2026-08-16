// シミュレーション内暦: 1 tick = 1時間（RTS風の超加速世界時計）。
// tick0 = 西暦2026年8月1日 00:00。分は演出（frac 0..1 で時間内を進む）。
export const SIM_T0 = Date.UTC(2026, 7, 1);

const p2 = n => String(n).padStart(2, "0");

export function simDate(tick, frac = 0) {
  const d = new Date(SIM_T0 + (tick + frac) * 3600e3);
  return `西暦${d.getUTCFullYear()}年${d.getUTCMonth() + 1}月${d.getUTCDate()}日 ${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}`;
}
