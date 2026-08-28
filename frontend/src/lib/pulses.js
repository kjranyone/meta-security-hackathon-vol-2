// イベント → 地図上の「光る線」パルスへの変換。
// 常時表示だった航路・関係アークを廃止し、何かが起きた瞬間だけ
// 関係が光る表現にする(審査基準の「挙動の確認」=イベント可視化に直結)。
//
// パルス形状:
//   { kind: "pair", a, b, color, born }        国家間の発光弧
//   { kind: "self", a, color, born }           国家自身の拡張リング
//   { kind: "choke", name, color, born }       海峡リング
//   { kind: "route", importer, exporter, commodity, color, born }  航路発光
//
// イベントの actor/targets は国家ID。god_intervention は actor="GOD"。

export const PULSE_TTL = 4200;   // ms — 減衰寿命

const C = {
  war: "#ff5252", peace: "#4ade80", sanction: "#ff8a3d", threat: "#ff8a3d",
  improve: "#4ade80", pact: "#38bdf8", alliance: "#38bdf8", cyber: "#22d3ee",
  disinfo: "#c084fc", gold: "#ffd75e", alarm: "#ff6b35", bad: "#f87171",
};

// god_intervention の data/card から海峡名を拾う(封鎖・開放)
function chokeFromGodEvent(e) {
  const p = e.params || e.data || {};
  return p.chokepoint || null;
}

export function eventsToPulses(events, meta, born = Date.now()) {
  const out = [];
  if (!events) return out;
  const routes = meta?.geo?.routes || [];
  for (const e of events) {
    const t = e.type;
    const tg = e.targets || [];
    const pair = (a, b, color) =>
      (a && b && a !== b) ? out.push({ kind: "pair", a, b, color, born }) : null;
    const self = (a, color) => a && out.push({ kind: "self", a, color, born });
    switch (t) {
      case "war_start":
      case "mobilization":
        pair(tg[0], tg[1], C.war);
        tg.forEach(x => self(x, C.war));
        break;
      case "war_end":
      case "peace_settlement":
      case "arms_control":
        pair(tg[0], tg[1], C.peace);
        break;
      case "alliance_activation":
        pair(e.actor, tg[tg.length - 1], C.alliance);
        self(e.actor, C.alliance);
        break;
      case "alliance_formed":
        pair(e.actor, tg[0], C.alliance);
        break;
      case "sanction":
        pair(e.actor, tg[0], C.sanction);
        self(tg[0], C.sanction);
        break;
      case "threat":
        pair(e.actor, tg[0], C.threat);
        break;
      case "improve":
      case "trade_pact":
        pair(e.actor, tg[0], C.improve);
        break;
      case "cyber_attack":
        pair(e.actor, tg[0], C.cyber);
        self(tg[0], C.cyber);
        break;
      case "disinfo":
        tg.forEach(x => self(x, C.disinfo));
        break;
      case "sovereign_default":
        self(e.actor || tg[0], C.alarm);
        break;
      case "shortage":
        tg.forEach(x => self(x, C.gold));
        break;
      case "insurgency":
      case "collapse":
        tg.forEach(x => self(x, C.bad));
        break;
      case "factor_acquired":
        self(e.actor || tg[0], C.gold);
        break;
      case "election_turnover":
        self(e.actor || tg[0], C.pact);
        break;
      case "price_spike": {
        // 関連商品の航路が一斉に光る(どの供給線が焼かれたかが見える)
        const comm = (e.data && (e.data.commodity || e.data.commodities)) || null;
        const list = Array.isArray(comm) ? comm : comm ? [comm] : null;
        for (const r of routes.slice(0, 400))
          if (!list || list.includes(r.commodity))
            out.push({ kind: "route", importer: r.importer, exporter: r.exporter,
                       commodity: r.commodity, color: C.gold, born });
        break;
      }
      case "trade_throttled": {
        const cp = (e.data && e.data.chokepoint) || (tg.find(x => typeof x === "string")) || null;
        for (const r of routes)
          if ((r.chokepoints || []).includes(cp))
            out.push({ kind: "route", importer: r.importer, exporter: r.exporter,
                       commodity: r.commodity, color: C.alarm, born });
        if (cp) out.push({ kind: "choke", name: cp, color: C.alarm, born });
        break;
      }
      case "god_intervention": {
        const cp = chokeFromGodEvent(e);
        if (cp) {
          out.push({ kind: "choke", name: cp, color: C.alarm, born });
          for (const r of routes)
            if ((r.chokepoints || []).includes(cp))
              out.push({ kind: "route", importer: r.importer, exporter: r.exporter,
                         commodity: r.commodity, color: C.alarm, born });
        }
        break;
      }
      default:
        break;
    }
  }
  return out;
}
