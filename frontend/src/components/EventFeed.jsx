import { useState } from "react";
import { GROUP_OF } from "../lib/eventMeta";

const EV_CLS = {
  war_start: "ev-war", war_end: "ev-war", collapse: "ev-collapse",
  god_intervention: "ev-god", shortage: "ev-shortage", sanction: "ev-sanction",
  threat: "ev-sanction", alliance_formed: "ev-alliance", price_spike: "ev-price",
  disinfo: "ev-disinfo", trade_throttled: "ev-trade", sovereign_default: "ev-default", fx_crisis: "ev-price", factor_acquired: "ev-war", factor_relinquished: "ev-alliance", collective_sanction: "ev-sanction", alliance_activation: "ev-alliance",
  credibility_hit: "ev-credhit", tech_emergence: "ev-tech", tech_adopted: "ev-tech2",
  mobilization: "ev-mobilization", stand_down: "ev-standdown",
};

export function EventRow({ e }) {
  return (
    <div className={`ev ${EV_CLS[e.type] || ""}`}>
      <span className="t">t{e.tick}</span>{e.text}
    </div>
  );
}

// feed: 現在tickまでのイベント(新しい順)。godEvents: 介入(先頭表示)。
// 主要イベント(武力/経済危機/介入/制度)を優先表示し、政策・技術などの
// 定常ログは折りたたむ — 洪水で本質的な事件が埋まるのを防ぐ。
export default function EventFeed({ events, godEvents = [], counts }) {
  const [showMinor, setShowMinor] = useState(false);
  const all = [...(godEvents || []).slice(-8).reverse(), ...(events || []).slice().reverse()];
  const major = all.filter(e => GROUP_OF[e.type]);
  const minor = all.filter(e => !GROUP_OF[e.type]);
  return (
    <div className="pane feed">
      <h3>イベント {counts ? <span style={{ color: "var(--accent)" }}>{counts}</span> : null}</h3>
      {major.length > 0
        ? major.map((e, i) => <EventRow key={`${e.id || i}-${i}`} e={e} />)
        : minor.length > 0 && <div className="cardhint">（主要イベントはまだ発生していません — 政策・技術ログは下から）</div>}
      {minor.length > 0 && (
        <div className="feedtoggle" onClick={() => setShowMinor(s => !s)}>
          {showMinor ? "▾" : "▸"} 政策・技術ログ ほか（{minor.length}件）
        </div>
      )}
      {showMinor && minor.slice(0, 150).map((e, i) => <EventRow key={`m-${e.id || i}-${i}`} e={e} />)}
      {!major.length && !minor.length && <div className="cardhint">（イベント待ち）</div>}
    </div>
  );
}
