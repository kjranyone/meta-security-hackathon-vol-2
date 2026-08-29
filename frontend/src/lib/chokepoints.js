// 海峡(chokepoint)のホバー情報。日本語名と、その世界の航路定義から
// 「何がどれだけこの海峡に依存しているか」を集計する。
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

export function chokeJa(name) {
  return JA[name] || name;
}

export function chokeInfo(name, tick, meta) {
  const routes = (meta?.geo?.routes || []).filter(r => (r.chokepoints || []).includes(name));
  const importers = [...new Set(routes.map(r => r.importer))];
  const commodities = {};
  routes.forEach(r => { commodities[r.commodity] = (commodities[r.commodity] || 0) + 1; });
  const commStr = Object.entries(commodities)
    .map(([c, n]) => `${COMMODITY_JA[c] || c}${n > 1 ? `×${n}` : ""}`).join("・") || "なし";
  return {
    ja: chokeJa(name),
    closed: !!(tick?.chokepoints?.[name]),
    routeCount: routes.length,
    importers: importers.slice(0, 5).join("・") + (importers.length > 5 ? " ほか" : ""),
    commodities: commStr,
  };
}
