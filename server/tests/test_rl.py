import json

import numpy as np
import pytest

from terrarium.agents.base import Decisions
from terrarium.agents.rl_policy import RLPolicy
from terrarium.rl.env import OBS_DIM, NationEnv, obs_from_view
from terrarium.rl.nets import BUDGET_PRESETS, PolicyNet
from terrarium.rl.train import evaluate, run_episode
from terrarium.sim.interventions import load_scenario


def test_obs_shape_and_finiteness():
    env = NationEnv("default", "VLT", seed=1, horizon=8)
    obs = env.reset()
    assert obs.shape == (OBS_DIM,)
    assert np.all(np.isfinite(obs))
    act = {"budget_idx": 0, "posture_idx": 0, "rationing": 1, "propaganda": 0}
    obs2, r, done, info = env.step(act)
    assert np.all(np.isfinite(obs2)) and isinstance(r, float)


def test_env_deterministic_given_seed_and_actions():
    def rollout():
        env = NationEnv("default", "VLT", seed=5, horizon=12)
        obs = env.reset()
        net = PolicyNet(obs_dim=OBS_DIM, seed=99)
        total = 0.0
        done = False
        while not done:
            act = net.act(obs, deterministic=True)
            obs, r, done, _ = env.step(act)
            total += r
        return total, obs

    (ta, oa), (tb, ob) = rollout(), rollout()
    assert ta == tb
    assert np.allclose(oa, ob)


def test_training_improves_eval_reward():
    """Actor-critic learns a survival policy for the fragile nation under
    its stress scenario (drought): eval reward must clearly improve."""
    scenario = load_scenario("scenarios/drought_sahelia.yaml")
    env = NationEnv("default", "SAH", seed=3, horizon=24, scenario=scenario)
    net = PolicyNet(obs_dim=OBS_DIM, seed=3)
    base = evaluate(env, net, [11, 22], 24)
    for ep in range(1, 501):
        env.seed = 3000 + (ep % 8)
        run_episode(env, net, train=True, lr=2e-3)
    final = evaluate(env, net, [11, 22], 24)
    assert final > base + 10.0, f"no learning signal: {base:.1f} -> {final:.1f}"


def test_policy_save_load_and_deterministic_inference(tmp_path):
    net = PolicyNet(obs_dim=OBS_DIM, seed=7)
    path = tmp_path / "rl_test.npz"
    net.save(path)
    loaded = PolicyNet.load(path)
    env = NationEnv("default", "VLT", seed=1, horizon=8)
    obs = env.reset()
    a1 = net.act(obs, deterministic=True)
    a2 = loaded.act(obs, deterministic=True)
    assert a1["budget_idx"] == a2["budget_idx"]
    assert a1["posture_idx"] == a2["posture_idx"]


def test_rl_policy_decides_from_view(tmp_path):
    net = PolicyNet(obs_dim=OBS_DIM, seed=1)
    path = tmp_path / "rl_X.npz"
    net.save(path)
    pol = RLPolicy("X", path)
    env = NationEnv("default", "VLT", seed=2, horizon=6)
    env.reset()
    view = env.eng.nation_view("VLT")
    d1, d2 = pol.decide(view), pol.decide(view)
    assert isinstance(d1, Decisions)
    assert abs(sum(d1.budget.values()) - 1.0) < 1e-6
    assert d1.military_posture in ("defensive", "neutral", "aggressive")
    assert json.dumps(d1.model_dump(), sort_keys=True) == json.dumps(d2.model_dump(), sort_keys=True)


def test_budget_presets_valid():
    for preset in BUDGET_PRESETS:
        assert abs(sum(preset.values()) - 1.0) < 1e-6
        assert all(v >= 0 for v in preset.values())
