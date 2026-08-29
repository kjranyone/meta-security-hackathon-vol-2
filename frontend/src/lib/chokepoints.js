// 地図ホバーtooltipの内容(海峡・国家で共通の {head, badge, lines, note} 形状)
const JA = {
  "Strait of Hormuz": "ホルムズ海峡",
  "Strait of Malacca": "マラッカ海峡",
  "Taiwan Strait": "台湾海峡",
  "Bab el-Mandeb": "バブ・エル・マンデブ海峡",
  "Suez Canal": "スエズ運河",
  "Panama Canal": "パナマ運河",
  "Turkish Straits": "トルコ海峡",
};
const COMMODITY_JA = { energy: "エネルギー", food: "食料", chips: "半導体",
                       minerals: "鉱物", space: "宇宙" };

export function chokeInfo(name, tick, meta) {
  const routes = (meta?.geo?.routes || []).filter(r => (r.chokepoints || []).includes(name));
  const importers = [...new Set(routes.map(r => r.importer))];
  const commodities = {};
  routes.forEach(r => { commodities[r.commodity] = (commodities[r.commodity] || 0) + 1; });
  const commStr = Object.entries(commodities)
    .map(([c, n]) => `${COMMODITY_JA[c] || c}${n > 1 ? `×${n}` : ""}`).join("・") || "なし";
  const closed = !!(tick?.chokepoints?.[name]);
  return {
    head: JA[name] || name,
    badge: closed ? "封鎖中" : "開通",
    badgeClass: closed ? "cp-closed" : "cp-open",
    lines: [
      `経由航路 ${routes.length}本（${commStr}）`,
      `主な輸入国: ${importers.slice(0, 5).join("・") || "—"}${importers.length > 5 ? " ほか" : ""}`,
    ],
    note: "封鎖すると経由航路の輸送力が約10日がかりで目減いし、価格・備蓄へ波及します",
  };
}

export function nationInfo(nid, tick) {
  const n = tick?.nations?.[nid];
  if (!n) return null;
  return {
    head: n.name || nid,
    badge: n.collapsed ? "崩壊" : null,
    badgeClass: "cp-closed",
    lines: [
      `GDP ${n.gdp}T・安定 ${n.stability}・軍事 ${n.military}`,
      `債務 ${n.debt_gdp}%・インフレ ${((n.inflation || 0) * 100).toFixed(1)}%`,
      `戦争: ${(n.at_war_with || []).join("・") || "なし"} / 同盟: ${(n.alliances || []).join("・") || "なし"}`,
    ],
    note: "クリックで統計表で選択(介入モードでは介入対象になる)",
  };
}
