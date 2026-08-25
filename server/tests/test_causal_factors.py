"""追加の因果ファクター: 難民・政体遷移・気候・エネルギー転換・サイバー戦。"""
from terrarium.agents.heuristic import HeuristicPolicy
from terrarium.sim.engine import Engine
from terrarium.sim.interventions import Scenario, Intervention
from terrarium.world.presets import load_preset


def _engine(seed: int = 7, preset: str = "earth") -> Engine:
    spec = load_preset(preset)
    return Engine(spec, {ns.id: HeuristicPolicy() for ns in spec.nations},
                  seed=seed, out_dir=None)


def test_war_creates_refugees_that_strain_neighbors():
    """戦争(高強度)は難民を流出させ、近隣の安定・失業を圧迫する。"""
    class HiRng:   # 講和ハザード等を発火させない(戦争を持続させる)
        def random(self): return 0.999
        def triangular(self, lo, hi, mode): return mode
        def uniform(self, a, b): return b

    eng = _engine(seed=1, preset="earth")
    eng.rng = HiRng()
    usa, irn = eng.nations["USA"], eng.nations["IRN"]
    eng.wars.append(("USA", "IRN"))
    eng._war_intensity[("USA", "IRN")] = 2.5
    usa.at_war_with.append("IRN"); irn.at_war_with.append("USA")
    usa.doctrine_militarism = irn.doctrine_militarism = 0.0  # 強度を維持
    eng.tick_no = 0
    eng.step()
    assert sum(eng._refugees_out.values()) > 0.0, "war must create refugee outflows"
    assert sum(eng._refugees_in.values()) > 0.0, "neighbors must receive refugees"


def test_crisis_drives_backsliding():
    """2年間の統治危機は混合政体を権威主義化する。"""
    eng = _engine(seed=3, preset="earth_all")
    frag = next(n for n in eng.nations.values()
                if eng._specs[n.id].centroid and n.regime == "hybrid")
    eng.tick_no = 0
    for t in range(1, 26):
        eng.tick_no = t
        frag.stability = 0.0    # 持続する統治危機(回復ドリフト後も<20を保つ)
        eng.step()
    assert frag.regime == "autocracy", "sustained crisis must cause backsliding"
    assert any(r.type == "democratic_backsliding" and r.actor == frag.id
               for r in eng.event_log.records)


def test_co2_drives_climate_disasters():
    eng = _engine(seed=5, preset="earth")
    eng.global_co2 = 40000.0   # 気候シグナルを極端に
    eng.tick_no = 0
    for t in range(1, 13):
        eng.tick_no = t
        eng.step()
    assert any(r.type == "climate_disaster" for r in eng.event_log.records), \
        "high CO2 must generate climate disasters within a year"


def test_price_signal_accelerates_energy_transition():
    """ホルムズ12ヶ月封鎖(持続する高価格)は再エネ比率を押し上げる。"""
    eng = _engine(seed=1, preset="earth")
    jpn = eng.nations["JPN"]
    r0 = jpn.renew_eff
    for t in range(12):
        eng.tick_no = t
        if t == 0:
            eng.apply_intervention(Intervention(
                tick=0, type="close_chokepoint",
                params={"chokepoint": "Strait of Hormuz", "duration": 12}))
        eng.step()
    assert jpn.renew_eff > r0, "sustained high prices must accelerate the transition"


def test_cyber_arsenal_sabotages_at_war():
    """サイバー基盤保有国は戦時に敵の生産を妨害する。"""
    eng = _engine(seed=9, preset="earth")
    eng._adopt_tech("USA", "cyber_arsenal", forced=True)

    class FireRng:
        def random(self): return 0.0
        def triangular(self, lo, hi, mode): return mode
        def uniform(self, a, b): return a

    eng.rng = FireRng()
    eng.wars.append(("USA", "CHN"))
    eng.nations["USA"].at_war_with.append("CHN")
    eng.nations["CHN"].at_war_with.append("USA")
    eng.tick_no = 0
    eng.step()
    assert any(r.type == "cyber_attack" for r in eng.event_log.records), \
        "cyber-capable belligerent must sabotage the enemy"
