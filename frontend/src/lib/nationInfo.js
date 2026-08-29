// 国家ホバーtooltip用の要約(tick.nationsから現在値を整形)
export function nationInfo(nid, tick) {
  const n = tick?.nations?.[nid];
  if (!n) return null;
  return {
    name: n.name || nid,
    collapsed: !!n.collapsed,
    atWar: (n.at_war_with || []).join("・") || "なし",
    allies: (n.alliances || []).join("・") || "なし",
    gdp: n.gdp, stability: n.stability, military: n.military,
    debt: n.debt_gdp, infl: ((n.inflation || 0) * 100).toFixed(1),
    stocks: n.stocks || {},
  };
}
