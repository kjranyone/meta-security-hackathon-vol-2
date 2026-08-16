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

from .env import OBS_DIM, NationEnv
from .nets import PolicyNet

SERVER_ROOT = Path(__file__).resolve().parents[3]


def run_episode(env: NationEnv, net: PolicyNet, train: bool, gamma: float = 0.97,
                reward_scale: float = 0.1, lr: float = 1e-3, entropy_coef: float = 0.005):
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
    return total


def evaluate(env: NationEnv, net: PolicyNet, seeds: list[int], horizon: int) -> float:
    rewards = []
    saved_ep = env._ep
    for s in seeds:
        env.seed = s
        env.horizon = horizon
        rewards.append(run_episode(env, net, train=False))
    env._ep = saved_ep
    return float(np.mean(rewards))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Train RL tactical policy for one nation")
    ap.add_argument("--preset", default="default")
    ap.add_argument("--nation", required=True, help="learner nation id (e.g. VLT, JPN)")
    ap.add_argument("--episodes", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--horizon", type=int, default=24)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--entropy", type=float, default=0.005)
    ap.add_argument("--eval-every", type=int, default=250)
    ap.add_argument("--scenario", default=None, help="train under this god-stress scenario")
    ap.add_argument("--out", default=None, help="weights path (default models/rl_<nation>.npz)")
    args = ap.parse_args(argv)

    out = Path(args.out) if args.out else SERVER_ROOT / "models" / f"rl_{args.nation}.npz"
    out.parent.mkdir(parents=True, exist_ok=True)

    from ..sim.interventions import load_scenario as _load_scenario

    train_scenario = _load_scenario(args.scenario) if args.scenario else None
    env = NationEnv(args.preset, args.nation, seed=args.seed, horizon=args.horizon,
                    scenario=train_scenario)
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
