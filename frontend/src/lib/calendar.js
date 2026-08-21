// シミュレーション内暦。tick0 = 西暦2026年8月1日 00:00。
// 1tickの実時間はサーバーの時計設定(meta.clock.hours_per_tick)に従う:
//   神モード = 1時間/tick(RTS)、実験リプレイ = 720時間/tick(月次圧縮)。
export const SIM_T0 = Date.UTC(2026, 7, 1);

let HPT = 1;
export function setClock(hoursPerTick) { HPT = Math.max(0.01, +hoursPerTick || 1); }
export function clockHours(tick, frac = 0) { return (tick + frac) * HPT; }

const p2 = n => String(n).padStart(2, "0");

export function simDate(tick, frac = 0) {
  const d = new Date(SIM_T0 + (tick + frac) * HPT * 3600e3);
  const days = (tick + frac) * HPT / 24;
  if (days < 2) {
    return `西暦${d.getUTCFullYear()}年${d.getUTCMonth() + 1}月${d.getUTCDate()}日 ${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}`;
  }
  return `西暦${d.getUTCFullYear()}年${d.getUTCMonth() + 1}月${d.getUTCDate()}日`;
}
