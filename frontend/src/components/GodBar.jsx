export const TECHS = ["drone_swarm", "laser_defense", "cyber_arsenal", "hypersonic_intercept",
  "ai_fab", "biomanuf", "autofactory", "deepsea_mining", "fusion", "space_solar",
  "asteroid_mining", "ai_religion", "techno_nationalism"];
export const RESOURCES = ["oil", "gas", "grain", "fab", "mineral", "orbit"];
// 資源の表示名(イベント文言とUI選択肢で同じ呼び方にする)
export const RESOURCE_JA = { oil: "石油", gas: "天然ガス", grain: "穀物",
  fab: "半導体製造", mineral: "希少金属", orbit: "宇宙インフラ" };

// 地図下部の神介入HUD。パラメータが必要な操作は onModal(type) でモーダルへ、
// 即時実行で良い操作は intervene を直接呼ぶ。sel.kind: "nation" | "cp" | "world"
export default function GodBar({ sel, meta, intervene, onModal }) {
  const nation = sel.kind === "nation" ? sel.id : null;
  const cp = sel.kind === "cp" ? sel.id : null;
  const world = sel.kind === "world";

  const NATION_BTNS = [
    { label: "救済", modal: null, act: () => intervene("bailout", { nation }) },
    { label: "偽情報", modal: "disinfo" },
    { label: "災害", modal: "disaster" },
    { label: "資源の創造", modal: "create_resource" },
    { label: "資源の消滅", modal: "destroy_resource" },
    { label: "技術の授与", modal: "grant_tech" },
    { label: "性格の書き換え", modal: "set_params" },
    { label: "因子の授与", modal: "grant_factor" },
  ];
  const CP_BTNS = [
    { label: "封鎖", modal: "close_chokepoint" },
    { label: "開放", modal: null, act: () => intervene("open_chokepoint", { chokepoint: cp }) },
  ];
  const WORLD_BTNS = [
    { label: "世界金利", modal: "rate_hike" },
    { label: "霧", modal: "fog" },
    { label: "世界パラメータ", modal: "global_sliders" },
    { label: "技術の全世界禁止", modal: "ban_tech" },
  ];
  const btns = nation ? NATION_BTNS : cp ? CP_BTNS : world ? WORLD_BTNS : [];

  if (!btns.length) return null;
  const name = nation ? (meta?.geo?.nations?.[nation]?.name || nation) : cp;

  return (
    <div className="godbar">
      <span className="tgt">
        {nation || cp ? <>対象: <b>{name}</b></> : <>対象: <b>世界</b></>}
      </span>
      {btns.map((b, i) => (
        <button key={i} onClick={() => (b.modal ? onModal(b.modal) : b.act())}>
          {b.label}
        </button>
      ))}
    </div>
  );
}
