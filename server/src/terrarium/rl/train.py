"""Train the RL tactical layer (actor-critic, numpy).

Example:
  uv run python -m terrarium.rl.train --preset default --nation VLT \
      --episodes 3000 --seed 0 --out models/rl_VLT.npz

The learned policy allocates the national budget posture-by-posture inside
the engine while heuristic nations provide the environment. Training curve
is written next to the weights as JSON.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from ..world.presets import load_preset
from .env import OBS_DIM, NationEnv
from .nets import PolicyNet

SERVER_ROOT = Path(__file__).resolve().parents[3]


def run_episode(env, net, train: bool, gamma: float = 0.97,
                reward_scale: float = 0.1, lr: float = 1e-3, entropy_coef: float = 0.005):
    """Single-agent episode (NationEnv); works unchanged for evaluation."""
    obs = env.reset()
    traj = []
    done = False
    total = 0.0
    while not done:
        act = net.act(obs, deterministic=not train)
        nxt, r, done, info = env.step(act)
        traj.append((obs, act, r * reward_scale))
        total += r
        obs = nxt
    if train:
        _apply_update(net, traj, gamma=gamma, lr=lr, entropy_coef=entropy_coef)
    return total


def _apply_update(net, traj, gamma: float = 0.97, lr: float = 1e-3,
                  entropy_coef: float = 0.005) -> None:
    # Monte-Carlo returns with value baseline, advantage-normalized
    returns = []
    G = 0.0
    for _, _, r_t in reversed(traj):
        G = r_t + gamma * G
        returns.append(G)
    returns.reverse()
    advs = [G - a["value"] for (_, a, _), G in zip(traj, returns)]
    mu = float(np.mean(advs))
    sigma = float(np.std(advs)) + 1e-6
    for (obs_t, act_t, _), G, adv in zip(traj, returns, advs):
        net.update(obs_t, act_t, (adv - mu) / sigma, G, lr=lr, entropy_coef=entropy_coef)


def run_selfplay_episode(env, nets: dict, train: bool, gamma: float = 0.97,
                         reward_scale: float = 0.1, lr: float = 1e-3,
                         entropy_coef: float = 0.005) -> dict[str, float]:
    """One episode of SelfPlayEnv: every learner acts each tick, each net
    updates on its own trajectory (the others are part of its environment)."""
    obs_d = env.reset()
    trajs = {nid: [] for nid in env.nation_ids}
    totals = {nid: 0.0 for nid in env.nation_ids}
    done = False
    while not done:
        acts = {nid: nets[nid].act(obs_d[nid], deterministic=not train)
                for nid in env.nation_ids}
        nxt_d, rew_d, done, info = env.step(acts)
        for nid in env.nation_ids:
            trajs[nid].append((obs_d[nid], acts[nid], rew_d[nid] * reward_scale))
            totals[nid] += rew_d[nid]
        obs_d = nxt_d
    if train:
        for nid in env.nation_ids:
            _apply_update(nets[nid], trajs[nid], gamma=gamma, lr=lr, entropy_coef=entropy_coef)
    return totals


def evaluate(env: NationEnv, net: PolicyNet, seeds: list[int], horizon: int) -> float:
    rewards = []
    saved_ep = env._ep
    for s in seeds:
        env.seed = s
        env.horizon = horizon
        rewards.append(run_episode(env, net, train=False))
    env._ep = saved_ep
    return float(np.mean(rewards))


def _train_generalist(args, train_scenario) -> int:
    """全国家を学習者として巡回しつつ重みを共有する汎用戦術AI。
    どの国に載せても動く単一ポリシー（LLM無しで全国家AIをRL化）。"""
    from .env import NationEnv

    out = Path(args.out) if args.out else SERVER_ROOT / "models" / "generalist.npz"
    out.parent.mkdir(parents=True, exist_ok=True)
    spec = load_preset(args.preset)
    nids = sorted(ns.id for ns in spec.nations)
    envs = {nid: NationEnv(args.preset, nid, seed=args.seed,
                           horizon=args.horizon, scenario=train_scenario)
            for nid in nids}
    net = PolicyNet(obs_dim=OBS_DIM, seed=args.seed)
    eval_seeds = [101, 202, 303]
    t0 = time.time()

    def evaluate() -> float:
        vals = []
        saved = {nid: env._ep for env in envs.values() for nid in [None]}
        for s in eval_seeds:
            for nid in nids[:: max(1, len(nids) // 6)]:   # 代表6カ国
                env = envs[nid]
                env.seed, env.horizon = s, args.horizon
                vals.append(run_episode(env, net, train=False))
        return float(np.mean(vals))

    base = evaluate()
    print(f"[gen] episode 0 eval={base:.2f}")
    for ep in range(1, args.episodes + 1):
        nid = nids[(ep - 1) % len(nids)]
        env = envs[nid]
        env.seed = args.seed * 1000 + ((ep // len(nids)) % 8) + 1
        run_episode(env, net, train=True, lr=args.lr, entropy_coef=args.entropy)
        if ep % args.eval_every == 0:
            print(f"[gen] episode {ep} eval={evaluate():.2f} elapsed={time.time()-t0:.0f}s")
    net.save(out)
    final = evaluate()
    (out.with_suffix(".curve.json")).write_text(json.dumps(
        [{"episode": 0, "eval_reward": round(base, 3)},
         {"episode": args.episodes, "eval_reward": round(final, 3)}], indent=1), encoding="utf-8")
    print(f"[gen] saved {out} | eval {base:.2f} -> {final:.2f} ({final-base:+.2f})")
    return 0


def _train_selfplay(args, nation_ids: list[str], train_scenario) -> int:
    """Multi-agent training: one net per nation, all learning inside one world."""
    from .env import SelfPlayEnv

    prefix = Path(args.out) if args.out else SERVER_ROOT / "models" / "selfplay"
    prefix.parent.mkdir(parents=True, exist_ok=True)

    env = SelfPlayEnv(args.preset, nation_ids, seed=args.seed, horizon=args.horizon,
                      scenario=train_scenario, default_penalty=args.default_penalty)
    nets = {nid: PolicyNet(obs_dim=OBS_DIM, seed=args.seed + i)
            for i, nid in enumerate(nation_ids)}

    eval_seeds = [101, 202, 303]
    train_seeds = [args.seed * 1000 + i for i in range(1, 9)]
    curve = []
    t0 = time.time()

    def evaluate_all() -> dict[str, float]:
        out = {}
        saved_ep = env._ep
        for s in eval_seeds:
            env.seed = s
            totals = run_selfplay_episode(env, nets, train=False)
            for nid, r in totals.items():
                out.setdefault(nid, []).append(r)
        env._ep = saved_ep
        return {nid: float(np.mean(rs)) for nid, rs in out.items()}

    base_eval = evaluate_all()
    curve.append({"episode": 0, "eval": {k: round(v, 3) for k, v in base_eval.items()}})
    print(f"[sp] episode 0 eval={ {k: round(v, 1) for k, v in base_eval.items()} }")

    for ep in range(1, args.episodes + 1):
        env.seed = train_seeds[(ep - 1) % len(train_seeds)]
        totals = run_selfplay_episode(env, nets, train=True,
                                      lr=args.lr, entropy_coef=args.entropy)
        if ep % args.eval_every == 0:
            ev = evaluate_all()
            curve.append({"episode": ep,
                          "train": {k: round(v, 3) for k, v in totals.items()},
                          "eval": {k: round(v, 3) for k, v in ev.items()}})
            mean_ev = float(np.mean(list(ev.values())))
            print(f"[sp] episode {ep} mean_eval={mean_ev:.2f} "
                  f"eval={ {k: round(v, 1) for k, v in ev.items()} } elapsed={time.time()-t0:.0f}s")

    paths = {}
    for nid, net in nets.items():
        p = Path(f"{prefix}_{nid}.npz")
        net.save(p)
        paths[nid] = p
    final_eval = evaluate_all()
    curve.append({"episode": args.episodes, "eval": {k: round(v, 3) for k, v in final_eval.items()}})
    (Path(f"{prefix}.curve.json")).write_text(json.dumps(curve, indent=1), encoding="utf-8")
    for nid, p in paths.items():
        print(f"[sp] saved {p} | eval {base_eval[nid]:.2f} -> {final_eval[nid]:.2f} "
              f"({final_eval[nid]-base_eval[nid]:+.2f})")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Train RL tactical policy for one nation")
    ap.add_argument("--preset", default="default")
    ap.add_argument("--nation", required=True,
                    help="learner nation id (e.g. VLT, JPN); comma-list for self-play (e.g. VLT,SAH)")
    ap.add_argument("--episodes", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--horizon", type=int, default=24)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--entropy", type=float, default=0.005)
    ap.add_argument("--eval-every", type=int, default=250)
    ap.add_argument("--scenario", default=None, help="train under this god-stress scenario")
    ap.add_argument("--default-penalty", type=float, default=0.0,
                    help="reward penalty per own sovereign default (0=growth-only objective)")
    ap.add_argument("--out", default=None,
                    help="weights path (single) or prefix (self-play); default models/rl_<nation>[.npz] or models/selfplay_<nation>.npz")
    args = ap.parse_args(argv)

    from ..sim.interventions import load_scenario as _load_scenario

    train_scenario = _load_scenario(args.scenario) if args.scenario else None
    nation_ids = [n.strip() for n in args.nation.split(",") if n.strip()]
    selfplay = len(nation_ids) > 1

    if selfplay:
        return _train_selfplay(args, nation_ids, train_scenario)
    if args.nation == "ALL":
        return _train_generalist(args, train_scenario)

    out = Path(args.out) if args.out else SERVER_ROOT / "models" / f"rl_{args.nation}.npz"
    out.parent.mkdir(parents=True, exist_ok=True)

    from ..sim.interventions import load_scenario as _load_scenario

    train_scenario = _load_scenario(args.scenario) if args.scenario else None
    env = NationEnv(args.preset, args.nation, seed=args.seed, horizon=args.horizon,
                    scenario=train_scenario, default_penalty=args.default_penalty)
    net = PolicyNet(obs_dim=OBS_DIM, seed=args.seed)

    eval_seeds = [101, 202, 303, 404, 505]
    # common random numbers: cycle a small fixed set of env seeds so the
    # policy gradient sees a consistent environment instead of pure noise
    train_seeds = [args.seed * 1000 + i for i in range(1, 9)]
    curve = []
    t0 = time.time()
    baseline = evaluate(env, net, eval_seeds, args.horizon)
    curve.append({"episode": 0, "eval_reward": round(baseline, 3)})
    print(f"[rl] episode 0 eval_reward={baseline:.2f}")

    for ep in range(1, args.episodes + 1):
        env.seed = train_seeds[(ep - 1) % len(train_seeds)]
        r = run_episode(env, net, train=True, lr=args.lr, entropy_coef=args.entropy)
        if ep % args.eval_every == 0:
            ev = evaluate(env, net, eval_seeds, args.horizon)
            curve.append({"episode": ep, "train_reward": round(r, 3), "eval_reward": round(ev, 3)})
            print(f"[rl] episode {ep} train={r:.2f} eval={ev:.2f} elapsed={time.time()-t0:.0f}s")

    net.save(out)
    final = evaluate(env, net, eval_seeds, args.horizon)
    curve.append({"episode": args.episodes, "eval_reward": round(final, 3)})
    (out.with_suffix(".curve.json")).write_text(json.dumps(curve, indent=1), encoding="utf-8")
    print(f"[rl] saved {out} | eval {baseline:.2f} -> {final:.2f} ({final-baseline:+.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
