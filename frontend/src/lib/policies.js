// 国家AIのプラットフォーム表示名（プレイヤー視点。値はエンジンのpolicy識別子）
export const POLICY_LABELS = {
  heuristic: "軽量AI（高速・完全予測可能）",
  mock_llm: "標準AI（オフライン・既定）",
  llm: "思考AI（z.ai GLM・低速・要APIキー）",
  rl: "学習AI（強化学習・要RL国指定）",
};
export const policyLabel = v => POLICY_LABELS[v] || v;
