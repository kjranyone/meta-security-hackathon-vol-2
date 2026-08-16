export const TECHS = ["drone_swarm", "laser_defense", "cyber_arsenal", "hypersonic_intercept",
  "ai_fab", "biomanuf", "autofactory", "deepsea_mining", "fusion", "space_solar",
  "asteroid_mining", "ai_religion", "techno_nationalism"];
export const RESOURCES = ["oil", "gas", "grain", "fab", "mineral", "orbit"];

// 地図下部の神介入HUD（シミュレーターゲーム風ワンクリック操作）
export default function GodBar({ sel, meta, intervene }) {
  const nation = sel.kind === "nation" ? sel.id : null;
  const cp = sel.kind === "cp" ? sel.id : null;
  const name = nation ? (meta?.geo?.nations?.[nation]?.name || nation) : cp;

  const B = [
    { label: "⚓ 封鎖", dis: !cp, act: d => intervene("close_chokepoint", { chokepoint: cp, duration: +d.dur }), title: "海峡選択時に有効" },
    { label: "⚓ 開放", dis: !cp, act: () => intervene("open_chokepoint", { chokepoint: cp }), title: "海峡選択時に有効" },
    { label: "💸 救済", dis: !nation, act: () => intervene("bailout", { nation }), title: "国家選択時に有効" },
    { label: "🌾 旱魃", dis: !nation, act: () => intervene("disaster", { nation, kind: "drought" }), title: "国家選択時に有効" },
    { label: "📰 偽情報", dis: !nation, act: () => intervene("disinfo", { target: nation, intensity: 0.6 }), title: "国家選択時に有効" },
    { label: "✨ 資源+2", dis: !nation, act: d => intervene("create_resource", { nation, resource: d.res, quantity: 2 }), title: "国家選択時に有効" },
    { label: "💥 資源消滅", dis: !nation, act: d => intervene("destroy_resource", { nation, resource: d.res }), title: "国家選択時に有効" },
    { label: "🧪 技術授与", dis: !nation, act: d => intervene("grant_tech", { nation, tech: d.tech }), title: "国家選択時に有効" },
    { label: "😠 好戦↑", dis: !nation, act: () => intervene("set_param", { nation, param: "aggression", value: 0.2 }), title: "国家選択時に有効" },
    { label: "🕊️ 好戦↓", dis: !nation, act: () => intervene("set_param", { nation, param: "aggression", value: -0.2 }), title: "国家選択時に有効" },
    { label: "📉 利上げ+5%", dis: false, act: () => intervene("rate_hike", { value: 0.05 }), title: "常時有効（全世界）" },
    { label: "🚫 技術禁止", dis: false, act: d => intervene("ban_tech", { tech: d.tech }), title: "常時有効（全世界）" },
  ];

  return (
    <div className="godbar">
      <span className="tgt">
        {nation || cp ? <>対象: <b>{name}</b></> : "対象なし（国家/海峡をクリック）"}
      </span>
      <select data-k="dur" title="封鎖期間（ヶ月）">{[6, 12, 24, 60].map(d => <option key={d}>{d}</option>)}</select>
      <select data-k="res" title="資源の種類">{RESOURCES.map(r => <option key={r}>{r}</option>)}</select>
      <select data-k="tech" title="技術">{TECHS.map(t => <option key={t}>{t}</option>)}</select>
      {B.map((b, i) => (
        <button key={i} disabled={b.dis} title={b.title}
                onClick={e => b.act(Object.fromEntries(
                  Array.from(e.currentTarget.parentElement.querySelectorAll("select[data-k]"))
                    .map(s => [s.dataset.k, s.value])))}>
          {b.label}
        </button>
      ))}
    </div>
  );
}
