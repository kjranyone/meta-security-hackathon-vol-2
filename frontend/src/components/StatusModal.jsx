import { simDate } from "../lib/calendar";
import { policyLabel } from "../lib/policies";

// 現在のセッション状態モーダル（タイトル/接続チップから開く。純粋な状態値のみ）
export default function StatusModal({ onClose, conn, status, tick, meta,
                                      preset, policy, seed, nations,
                                      serverLabel, onNewSim }) {
  const m = tick?.metrics;
  const mdl = status.model;
  const rows = [
    ["状態", conn ? "接続中" : "切断"],
    ["サーバ", serverLabel || `ws://${location.host}/ws`],
    ["世界", preset === "gen" ? `gen（自動生成 seed=${seed}）` : preset],
    ["seed", seed],
    ["国家AI", policyLabel(policy)],
    ...(mdl ? [["配備モデル",
      `${mdl.file} (${(mdl.bytes / 1048576).toFixed(1)}MB・全${mdl.nations}カ国に1本)`]] : []),
    ["進行", `tick ${status.tick} / ${status.max_ticks} ${status.running ? "▶" : "⏸"}`],
    ["暦", tick ? simDate(tick.tick) : "—"],
    ["主体", nations ?? meta?.geo?.nations ? `${Object.keys(meta?.geo?.nations || {}).length}カ国` : "—"],
  ];
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h2>状態</h2>
        <div className="statrows">
          {rows.map(([k, v]) => (
            <div className="statrow-line" key={k}><span>{k}</span><b>{String(v)}</b></div>
          ))}
        </div>
        {m && (
          <>
            <h2 style={{ marginTop: 14 }}>世界</h2>
            <div className="statrows">
              {[["世界GDP", m.world_gdp.toFixed(1)], ["平均安定", m.mean_stability.toFixed(1)],
                ["戦争", m.wars], ["崩壊", m.collapsed], ["破綻", m.defaults],
                ["平均インフレ", `${(m.mean_inflation * 100).toFixed(1)}%`],
                ["平均債務", `${(m.mean_debt_gdp || 0).toFixed(0)}%`]].map(([k, v]) => (
                <div className="statrow-line" key={k}><span>{k}</span><b>{v}</b></div>
              ))}
            </div>
          </>
        )}
        <h2 style={{ marginTop: 14 }}>クレジット</h2>
        <div className="statrows">
          <div className="statrow-line"><span>製作</span><b>Kojiro Tanaka (kjranyone)</b></div>
          <div className="statrow-line"><span>応募</span><b>第2回 AIエージェント社会シミュレーション・ハッカソン「メタ安全保障」</b></div>
          <div className="statrow-line"><span>地図データ</span><b>Natural Earth (public domain)</b></div>
          <div className="statrow-line"><span>学習教師</span><b>z.ai GLM</b></div>
          {serverLabel?.includes("Pyodide") && (
            <div className="statrow-line"><span>実行基盤</span><b>Pyodide (CPython + numpy / WASM)</b></div>
          )}
        </div>
        <div className="modalbtns">
          <button onClick={onClose}>閉じる</button>
          {onNewSim && <button className="go" onClick={onNewSim}>新しいシミュレーション</button>}
        </div>
      </div>
    </div>
  );
}
