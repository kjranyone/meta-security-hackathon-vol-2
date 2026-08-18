const EV_CLS = {
  war_start: "ev-war", war_end: "ev-war", collapse: "ev-collapse",
  god_intervention: "ev-god", shortage: "ev-shortage", sanction: "ev-sanction",
  threat: "ev-sanction", alliance_formed: "ev-alliance", price_spike: "ev-price",
  disinfo: "ev-disinfo", trade_throttled: "ev-trade", sovereign_default: "ev-default", fx_crisis: "ev-price", factor_acquired: "ev-war", factor_relinquished: "ev-alliance", collective_sanction: "ev-sanction",
  credibility_hit: "ev-credhit", tech_emergence: "ev-tech", tech_adopted: "ev-tech2",
};

export function EventRow({ e }) {
  return (
    <div className={`ev ${EV_CLS[e.type] || ""}`}>
      <span className="t">t{e.tick}</span>{e.text}
    </div>
  );
}

// feed: 現在tickまでのイベント（新しい順）。godEvents: 神の介入（先頭表示）
export default function EventFeed({ events, godEvents = [], counts }) {
  const body = [...(godEvents || []).slice(-8).reverse(), ...(events || []).slice().reverse()];
  return (
    <div className="pane feed">
      <h3>Event cascade {counts ? <span style={{ color: "var(--accent)" }}>{counts}</span> : null}</h3>
      {body.length
        ? body.map((e, i) => <EventRow key={`${e.id || i}-${i}`} e={e} />)
        : <div className="cardhint">（イベント待ち）</div>}
    </div>
  );
}
