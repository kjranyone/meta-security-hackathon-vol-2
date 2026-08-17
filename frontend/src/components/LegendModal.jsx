// ビジュアル凡例（?ボタンで開く。CSSグリフと色チップのみ）
const ROUTES = [
  ["エネルギー", "#e3b341"], ["食料", "#7cb342"], ["半導体", "#58a6ff"],
  ["地下資源", "#d2a8ff"], ["宇宙", "#3fdeff"],
];
const TRUST = [["高信頼", "#3fb950"], ["中立", "#8b949e"], ["敵対", "#f85149"]];
const TL = [["債務不履行", "#ff6b35"], ["開戦", "#f85149"], ["価格急騰", "#e3b341"],
            ["神の介入", "#a371f7"], ["GDP急落", "#e5534b"], ["核取得", "#ff4d6d"], ["核放棄", "#7ee787"]];

function Line({ color, dashed }) {
  return <span style={{
    display: "inline-block", width: 34, height: 0,
    borderTop: `${dashed ? "2px dashed" : "3px solid"} ${color}`,
    verticalAlign: "middle", marginRight: 8,
  }} />;
}

function Ring({ color, slashed, size = 16 }) {
  return <span className="glyph" style={{
    width: size, height: size, borderRadius: "50%",
    border: `2px solid ${color}`, display: "inline-block",
    marginRight: 8, position: "relative", verticalAlign: "middle",
    background: slashed
      ? `linear-gradient(45deg, transparent 44%, ${color} 44%, ${color} 56%, transparent 56%)`
      : "transparent",
  }} />;
}

export default function LegendModal({ onClose }) {
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h2>凡例</h2>
        <div className="leggrid">
          <div className="legsec">
            <b>航路</b>
            {ROUTES.map(([name, c]) => <div key={name}><Line color={c} />{name}</div>)}
            <div><Line color="#f85149" dashed />封鎖された航路</div>
          </div>
          <div className="legsec">
            <b>友好度線</b>
            {TRUST.map(([name, c]) => <div key={name}><Line color={c} />{name}</div>)}
          </div>
          <div className="legsec">
            <b>海峡</b>
            <div><Ring color="rgba(255,255,255,.55)" />開通</div>
            <div><Ring color="#f85149" slashed />封鎖</div>
          </div>
          <div className="legsec">
            <b>国家</b>
            <div><Ring color="#ffffff" />選択中</div>
            <div><Ring color="#f85149" />戦争中</div>
            <div><Ring color="#ff6b35" />債務不履行</div>
            <div><span className="glyph glyph-dark" />崩壊（領土暗転）</div>
          </div>
          <div className="legsec">
            <b>タイムライン</b>
            {TL.map(([name, c]) => (
              <div key={name}><span className="dot" style={{ background: c }} />{name}</div>
            ))}
          </div>
        </div>
        <div className="modalbtns">
          <button className="go" onClick={onClose}>閉じる</button>
        </div>
      </div>
    </div>
  );
}
