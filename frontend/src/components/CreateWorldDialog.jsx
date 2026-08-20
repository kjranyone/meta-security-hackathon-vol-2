import { useEffect } from "react";
import { POLICY_LABELS } from "../lib/policies";
// 「世界を創る」ダイアログ（新規ゲーム画面風・説明文なし）
export default function CreateWorldDialog({ open, preset, policy, seed, rlNation,
                                            onPreset, onPolicy, onSeed, onRlNation,
                                            onCreate, onClose }) {
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
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h2>世界を創る</h2>
        <label className="modalfield">世界
          <select value={preset} onChange={e => onPreset(e.target.value)}>
            <option value="earth">earth — 実世界16国</option>
            <option value="earth_all">earth_all — 全世界176カ国</option>
            <option value="default">default — 架空8国</option>
            <option value="gen">gen — 自動生成 seed=7</option>
          </select>
        </label>
        <label className="modalfield">国家AIの頭脳
          <select value={policy} onChange={e => onPolicy(e.target.value)}>
            {Object.entries(POLICY_LABELS).map(([v, label]) => (
              <option key={v} value={v}>{label}</option>
            ))}
          </select>
        </label>
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
