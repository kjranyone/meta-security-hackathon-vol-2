from terrarium.agents.heuristic import HeuristicPolicy
from terrarium.sim.engine import Engine
from terrarium.sim.interventions import Intervention, Scenario
from terrarium.world.presets import load_preset


def _engine(preset: str = "earth", seed: int = 7) -> Engine:
    spec = load_preset(preset)
    return Engine(spec, {ns.id: HeuristicPolicy() for ns in spec.nations}, seed=seed, out_dir=None)


def test_baseline_has_at_most_isolated_defaults():
    """No-god baseline: the fiscal system must not cascade (design invariant).
    A single dramatic default (e.g. high-debt Japan) is acceptable theatre."""
    eng = _engine(seed=42)
    eng.run(36, Scenario())
    total = sum(n.defaults for n in eng.nations.values())
    assert total <= 2, f"baseline produced {total} defaults — fiscal system too fragile"
    assert not any(n.collapsed for n in eng.nations.values())


def test_rate_hike_shocks_high_debt_nations():
    """God's rate hike must push high-debt / low-credibility states into
    default far more often than the baseline."""
    base, shock = _engine(seed=5), _engine(seed=5)
    eng_scenario = Scenario(name="hike", interventions=[
        {"tick": 2, "type": "rate_hike", "params": {"value": 0.15}},
    ])
    base.run(30, Scenario())
    shock.run(30, eng_scenario)
    d0 = sum(n.defaults for n in base.nations.values())
    d1 = sum(n.defaults for n in shock.nations.values())
    assert d1 > d0, f"rate hike did not increase defaults ({d0} -> {d1})"
    assert any(n.credibility < 50 for n in shock.nations.values())


def test_default_contagion_has_causal_parents():
    """A default must (a) link to its upstream causes and (b) hit creditors
    with parent-linked credibility events (domino wiring)."""
    eng = _engine(seed=9)
    # engineer a definite default: Egypt, huge debt, no credibility
    eng.nations["EGY"].debt_gdp = 300.0
    eng.nations["EGY"].credibility = 5.0
    # 外貨建て危機: 準備枯渇 + 高インフレで金利が上限へ（自国通貨国は
    # 校正後破綻しないので、破綻の再現には外貨建て条件が要る）
    eng.nations["EGY"].fx_reserves = 0.5
    eng.nations["EGY"].inflation = 0.30
    eng.run(3, Scenario())
    defaults = [r for r in eng.event_log.records if r.type == "sovereign_default"
                and (r.actor == "EGY" or "EGY" in r.targets)]
    assert defaults, "engineered insolvency did not default"
    hits = [r for r in eng.event_log.records if r.type == "credibility_hit"]
    assert hits, "creditors were not affected by the default"
    # creditor hits must reference the default event as their cause
    parents = {p for h in hits for p in h.parents}
    assert any(d.id in parents for d in defaults)
    # default effects applied
    egy = eng.nations["EGY"]
    assert egy.defaults >= 1 and egy.default_cooldown >= 0
    assert egy.debt_gdp < 300.0  # restructuring haircut


def test_bailout_card_reduces_debt():
    eng = _engine(seed=3)
    eng.nations["EGY"].debt_gdp = 200.0
    eng.nations["EGY"].credibility = 10.0
    eng.apply_intervention(Intervention(tick=0, type="bailout", params={"nation": "EGY"}))
    nat = eng.nations["EGY"]
    assert nat.debt_gdp <= 120.0
    assert nat.credibility >= 60.0
    assert any(r.type == "god_intervention" and "救済" in r.text for r in eng.event_log.records)


def test_bond_rate_monotonic_in_credibility_and_hike():
    eng = _engine(seed=1)
    nat = eng.nations["JPN"]
    nat.inflation = 0.02
    nat.credibility = 90.0
    r_hi = eng._bond_rate(nat)
    nat.credibility = 20.0
    r_lo = eng._bond_rate(nat)
    assert r_hi < r_lo
    eng.god.world_rate_hike = 0.10
    assert eng._bond_rate(nat) >= r_lo + 0.10 - 1e-9


def test_war_deficits_accumulate_debt():
    eng = _engine(seed=11)
    a, b = "RUS", "TUR"
    eng.nations[a].at_war_with.append(b)
    eng.nations[b].at_war_with.append(a)
    eng.wars.append((a, b))
    d0 = eng.nations[a].debt_gdp
    eng.run(8, Scenario())
    assert eng.nations[a].debt_gdp > d0 + 2.0, "wartime deficits did not accumulate"
