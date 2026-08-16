from terrarium.agents.heuristic import HeuristicPolicy
from terrarium.sim.engine import Engine
from terrarium.sim.interventions import Intervention, Scenario
from terrarium.world.presets import load_preset
from terrarium.world.tech import CATALOG


def _engine(seed: int = 7, preset: str = "earth") -> Engine:
    spec = load_preset(preset)
    return Engine(spec, {ns.id: HeuristicPolicy() for ns in spec.nations}, seed=seed, out_dir=None)


def test_techs_emerge_over_time():
    eng = _engine(11)
    eng.run(36, Scenario())
    emergences = [r for r in eng.event_log.records if r.type == "tech_emergence"]
    adoptions = [r for r in eng.event_log.records if r.type == "tech_adopted"]
    # most of the catalog (unlock_tick <= 35) emerges in a 36-tick run
    expected = sum(1 for t in CATALOG if t.unlock_tick <= 35)
    assert len(emergences) == expected
    assert len(adoptions) >= 5, f"only {len(adoptions)} adoptions — diffusion too slow?"
    # rich nations absorb more tech than poor ones (research capacity divide)
    assert len(eng._techs_of("USA")) + len(eng._techs_of("EUR")) + len(eng._techs_of("CHN")) \
        > len(eng._techs_of("EGY")) + len(eng._techs_of("IRN"))


def test_fusion_grants_energy_without_oil():
    """核融合は油田ゼロの国にも電力を与える（flat供給）."""
    eng = _engine(3)
    eng.run(4, Scenario())  # before natural fusion unlock (t20)
    base = eng._production()["JPN"]["energy"]
    assert base < 0.01  # Japan has no energy units
    eng.apply_intervention(Intervention(tick=4, type="grant_tech", params={"nation": "JPN", "tech": "fusion"}))
    after = eng._production()["JPN"]["energy"]
    assert after >= 1.2  # fusion flat supply
    assert "fusion" in eng._techs_of("JPN")


def test_ban_tech_removes_and_blocks():
    eng = _engine(5)
    eng.run(4, Scenario())
    eng.apply_intervention(Intervention(tick=4, type="grant_tech", params={"nation": "USA", "tech": "ai_fab"}))
    assert "ai_fab" in eng._techs_of("USA")
    sup_with = eng._production()["USA"]["chips"]
    eng.apply_intervention(Intervention(tick=4, type="ban_tech", params={"tech": "ai_fab"}))
    assert "ai_fab" not in eng._techs_of("USA")
    sup_without = eng._production()["USA"]["chips"]
    assert sup_with > sup_without
    # after the ban, nobody adopts it even after the natural unlock tick
    eng.run(30, Scenario())
    assert all("ai_fab" not in eng._techs_of(nid) for nid in eng.nations)


def test_ai_religion_shifts_society():
    eng = _engine(6)
    eng.run(3, Scenario())
    eng.apply_intervention(Intervention(tick=3, type="grant_tech", params={"nation": "IND", "tech": "ai_religion"}))
    stab0 = eng.nations["IND"].stability
    eng.run(6, Scenario())
    # socio drift should have lifted stability relative to decay pressures
    t_stab, t_appr = eng._tech_socio_drifts("IND")
    assert t_stab > 0 and t_appr > 0
    # ideological friction: other nations trust IND less
    assert all(n.trust["IND"] < 20.0 for k, n in eng.nations.items() if k != "IND")


def test_determinism_with_techs():
    import json
    a, b = _engine(9), _engine(9)
    a.run(30, Scenario())
    b.run(30, Scenario())
    assert json.dumps(a.snapshots[-1], sort_keys=True) == json.dumps(b.snapshots[-1], sort_keys=True)
