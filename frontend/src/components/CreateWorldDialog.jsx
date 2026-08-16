// 「世界を創る」実行前ダイアログ: 各設定が何をするか説明しながら確認する（ゲームの新規ゲーム画面風）
const PRESET_INFO = {
  earth: "実世界の16主体・実在7海峡・実態を概算反映した債務で開始。提出実験は全てこの世界。",
  default: "架空8カ国の砂場。RL学習の教材に使った小さい世界。",
  gen: "seed=7から需給バランスの取れた架空世界を実地図上に自動生成。",
};
const POLICY_INFO = {
  mock_llm: "LLM風のオフラインAI。personaごとに違う判断を返すがAPIを呼ばない。速くて決定論的。デフォルト。",
  heuristic: "手書きルールのAI（「備蓄が減ったら備蓄予算」等）。最速・完全決定論。実験の基準線。",
  llm: "本物のz.ai GLMが全国家を思考。遅い（1ヶ月≈5分）・非決定論・APIキー必要。思考の理由がログに残る。",
  rl: "強化学習の戦術層（学習済み重み）。下のRL国に装着、他国はheuristic。速い・決定論的。",
};

export default function CreateWorldDialog({ open, preset, policy, seed, rlNation,
                                            onPreset, onPolicy, onSeed, onRlNation,
                                            onCreate, onClose }) {
  if (!open) return null;
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h2>🌍 新しい世界を創造する</h2>
        <p className="modalsub">設定を確認して「創造」を押すと、現在の世界は上書きされます（同じ設定+seedなら毎回同じ歴史）。</p>

        <label className="modalfield">世界（プリセット）
          <select value={preset} onChange={e => onPreset(e.target.value)}>
            <option value="earth">earth — 実世界16国</option>
            <option value="default">default — 架空8国</option>
            <option value="gen">gen — 自動生成 seed=7</option>
          </select>
        </label>
        <p className="modalinfo">{PRESET_INFO[preset]}</p>

        <label className="modalfield">国家AIの頭脳（policy）
          <select value={policy} onChange={e => onPolicy(e.target.value)}>
            <option value="mock_llm">mock_llm — オフラインLLM風（速い・決定論）</option>
            <option value="heuristic">heuristic — 手書きルール（最速）</option>
            <option value="llm">llm — 本物のGLM思考（遅い・要APIキー）</option>
            <option value="rl">rl — 強化学習戦術層（要RL国指定）</option>
          </select>
        </label>
        <p className="modalinfo">{POLICY_INFO[policy]}</p>

        <div className="modalrow">
          <label className="modalfield" style={{ flex: 1 }}>seed（世界の初期状態）
            <input type="number" value={seed} onChange={e => onSeed(e.target.value)} />
          </label>
          {policy === "rl" && (
            <label className="modalfield" style={{ flex: 1 }}>RL国（policy=rl時）
              <input type="text" value={rlNation} onChange={e => onRlNation(e.target.value)}
                     placeholder="例: JPN,EGY" />
            </label>
          )}
        </div>
        <p className="modalinfo">同じseedは常に同じ歴史を生む — これがA/B反実仮想とIF史の土台。</p>

        <div className="modalbtns">
          <button onClick={onClose}>やめる</button>
          <button className="go" onClick={() => { onCreate(); onClose(); }}>🌍 創造する</button>
        </div>
      </div>
    </div>
  );
}
