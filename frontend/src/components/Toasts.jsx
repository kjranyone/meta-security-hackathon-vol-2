import { useRef, useState, useCallback } from "react";

const ICON = {
  sovereign_default: "🏦💥", war_start: "⚔️", war_end: "🕊️", collapse: "💀",
  price_spike: "📈", god_intervention: "⚡", tech_emergence: "🔬",
  disinfo: "📰", alliance_formed: "🤝", sanction: "🚫", crash: "📉",
};
const COLOR = {
  sovereign_default: "#ff6b35", war_start: "#f85149", war_end: "#3fb950",
  collapse: "#d29922", price_spike: "#e3b341", god_intervention: "#a371f7",
  tech_emergence: "#3fdeff", disinfo: "#f778ba", alliance_formed: "#3fb950",
  sanction: "#d29922", crash: "#e5534b",
};

export function useToasts() {
  const [toasts, setToasts] = useState([]);
  const idRef = useRef(0);
  const push = useCallback((type, text) => {
    const id = ++idRef.current;
    setToasts(ts => [...ts.slice(-3), { id, type, text: text.slice(0, 90) }]);
    setTimeout(() => setToasts(ts => ts.filter(t => t.id !== id)), 4000);
  }, []);
  return { toasts, push };
}

export default function Toasts({ toasts }) {
  return (
    <div className="toasts">
      {toasts.map(t => (
        <div key={t.id} className="toast" style={{ borderLeftColor: COLOR[t.type] || "#58a6ff" }}>
          <span className="toast-icon">{ICON[t.type] || "📢"}</span>
          <span>{t.text}</span>
        </div>
      ))}
    </div>
  );
}
