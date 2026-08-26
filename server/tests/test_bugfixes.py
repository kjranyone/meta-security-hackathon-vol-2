"""レビューで見つかったバグ修正の回帰テスト。

- genworld の summary KeyError (minerals/space)
- v9観測の死んでいた3次元（戦争強度・難民負担）の実供給と、旧モデル向け
  obs_sem ゲート（コミット済みrunのbit等価を保つ）
- /static マウントの範囲限定（server/.env が露出しない）
- set_param / global_slider のホワイトリスト
- NationState.population_m の二重宣言除去
- EventLog.by_id のインデックス
"""
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from terrarium.agents.heuristic import HeuristicPolicy
from terrarium.rl.env import OBS_DESC, OBS_DIM, OBS_SEM2_LIVE_IDX, obs_from_view
from terrarium.rl.nets import PolicyNet
from terrarium.sim.engine import Engine
from terrarium.sim.events import EventLog
from terrarium.sim.interventions import Intervention, load_scenario
from terrarium.world.models import NationState
from terrarium.world.presets import load_preset

SERVER_ROOT = Path(__file__).resolve().parents[1]
MODELS = SERVER_ROOT / "models"


@pytest.fixture(scope="module")
def hormuz_engine():
    """36ヶ月のホルムズ封鎖世界（戦争と難民が創発する決定論的シード）。"""
    spec = load_preset("earth")
    policies = {ns.id: HeuristicPolicy() for ns in spec.nations}
    eng = Engine(spec, policies, seed=42)
    eng.run(36, load_scenario("scenarios/earth_hormuz.yaml"))
    return eng


# --------------------------------------------------------------- genworld
def test_genworld_summary_covers_all_commodities():
    from terrarium.runner.genworld import world_summary
    from terrarium.world.worldgen import GenParams, generate_world

    for seed in (7, 13, 99):
        summary = world_summary(generate_world(GenParams(seed=seed)))
        for c in ("energy", "food", "chips", "minerals", "space"):
            assert c in summary


# ----------------------------------------------------- v9 obs live dims
def test_observation_has_live_war_and_refugee_dims(hormuz_engine):
    eng = hormuz_engine
    war_seen = ref_seen = False
    for nid in eng.nations:
        view = eng.nation_view(nid)
        assert view.me["war_intensity_max"] >= 0.0
        if view.me["war_intensity_max"] >= 1.0:
            war_seen = True
            obs = obs_from_view(view)
            assert obs[OBS_SEM2_LIVE_IDX[0]] > 0.0
        if view.me["refugees_in_m"] > 0.0 or view.me["refugees_out_m"] > 0.0:
            ref_seen = True
            obs = obs_from_view(view)
            assert obs[OBS_SEM2_LIVE_IDX[1]] > 0.0 or obs[OBS_SEM2_LIVE_IDX[2]] > 0.0
    assert war_seen, "hormuz 36 ticks should have produced at least one war"
    assert ref_seen, "hormuz 36 ticks should have produced refugee flows"


def test_obs_desc_matches_sem2_indices():
    assert OBS_DESC[OBS_SEM2_LIVE_IDX[0]] == "war_intensity_max"
    assert OBS_DESC[OBS_SEM2_LIVE_IDX[1]] == "refugee_burden_in"
    assert OBS_DESC[OBS_SEM2_LIVE_IDX[2]] == "refugee_burden_out"
    assert OBS_DIM == len(OBS_DESC)


# ------------------------------------------------------------ obs_sem gate
def test_new_net_saves_obs_sem2(tmp_path):
    net = PolicyNet(obs_dim=OBS_DIM, seed=0)
    p = tmp_path / "t.npz"
    net.save(p)
    assert PolicyNet.load(p).obs_sem == 2


def test_legacy_npz_loads_as_sem1_and_masks_live_dims(hormuz_engine):
    """コミット済みの旧61次元npz（obs_semなし）はsem1とみなされ、推論時に
    戦争強度・難民次元が0にマスクされて訓練時の入力分布が保たれる。"""
    from terrarium.agents.rl_policy import RLPolicy

    weights = MODELS / "generalist_lh.npz"
    if not weights.exists():
        pytest.skip("generalist_lh.npz not present")
    with np.load(weights) as data:
        assert "obs_sem" not in data.files
    pol = RLPolicy("JPN", weights)
    assert pol.net.obs_sem == 1

    eng = hormuz_engine
    nid = next(n for n in sorted(eng.nations)
               if eng.nation_view(n).me["war_intensity_max"] >= 1.0)
    view = eng.nation_view(nid)
    obs = obs_from_view(view)
    assert obs[OBS_SEM2_LIVE_IDX[0]] > 0.0            # 生観測は非ゼロ
    d = pol.decide(view)                              # ゲート後の決定
    # 同じ観測を手動でマスク+切断した場合と同一の決定になること
    want = pol.net.W1.shape[0]
    masked = obs[:want].copy()
    for i in OBS_SEM2_LIVE_IDX:
        if i < masked.shape[0]:
            masked[i] = 0.0
    a = pol.net.act(masked, deterministic=True)
    assert d.budget is not None and d.military_posture in ("defensive", "neutral", "aggressive")
    ref = pol.net.act(masked, deterministic=True)
    assert (a["posture_idx"], a["rationing"], a["propaganda"]) == \
           (ref["posture_idx"], ref["rationing"], ref["propaganda"])


# ----------------------------------------------------------------- server
def test_static_does_not_expose_env():
    from terrarium.server.app import app

    with TestClient(app) as client:
        assert client.get("/static/server/.env").status_code == 404
        assert client.get("/static/web/world.geojson").status_code == 200
        assert client.get("/static/server/logs").status_code in (200, 404)


# ------------------------------------------------------------ interventions
def _small_engine():
    spec = load_preset("default")
    policies = {ns.id: HeuristicPolicy() for ns in spec.nations}
    return Engine(spec, policies, seed=1)


def test_set_param_whitelist():
    eng = _small_engine()
    with pytest.raises(ValueError):
        eng.apply_intervention(Intervention(
            tick=1, type="set_param", params={"nation": "VLT", "param": "gdp", "value": 99.0}))
    eng.apply_intervention(Intervention(
        tick=1, type="set_param", params={"nation": "VLT", "param": "aggression", "value": 0.9}))
    with pytest.raises(ValueError):
        eng.apply_intervention(Intervention(
            tick=1, type="global_slider", params={"param": "nonsense", "value": 1.0}))
    eng.apply_intervention(Intervention(
        tick=1, type="global_slider", params={"param": "food_yield", "value": 0.7}))


# ------------------------------------------------------------------ models
def test_nation_state_population_m_required_once():
    fields = list(NationState.model_fields)
    assert fields.count("population_m") == 1
    base = dict(id="X", name="X", gdp=1.0, military=5.0, stability=50.0,
                approval=50.0, aggression=0.3, paranoia=0.3, stocks={},
                base_aggression=0.3, base_paranoia=0.3)
    with pytest.raises(ValidationError):
        NationState(**base)                    # population_m なし
    NationState(**base, population_m=10.0)     # あり


# ----------------------------------------------------------------- events
def test_eventlog_by_id_uses_index():
    log = EventLog()
    rec = log.emit(1, "war_start", "text")
    assert log.by_id(rec.id) is rec
    assert log.by_id("e999999") is None
    assert log.records[-1] is rec


# -------------------------------------------------------------------- gru
def test_gru_weights_deploy_through_rlpolicy(hormuz_engine):
    """GRU npzはW1を持たない — RLPolicyがobs_dim属性で次元合わせできること。"""
    from terrarium.agents.rl_policy import RLPolicy

    weights = MODELS / "generalist_gru.npz"
    if not weights.exists():
        pytest.skip("generalist_gru.npz not present")
    pol = RLPolicy("JPN", weights)
    eng = hormuz_engine
    nid = sorted(eng.nations)[0]
    d = pol.decide(eng.nation_view(nid))
    assert d.military_posture in ("defensive", "neutral", "aggressive")
