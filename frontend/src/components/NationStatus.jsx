// 選択国の状態（対象バナー直下に常時表示。実値のみ）
export default function NationStatus({ n }) {
  if (!n) return null;
  const st = n.stocks;
  const rows = [
    ["GDP", `${n.gdp.toFixed(1)}兆$`],
    ["物価", `${(n.inflation * 100).toFixed(1)}%`],
    ["安定", n.stability.toFixed(0)],
    ["債務", `${n.debt_gdp.toFixed(0)}%`],
    ["信用", n.credibility.toFixed(0)],
    ["軍事", n.military.toFixed(0)],
    ["破綻", `${n.defaults}回`],
    ["備蓄", `${st.energy?.toFixed(1) ?? "-"}/${st.food?.toFixed(1) ?? "-"}/${st.chips?.toFixed(1) ?? "-"}/${st.minerals?.toFixed(1) ?? "-"}/${st.space?.toFixed(1) ?? "-"}`],
    ["技術", `${(n.techs || []).length}`],
    ["戦争", n.at_war_with?.length ? n.at_war_with.join(", ") : "—"],
  ];
  return (
    <div className="statrows" style={{ marginBottom: 8 }}>
      {rows.map(([k, v]) => (
        <div className="statrow-line" key={k}><span>{k}</span><b>{v}</b></div>
      ))}
    </div>
  );
}
