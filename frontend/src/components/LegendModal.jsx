import ModalClose from "./ModalClose";
import { GROUP_COLOR } from "../lib/eventMeta";
// ビジュアル凡例（?ボタンで開く。CSSグリフと色チップのみ）
const ROUTES = [
  ["エネルギー", "#e3b341"], ["食料", "#7cb342"], ["半導体", "#58a6ff"],
  ["地下資源", "#d2a8ff"], ["宇宙", "#3fdeff"],
];
const TRUST = [["高信頼", "#3fb950"], ["中立", "#8b949e"], ["敵対", "#f85149"]];
const TL_DESC = {
  "武力": "開戦・動員・国家崩壊・核取得",
  "経済危機": "価格急騰・為替危機・債務不履行・GDP急落",
  "介入": "プレイヤーによる介入",
  "制度": "同盟参戦・因子放棄",
};

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
      <div className="modal legmodal" onClick={e => e.stopPropagation()}>
        <ModalClose onClose={onClose} />
        <h2>凡例</h2>
        <div className="leggrid">
          <div className="legsec">
            <b>航路</b>
            {ROUTES.map(([name, c]) => <div key={name}><Line color={c} />{name}</div>)}
            <div><Line color="#f85149" dashed />封鎖された航路</div>
          </div>
          <div className="legsec">
            <b>友好度線（国選択中）</b>
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
            <div><span className="glyph glyph-nuke" />核保有</div>
            <div><span className="glyph glyph-dark" />崩壊（領土暗転）</div>
          </div>
          <div className="legsec">
            <b>タイムラインの事件マーカー</b>
            {Object.entries(GROUP_COLOR).map(([g, c]) => (
              <div key={g}><span className="dot" style={{ background: c }} />{g}
                <small style={{ color: "var(--dim)", marginLeft: 6 }}>{TL_DESC[g]}</small></div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
