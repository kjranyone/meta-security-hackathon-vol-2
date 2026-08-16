import { simDate } from "../lib/calendar";

// 現在のセッション状態モーダル（タイトル/接続チップから開く。純粋な状態値のみ）
export default function StatusModal({ onClose, conn, status, tick, meta,
                                      preset, policy, seed, nations }) {
  const m = tick?.metrics;
  const rows = [
    ["状態", conn ? "接続中" : "切断"],
    ["サーバ", `ws://${location.host}/ws`],
    ["世界", preset === "gen" ? "gen（自動生成 seed=7）" : preset],
    ["seed", seed],
    ["国家AI", policy],
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
        <div className="modalbtns">
          <button className="go" onClick={onClose}>閉じる</button>
        </div>
      </div>
    </div>
  );
}
