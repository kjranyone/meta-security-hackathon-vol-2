import { useEffect } from "react";
import ModalClose from "./ModalClose";
import { POLICY_LABELS } from "../lib/policies";
// 「世界を創る」ダイアログ（新規ゲーム画面風・説明文なし）
// 学習AI選択時は配備モデル(重みファイル)を明示する — 何が頭脳なのか曖昧にしない
// policyLocked: ブラウザ実行版(学習AI固定。LLM戦略はAPI鍵が必要なため不可)
// noGen: 生成世界(手続き生成が未同梱)を選択肢から外す
export default function CreateWorldDialog({ open, preset, policy, seed, rlNation, modelInfo,
                                            onPreset, onPolicy, onSeed, onRlNation,
                                            onCreate, onClose, policyLocked, noGen }) {
  useEffect(() => {
    if (!open) return;
    const onKey = e => {
      if (e.key === "Escape") onClose();
      if (e.key === "Enter") { onCreate(); onClose(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCreate, onClose]);
  if (!open) return null;
  const mb = modelInfo ? (modelInfo.bytes / 1048576).toFixed(1) : "";
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <ModalClose onClose={onClose} />
          <h2>新しいシミュレーション</h2>
        <label className="modalfield">世界
          <select value={preset} onChange={e => onPreset(e.target.value)}>
            <option value="earth_all">earth_all — 全世界176カ国</option>
            <option value="earth">earth — 実世界16カ国</option>
            <option value="earth_jpn">earth_jpn — 16カ国・日本は米ハブ同盟網</option>
            <option value="default">default — 架空8国</option>
            {!noGen && <option value="gen">gen — 自動生成(seedで初期値が変わる)</option>}
          </select>
        </label>
        <label className="modalfield">国家AIの頭脳
          <select value={policy} disabled={policyLocked}
                  onChange={e => onPolicy(e.target.value)}>
            {Object.entries(POLICY_LABELS).map(([v, label]) => (
              <option key={v} value={v}>{label}</option>
            ))}
          </select>
        </label>
        {policyLocked && (
          <p style={{ margin: "-4px 0 8px", fontSize: 12, color: "var(--dim)" }}>
            ブラウザ実行版は学習AI固定(思考AIはAPIキーが必要なためローカルサーバ版のみ)
          </p>
        )}
        {policy === "rl" && (
          <p style={{ margin: "-4px 0 8px", fontSize: 12, color: "var(--dim)" }}>
            配備モデル: <b style={{ color: "var(--fg)" }}>{modelInfo?.file || "未読み込み"}</b>
            {modelInfo ? ` (${mb}MB・全${modelInfo.nations}カ国に同一モデル1本)` : ""}
          </p>
        )}
        <label className="modalfield">seed
          <input type="number" value={seed} onChange={e => onSeed(e.target.value)} />
        </label>
        <div className="modalbtns">
          <button onClick={onClose}>やめる</button>
          <button className="go" onClick={() => { onCreate(); onClose(); }}>創造</button>
        </div>
      </div>
    </div>
  );
}
