// シミュレーション内暦: tick0 = 西暦2026年8月 (1 tick = 1ヶ月)。
// 日・時刻は演出(frac 0..1 で月内を進む)。
export const SIM_MONTH0 = 2026 * 12 + 7;

export function simDate(tick, frac = 0.5) {
  const total = SIM_MONTH0 + tick;
  const y = Math.floor(total / 12), m = total % 12 + 1;
  const day = 1 + Math.floor(27 * frac);
  const hh = Math.floor(24 * frac), mm = Math.floor(60 * (24 * frac - hh));
  const p2 = n => String(n).padStart(2, "0");
  return `西暦${y}年${m}月${day}日 ${p2(hh)}:${p2(mm)}`;
}
