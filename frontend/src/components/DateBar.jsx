import { simDate } from "../lib/calendar";

export default function DateBar({ tick, maxTick, frac = 0.5, visible }) {
  if (!visible || tick == null) return null;
  return (
    <div className="datebar">
      {simDate(tick, frac)}
      <small>tick {tick} / {maxTick ?? "?"}（1tick=1時間・分は演出）</small>
    </div>
  );
}
