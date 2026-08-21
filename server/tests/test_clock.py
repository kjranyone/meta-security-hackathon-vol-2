"""実時間時計のテスト: 介入は遅延をもって波及し、短時間では何も起きない。

神モード(1tick=1時間)の約束:
- 3日でデフォルトも戦争も起きない（財政は四半期、動員は~10日の物理）
- 市場は期待で数時間内に反応する（在庫が尽きるより先に）
- 戦争は動員という梯子を経てのみ勃発する
- 圧縮時計(720h/tick)では従来の月次実験と同様に危機が展開する
"""
from terrarium.agents.heuristic import HeuristicPolicy
from terrarium.sim.engine import Engine
from terrarium.sim.interventions import Intervention, Scenario, load_scenario
from terrarium.world.presets import load_preset


def _engine(seed: int = 11, preset: str = "earth", hpt: float = 1.0,
            decision_every: float | None = 168.0) -> Engine:
    spec = load_preset(preset)
    spec.hours_per_tick = hpt
    spec.decision_every_hours = decision_every
    return Engine(spec, {ns.id: HeuristicPolicy() for ns in spec.nations},
                  seed=seed, out_dir=None)


def _run_with(eng: Engine, ticks: int, ivs: list[Intervention]) -> None:
    eng.open_replay()
    for t in range(ticks):
        eng.tick_no = t
        for iv in ivs:
            if iv.tick == t:
                eng.apply_intervention(iv)
        eng.step()
    eng.close()


def test_three_days_of_quiet_after_closure():
    """ホルムズ封鎖から72時間: 何も壊れない。価格だけが(期待で)動く。"""
    ivs = [Intervention(tick=24, type="close_chokepoint",
                        params={"chokepoint": "Strait of Hormuz"})]
    eng = _engine(seed=11)
    _run_with(eng, 24 * 3, ivs)
    types = [r.type for r in eng.event_log.records]
    assert types.count("war_start") == 0, "wars cannot start within 3 days (mobilization physics)"
    assert types.count("sovereign_default") == 0, "defaults are quarterly dynamics"
    assert types.count("shortage") == 0, "3-month stockpiles absorb a 3-day shock"
    assert types.count("trade_throttled") > 0, "shipping throttle begins ramping"
    assert eng.prices["energy"] > 1.10, "markets price the news within days"


def test_expectation_precedes_physical_shortage():
    """価格は在庫揚耗より先に動く（期待効果）。数日ではGDPはほぼ動かない。"""
    ivs = [Intervention(tick=0, type="close_chokepoint",
                        params={"chokepoint": "Strait of Hormuz"})]
    eng = _engine(seed=11)
    _run_with(eng, 48, ivs)
    assert eng.prices["energy"] > 1.05
    g0, g1 = eng.series[0]["world_gdp"], eng.series[-1]["world_gdp"]
    assert abs(g1 / g0 - 1.0) < 0.01, f"GDP moved {g1/g0 - 1.0:.4f} in 2 days — too fast"


def test_mobilization_ladder_times_the_war():
    """開戦は動員所要時間(ここでは240h=10日)を経てちょうどそのtickに起こる。"""

    class FixedRng:
        def random(self): return 0.99
        def triangular(self, lo, hi, mode): return 240.0
        def uniform(self, a, b): return a

    eng = _engine(seed=1)
    eng.rng = FixedRng()
    for nid in ("USA", "CHN"):
        eng.nations[nid].aggression = 0.85
        eng.nations[nid].trust[{"USA": "CHN", "CHN": "USA"}[nid]] = -60.0
    eng.tick_no = 0
    eng._enqueue_mobilization("USA", "CHN", 0.9)
    war_tick = None
    for t in range(1, 300):
        eng.tick_no = t
        eng.step()
        if war_tick is None and any(r.type == "war_start" for r in eng.event_log.records):
            war_tick = t
            break
    assert war_tick == 240, f"war must start exactly at the 240h mobilization due (got t={war_tick})"


def test_stand_down_when_tension_recedes():
    """動員中に緊張が引けば開戦せず解除される。"""

    class FixedRng:
        def random(self): return 0.99
        def triangular(self, lo, hi, mode): return 240.0
        def uniform(self, a, b): return a

    eng = _engine(seed=1)
    eng.rng = FixedRng()
    eng.tick_no = 0
    eng._enqueue_mobilization("USA", "CHN", 0.9)
    for t in range(1, 300):
        eng.tick_no = t
        eng.step()
    types = [r.type for r in eng.event_log.records]
    assert types.count("war_start") == 0
    assert types.count("stand_down") >= 1, "mobilization must be stood down when tension recedes"


def test_compressed_clock_still_produces_crisis():
    """月次圧縮時計(720h/tick)では従来どおり72ヶ月の危機が展開する。"""
    spec = load_preset("earth")
    eng = Engine(spec, {ns.id: HeuristicPolicy() for ns in spec.nations},
                 seed=11, out_dir=None)
    scen = load_scenario("scenarios/earth_chaos.yaml")
    eng.run(72, scen)
    types = [r.type for r in eng.event_log.records]
    assert types.count("war_start") > 0, "chaos scenario must still produce wars"
    assert types.count("mobilization") >= types.count("war_start")


def test_decision_cadence_caches_standing_policy():
    """意思決定周期(週次)より頻繁に政府は閣議を開かない。"""
    calls = {"n": 0}

    class Counting(HeuristicPolicy):
        def decide(self, view):
            calls["n"] += 1
            return super().decide(view)

    spec = load_preset("earth")
    spec.hours_per_tick = 1.0
    spec.decision_every_hours = 168.0
    eng = Engine(spec, {ns.id: Counting() for ns in spec.nations}, seed=5, out_dir=None)
    _run_with(eng, 24 * 30, [])
    assert calls["n"] <= 6 * len(eng.nations), f"decide called {calls['n']} times in 30 days"
    pol_shifts = sum(1 for r in eng.event_log.records if r.type == "policy_shift")
    assert pol_shifts <= 6 * len(eng.nations)


def test_hourly_clock_is_deterministic():
    a, b = _engine(seed=9), _engine(seed=9)
    _run_with(a, 100, [])
    _run_with(b, 100, [])
    assert a.snapshots[-1] == b.snapshots[-1]
    assert [e.text for e in a.event_log.records] == [e.text for e in b.event_log.records]
