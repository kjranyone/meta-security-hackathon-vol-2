// 「世界を創る」ダイアログ（新規ゲーム画面風・説明文なし）
export default function CreateWorldDialog({ open, preset, policy, seed, rlNation,
                                            onPreset, onPolicy, onSeed, onRlNation,
                                            onCreate, onClose }) {
  if (!open) return null;
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h2>🌍 世界を創る</h2>
        <label className="modalfield">世界
          <select value={preset} onChange={e => onPreset(e.target.value)}>
            <option value="earth">earth — 実世界16国</option>
            <option value="default">default — 架空8国</option>
            <option value="gen">gen — 自動生成 seed=7</option>
          </select>
        </label>
        <label className="modalfield">国家AI
          <select value={policy} onChange={e => onPolicy(e.target.value)}>
            <option value="mock_llm">mock_llm — オフライン</option>
            <option value="heuristic">heuristic</option>
            <option value="llm">llm — z.ai GLM</option>
            <option value="rl">rl — 強化学習</option>
          </select>
        </label>
        <div className="modalrow">
          <label className="modalfield" style={{ flex: 1 }}>seed
            <input type="number" value={seed} onChange={e => onSeed(e.target.value)} />
          </label>
          {policy === "rl" && (
            <label className="modalfield" style={{ flex: 1 }}>RL国
              <input type="text" value={rlNation} onChange={e => onRlNation(e.target.value)}
                     placeholder="JPN,EGY" />
            </label>
          )}
        </div>
        <div className="modalbtns">
          <button onClick={onClose}>やめる</button>
          <button className="go" onClick={() => { onCreate(); onClose(); }}>🌍 創造</button>
        </div>
      </div>
    </div>
  );
}
