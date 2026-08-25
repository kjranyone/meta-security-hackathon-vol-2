import { trustColor } from "../lib/trust";

const nameOf = (meta, id) => meta?.geo?.nations?.[id]?.name || id;

function Row({ k, v }) {
  return <div className="statrow-line"><span>{k}</span><b>{v}</b></div>;
}

// 国詳細（クリックした国の情報画面。友好度行クリックで対象を切り替え）
export default function NationDetail({ n, meta, onSelect }) {
  if (!n) return null;
  const st = n.stocks;
  const chips = [];
  if (n.at_war_with?.length) chips.push(["戦争中", "#f85149"]);
  if (n.collapsed) chips.push(["崩壊", "#d29922"]);
  if (n.rationing) chips.push(["配給", "#e3b341"]);
  if (n.propaganda) chips.push(["プロパガンダ", "#f778ba"]);

  const trustEntries = Object.entries(n.trust || {}).sort((a, b) => b[1] - a[1]);
  const top = trustEntries.slice(0, 8);
  const bottom = trustEntries.slice(-8).reverse().filter(([, v]) => v < 40);

  return (
    <div className="nationdetail">
      <div className="target-banner" style={{ borderColor: n.color }}>
        <span className="tdot" style={{ background: n.color }} />
        {n.name}
        {chips.map(([label, c]) => (
          <span className="chip" key={label} style={{ color: c, borderColor: c }}>{label}</span>
        ))}
      </div>

      <div className="ndgrid">
        <div>
          <Row k="GDP" v={`${n.gdp.toFixed(1)}兆$`} />
          <Row k="物価" v={`${(n.inflation * 100).toFixed(1)}%`} />
          <Row k="安定" v={n.stability.toFixed(0)} />
          <Row k="支持" v={n.approval.toFixed(0)} />
        </div>
        <div>
          <Row k="債務" v={`${n.debt_gdp.toFixed(0)}%`} />
          <Row k="信用" v={n.credibility.toFixed(0)} />
          <Row k="軍事" v={n.military.toFixed(0)} />
          <Row k="破綻" v={`${n.defaults}回`} />
        </div>
        <div>
          <Row k="好戦性" v={n.aggression.toFixed(2)} />
          <Row k="疑心暗鬼" v={n.paranoia.toFixed(2)} />
          <Row k="戦争" v={n.at_war_with?.length ? n.at_war_with.map(x => nameOf(meta, x)).join(", ") : "—"} />
          <Row k="同盟" v={n.alliances?.length ? n.alliances.map(x => nameOf(meta, x)).join(", ") : "—"} />
        </div>
        <div>
          <Row k="備蓄 E/F/C/M/S"
               v={`${st.energy?.toFixed(1) ?? "-"} / ${st.food?.toFixed(1) ?? "-"} / ${st.chips?.toFixed(1) ?? "-"} / ${st.minerals?.toFixed(1) ?? "-"} / ${st.space?.toFixed(1) ?? "-"}`} />
          <Row k="技術" v={(n.techs || []).length ? (n.techs || []).join(", ") : "—"} />
        </div>
        <div>
          <Row k="人口" v={`${(n.population_m ?? 0).toFixed(0)}百万人`} />
          <Row k="失業率" v={`${(n.unemployment ?? 0).toFixed(1)}%`} />
          <Row k="為替" v={(n.fx ?? 1).toFixed(2)} />
          <Row k="外貨準備" v={`${(n.fx_reserves ?? 0).toFixed(1)}ヶ月分`} />
        </div>
        <div>
          <Row k="思想: 軍事偏重" v={(n.doctrine_militarism ?? 0).toFixed(2)} />
          <Row k="思想: 修正主義" v={(n.doctrine_revisionism ?? 0).toFixed(2)} />
          <Row k="思想: 危機許容" v={(n.doctrine_risk ?? 0).toFixed(2)} />
          <Row k="思想: 同盟遵守" v={(n.doctrine_treaty_fidelity ?? 0).toFixed(2)} />
          <Row k="核態勢" v={n.nuclear_posture === "counterforce" ? "先制攻撃型" : n.nuclear_posture === "nfu" ? "不先使用" : "相互抑止"} />
          <Row k="イデオロギー" v={n.ideology === "ai_cult" ? "AI神格宗教圏" : n.ideology === "techno_nationalist" ? "テクノ・ナショナリズム圏" : "世俗"} />
          <Row k="政体" v={n.regime === "democracy" ? "民主主義" : n.regime === "autocracy" ? "権威主義" : "混合"} />
        </div>
        <div>
          <Row k="経常収支" v={`${(n.ca_last ?? 0) >= 0 ? "+" : ""}${(n.ca_last ?? 0).toFixed(1)}`} />
          <Row k="インフラ" v={(n.infra ?? 1).toFixed(2)} />
          <Row k="CO2累積" v={(n.co2_cum ?? 0).toFixed(0)} />
          <Row k="再生エネルギー" v={`${Math.round((n.renew_eff ?? 0) * 100)}%`} />
          <Row k="因子" v={[
            (n.factors || []).includes("nuclear") ? "核:保有"
              : (n.factor_progress || {}).nuclear ? `核:追求${(n.factor_progress.nuclear).toFixed(0)}%` : null,
            (n.factors || []).includes("export_control") ? "規制:加盟"
              : (n.factor_progress || {}).export_control ? "規制:交渉中" : null,
            (n.factors || []).includes("nuclear_umbrella") ? "核傘:加入" : null,
            (n.factors || []).includes("currency_bloc") ? "通貨:加盟"
              : (n.factor_progress || {}).currency_bloc ? "通貨:交渉中" : null,
          ].filter(Boolean).join(" ") || "—"} />
        </div>
      </div>

      <h4 className="ndhead">友好度</h4>
      <div className="ndtrust">
        <div className="ndtrust-col">
          {[...top].reverse().map(([id, v]) => (
            <div className="trustrow" key={id} onClick={() => onSelect?.(id)}>
              <span className="trustname">{nameOf(meta, id)}</span>
              <span className="trustbar"><i style={{ width: `${v}%`, background: trustColor(v) }} /></span>
              <b>{v.toFixed(0)}</b>
            </div>
          ))}
        </div>
        <div className="ndtrust-col">
          {bottom.map(([id, v]) => (
            <div className="trustrow" key={id} onClick={() => onSelect?.(id)}>
              <span className="trustname">{nameOf(meta, id)}</span>
              <span className="trustbar"><i style={{ width: `${v}%`, background: trustColor(v) }} /></span>
              <b>{v.toFixed(0)}</b>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
