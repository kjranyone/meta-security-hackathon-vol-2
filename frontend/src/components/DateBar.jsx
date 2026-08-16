import { simDate } from "../lib/calendar";

// 世界時計チップ（タイムライン内の固定スロット。地図には重ならない）
export default function DateBar({ tick, frac = 0, suffix = "" }) {
  if (tick == null) return null;
  return (
    <span className="datechip">
      {simDate(tick, frac)}<small> · t{tick}{suffix}</small>
    </span>
  );
}
