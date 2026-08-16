// ゲーム風ガイドダイアログ（初回起動時に表示、?ボタンで再表示）
const SECTIONS = {
  viewer: [
    { icon: "🗺️", title: "地図の読み方", text: "色付きの領土=国家（崩壊で暗転）・⚓/⛔=海峡（封鎖で⛔に）・色付きの弧=貿易航路（琥珀=エネルギー 緑=食料 青=半導体 紫=地下資源 水色=宇宙）。緑〜赤の線は国家間の友好度です。" },
    { icon: "👆", title: "調べる", text: "右の統計テーブルで国の行をクリックすると選択され、友好度がその国を中心とした星型で表示されます。パネルの境界バーはドラッグで拡大・縮小、ダブルクリックで戻ります。" },
    { icon: "⏬", title: "タイムライン", text: "▶で履歴を再生、バーをドラッグして任意の月へ。色付きのマーカーは大イベント（橙=債務不履行 赤=開戦 黄=価格急騰 紫=神の介入）で、再生で跨ぐと発光と効果音が鳴ります（🔊で切替）。1tick=1時間の高速世界時計。" },
    { icon: "⏪", title: "IF史モード", text: "「過去、●●年に△△していたら」を検証: 分岐tickと介入カードを選ぶと、決定論エンジンが元の歴史をそこまで正確に再生し、介入から先を新しい歴史として再実行します。分岐レポートは数値でも表示されます。" },
  ],
  god: [
    { icon: "🌍", title: "世界を創る", text: "ヘッダーの設定（世界の種類・国家AIの頭脳・seed）を選んで「世界を創る」。同じseedなら完全に同じ歴史が再現されます（決定論）。" },
    { icon: "👆", title: "対象を選ぶ", text: "地図の海峡⚓か国家をクリック（または統計の行）で介入対象を選択。地図下部の神の介入HUDのボタンが有効になります。細かいパラメータは右パネルのカード。" },
    { icon: "⚡", title: "神の介入", text: "封鎖・救済・旱魃・偽情報・資源の創造/消滅・技術の授与/禁止・金利など。介入は即座に世界に適用され、イベントフィードに記録されます。" },
    { icon: "⏬", title: "時間の流れ", text: "▶再生/⏸停止/⏭1tick、速度スライダーで調整。大イベント（破綻・開戦・介入）では発光と効果音が鳴ります（🔊で切替）。地図上部はシミュレーション内の暦（1tick=1ヶ月）。" },
  ],
};

export default function HelpModal({ page, onClose }) {
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h2>{page === "god" ? "👑 神の玉座 — 操作ガイド" : "🌐 リプレイビューア — 操作ガイド"}</h2>
        <div className="modalsecs">
          {SECTIONS[page].map((s, i) => (
            <div className="modalsec" key={i}>
              <div className="modalsec-icon">{s.icon}</div>
              <div>
                <b>{s.title}</b>
                <p>{s.text}</p>
              </div>
            </div>
          ))}
        </div>
        <div className="modalbtns">
          <button className="go" onClick={onClose}>冒険を始める</button>
        </div>
      </div>
    </div>
  );
}
