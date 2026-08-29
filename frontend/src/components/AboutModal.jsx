import Credits from "./Credits";

// 作品情報モーダル(全ページのタイトルクリックで開く共通導線)。
// ギャラリー以外で開いた場合はトップ(#)への導線も併せる
export default function AboutModal({ onClose }) {
  const atTop = ["", "#", "#/"].includes(location.hash);
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h2>この作品について</h2>
        <div className="statrows">
          <div className="statrow-line"><span>構成</span><b>決定論シミュレーション + LLM→RL蒸留 + 介入実験</b></div>
          <div className="statrow-line"><span>主張の範囲</span><b>世界予測ではなく、事案→機序→数値の可視化</b></div>
        </div>
        <Credits />
        <div className="modalbtns">
          <button onClick={onClose}>閉じる</button>
          {!atTop && (
            <button className="go" onClick={() => { location.hash = "/"; onClose(); }}>
              ギャラリーに戻る
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
