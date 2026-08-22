// 国家AIのプラットフォーム表示名（プレイヤー視点。値はエンジンのpolicy識別子）
// ルールAI(heuristic)はUIから廃止: 学習AIが既定。比較基線としてCLI実験にのみ残る
export const POLICY_LABELS = {
  rl: "学習AI（汎用戦術AIが全国家へ自動適用）",
  llm: "思考AI（z.ai GLM・低速・要APIキー）",
};
export const policyLabel = v => POLICY_LABELS[v] || v;
