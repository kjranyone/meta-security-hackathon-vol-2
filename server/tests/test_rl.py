import json

import numpy as np
import pytest

from terrarium.agents.base import Decisions
from terrarium.agents.llm import make_policy_factory
from terrarium.agents.rl_policy import RLPolicy
from terrarium.rl.env import OBS_DIM, NationEnv, SelfPlayEnv, obs_from_view, tick_reward
from terrarium.rl.nets import BUDGET_PRESETS, PolicyNet
from terrarium.rl.train import evaluate, run_episode, run_selfplay_episode
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


def test_selfplay_env_step_shapes():
    env = SelfPlayEnv("default", ["VLT", "SAH"], seed=2, horizon=6)
    obs_d = env.reset()
    assert set(obs_d) == {"VLT", "SAH"}
    assert all(o.shape == (OBS_DIM,) and np.all(np.isfinite(o)) for o in obs_d.values())
    nets = {nid: PolicyNet(obs_dim=OBS_DIM, seed=10 + i) for i, nid in enumerate(env.nation_ids)}
    acts = {nid: net.act(obs_d[nid], deterministic=True) for nid, net in nets.items()}
    nxt_d, rew_d, done, info = env.step(acts)
    assert set(rew_d) == {"VLT", "SAH"}
    assert all(isinstance(r, float) for r in rew_d.values())
    assert np.all(np.isfinite(nxt_d["VLT"]))


def test_selfplay_episode_deterministic_and_learns():
    """Two learners in one world: identical seeds give identical totals, and
    a short run produces finite gradients (training loop executes)."""
    def rollout():
        env = SelfPlayEnv("default", ["VLT", "SAH"], seed=4, horizon=10)
        nets = {nid: PolicyNet(obs_dim=OBS_DIM, seed=40 + i) for i, nid in enumerate(env.nation_ids)}
        totals = run_selfplay_episode(env, nets, train=True, lr=1e-3)
        return totals

    t1, t2 = rollout(), rollout()
    assert t1 == t2
    assert all(np.isfinite(v) for v in t1.values())


def test_default_penalty_changes_reward_on_default():
    """JPN defaults under the financial-crisis scenario; the penalty knob must
    change the reward stream (growth-only vs debt-discipline objective)."""
    scenario = load_scenario("scenarios/earth_financial_crisis.yaml")

    def rollout(penalty):
        env = NationEnv("earth", "JPN", seed=42, horizon=10, scenario=scenario,
                        default_penalty=penalty)
        env.reset()
        total, done = 0.0, False
        net = PolicyNet(obs_dim=OBS_DIM, seed=1)
        obs = env.reset()
        while not done:
            obs, r, done, _ = env.step(net.act(obs, deterministic=True))
            total += r
        defaults = sum(1 for rec in env.eng.event_log.records
                       if rec.type == "sovereign_default" and rec.actor == "JPN")
        return total, defaults

    plain, n1 = rollout(0.0)
    penalized, n2 = rollout(6.0)
    assert n1 == n2 and n1 >= 1, f"expected JPN default in horizon, got {n1}"
    assert abs((plain - penalized) - 6.0 * n1) < 1e-9


def test_factory_accepts_multi_rl_nations(tmp_path):
    paths = {}
    for nid in ("VLT", "SAH"):
        p = tmp_path / f"sp_{nid}.npz"
        PolicyNet(obs_dim=OBS_DIM, seed=1).save(p)
        paths[nid] = p
    factory = make_policy_factory("rl", rl_nation="VLT,SAH",
                                  rl_weights=f"{paths['VLT']},{paths['SAH']}")

    class Spec:
        pass

    s_vlt, s_sah, s_other = Spec(), Spec(), Spec()
    s_vlt.id, s_sah.id, s_other.id = "VLT", "SAH", "GRN"
    assert isinstance(factory(s_vlt), RLPolicy)
    assert isinstance(factory(s_sah), RLPolicy)
    assert not isinstance(factory(s_other), RLPolicy)
    with pytest.raises(ValueError):
        make_policy_factory("rl", rl_nation="VLT,SAH", rl_weights=str(paths["VLT"]))
