export default function StatsTable({ tick, selected, onSelect, showStocks = false }) {
  if (!tick) return <div className="pane"><h3>Nations</h3><div>—</div></div>;
  const m = tick.metrics;
  const rows = Object.entries(tick.nations).map(([nid, n]) => {
    const st = n.stocks;
    return (
      <tr key={nid} className={`statrow${selected === nid ? " sel" : ""}`} onClick={() => onSelect?.(nid)}>
        <td><span style={{ color: n.color }}>●</span> {n.name}{n.collapsed ? " 💀" : ""}{n.at_war_with?.length ? " ⚔️" : ""}</td>
        <td className="num">{n.gdp.toFixed(1)}</td>
        <td className="num">{(n.inflation * 100).toFixed(1)}%</td>
        <td className="num">{n.stability.toFixed(0)}</td>
        <td className="num" style={{ color: n.debt_gdp > 130 ? "#f85149" : n.debt_gdp > 100 ? "#e3b341" : "inherit" }}>
          {n.debt_gdp.toFixed(0)}%{n.defaults ? "⚠" + n.defaults : ""}
        </td>
        {showStocks && (
          <td className="num">{st.energy?.toFixed(1)}/{st.food?.toFixed(1)}/{st.chips?.toFixed(1)}/{st.minerals?.toFixed(1)}/{st.space?.toFixed(1)}</td>
        )}
      </tr>
    );
  });
  return (
    <div className="pane" style={{ flex: "none" }}>
      <h3>Nations</h3>
      <table>
        <thead>
          <tr>
            <th></th><th>GDP</th><th>物価↑</th><th>安定</th><th>債務</th>
            {showStocks && <th>備蓄 E/F/C/M/S</th>}
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
      <div style={{ marginTop: 6, color: "var(--dim)" }}>
        世界GDP <b style={{ color: "var(--text)" }}>{m.world_gdp.toFixed(1)}</b>
        ・平均安定 <b style={{ color: "var(--text)" }}>{m.mean_stability.toFixed(1)}</b>
        ・戦争 <b style={{ color: "var(--text)" }}>{m.wars}</b>
        ・崩壊 <b style={{ color: "var(--text)" }}>{m.collapsed}</b>
        ・平均インフレ <b style={{ color: "var(--text)" }}>{(m.mean_inflation * 100).toFixed(1)}%</b>
        ・平均債務 <b style={{ color: "var(--text)" }}>{(m.mean_debt_gdp || 0).toFixed(0)}%</b>
        ・破綻 <b style={{ color: m.defaults > 0 ? "#ff6b35" : "var(--text)" }}>{m.defaults || 0}</b>
      </div>
    </div>
  );
}
