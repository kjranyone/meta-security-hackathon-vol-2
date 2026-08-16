// ビジュアル凡例（ヘルプ画面。?ボタンで開く。色チップとアイコンのみ）
const ROUTES = [
  ["エネルギー", "#e3b341"], ["食料", "#7cb342"], ["半導体", "#58a6ff"],
  ["地下資源", "#d2a8ff"], ["宇宙", "#3fdeff"],
];
const TRUST = [["高信頼", "#3fb950"], ["中立", "#8b949e"], ["敵対", "#f85149"]];
const ICONS = [
  ["⚓", "海峡（開通）"], ["⛔", "海峡封鎖"], ["⚔️", "戦争"], ["💀", "国家崩壊"],
  ["🏦✖", "債務不履行"], ["⚡", "神の介入"], ["🔬", "未来技術の創発"],
];

function Line({ color, dashed }) {
  return <span style={{
    display: "inline-block", width: 34, height: 0,
    borderTop: `${dashed ? "2px dashed" : "3px solid"} ${color}`,
    verticalAlign: "middle", marginRight: 8,
  }} />;
}

export default function LegendModal({ onClose }) {
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h2>🧭 凡例</h2>
        <div className="leggrid">
          <div className="legsec">
            <b>航路</b>
            {ROUTES.map(([name, c]) => (
              <div key={name}><Line color={c} />{name}</div>
            ))}
            <div><Line color="#f85149" dashed />封鎖された航路</div>
          </div>
          <div className="legsec">
            <b>友好度線</b>
            {TRUST.map(([name, c]) => (
              <div key={name}><Line color={c} />{name}</div>
            ))}
          </div>
          <div className="legsec">
            <b>マップ記号</b>
            {ICONS.map(([icon, name]) => (
              <div key={name}><span className="legicon">{icon}</span>{name}</div>
            ))}
          </div>
          <div className="legsec">
            <b>タイムライン</b>
            <div><span className="dot" style={{ background: "#ff6b35" }} />債務不履行</div>
            <div><span className="dot" style={{ background: "#f85149" }} />開戦</div>
            <div><span className="dot" style={{ background: "#e3b341" }} />価格急騰</div>
            <div><span className="dot" style={{ background: "#a371f7" }} />神の介入</div>
            <div><span className="dot" style={{ background: "#e5534b" }} />GDP急落</div>
          </div>
        </div>
        <div className="modalbtns">
          <button className="go" onClick={onClose}>閉じる</button>
        </div>
      </div>
    </div>
  );
}
