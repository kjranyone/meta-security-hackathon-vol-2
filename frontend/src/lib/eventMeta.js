// イベント型の分類と日本語名(単一情報源)。
// タイムラインマーカーの4分類・tooltip表示がここを参照する。
// 注意: pulses.js(発光色)とaudio.js(音程)は同じ型を扱うが演出上の
// 別データであり、意図的にここには統合しない(値が用途別に調整済み)。
export const GROUP_OF = {
  war_start: "武力", mobilization: "武力", collapse: "武力", factor_acquired: "武力",
  price_spike: "経済危機", fx_crisis: "経済危機", sovereign_default: "経済危機",
  crash: "経済危機", collective_sanction: "経済危機",
  god_intervention: "介入",
  alliance_activation: "制度", factor_relinquished: "制度",
};
export const GROUP_COLOR = { 武力: "#f85149", 経済危機: "#e3b341", 介入: "#a371f7", 制度: "#7ee787" };
export const TYPE_JA = {
  war_start: "開戦", mobilization: "動員", collapse: "国家崩壊", factor_acquired: "因子取得",
  price_spike: "価格急騰", fx_crisis: "為替危機", sovereign_default: "債務不履行",
  crash: "GDP急落", collective_sanction: "集団制裁", god_intervention: "介入",
  alliance_activation: "同盟参戦", factor_relinquished: "因子放棄",
};
