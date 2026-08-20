// 国家AIのプラットフォーム表示名（プレイヤー視点。値はエンジンのpolicy識別子）
export const POLICY_LABELS = {
  heuristic: "標準AI（高速・完全予測可能）",
  llm: "思考AI（z.ai GLM・低速・要APIキー）",
  rl: "学習AI（学習済み国家へ自動適用）",
};
export const policyLabel = v => POLICY_LABELS[v] || v;
