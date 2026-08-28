"""F2実験: KLアンカー付きA2C微調整(BC蒸留モデルの50MB版)。

v11で発見した「12.7M paramsでは単一サンプルA2Cが教師一致を破壊する」問題への
原理的処置: RLHFと同じサンプルKLペナルティ(有効advantage = adv - β)で
BC参照へ固定しつつ報酬を追う。エピソードをバッチに束ねて分散を下げる。

Usage:
  uv run python scripts/finetune_deep.py --weights models/generalist_llm_deep_bc.npz \
      --beta 0.2 --episodes 240 --out models/ft_beta02.npz
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from terrarium.rl.distill import eval_agreement
from terrarium.rl.env import NationEnv
from terrarium.rl.nets import DeepPolicyNet
from terrarium.rl.train import evaluate
from terrarium.sim.interventions import load_scenario

SERVER_ROOT = Path(__file__).resolve().parents[1]


def load_corpus():
    data = []
    for f in ["models/teacher_w1_clean.jsonl", "models/teacher_w2_d.jsonl",
              "models/teacher_w2_e.jsonl"]:
        for line in open(SERVER_ROOT / f):
            r = json.loads(line)
            if not r.get("fallback"):
                data.append({"obs": np.asarray(r["obs"], dtype=np.float32),
                             "action": r["action"]})
    return data


def run_gather(env: NationEnv, net: DeepPolicyNet, gamma: float = 0.97):
    """1エピソードを方策サンプリングで走らせ (obs, action, ret, adv) を返す。"""
    obs = env.reset()
    traj = []
    done = False
    while not done:
        a = net.act(obs, deterministic=False)
        act = {k: a[k] for k in ("budget_idx", "posture_idx", "rationing", "propaganda")
               if k in a}
        v = a["value"]
        nxt, r, done, _ = env.step(act)
        traj.append((obs.copy(), act, r, v))
        obs = nxt
    # discounted returns + advantage (= ret - V(s))
    T = len(traj)
    rets = np.zeros(T)
    acc = 0.0
    for t in reversed(range(T)):
        acc = traj[t][2] + gamma * acc
        rets[t] = acc
    batch = []
    for t, (o, a, r, v) in enumerate(traj):
        batch.append((o, a, rets[t] - v, rets[t]))
    return batch, float(rets[0])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="KL-anchored fine-tune of distilled deep net")
    ap.add_argument("--weights", required=True)
    ap.add_argument("--beta", type=float, default=0.2, help="KL penalty coefficient")
    ap.add_argument("--episodes", type=int, default=240)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--batch-eps", type=int, default=4, help="episodes per update batch")
    ap.add_argument("--entropy", type=float, default=0.0)
    ap.add_argument("--preset", default="earth")
    ap.add_argument("--nation", default="JPN")
    ap.add_argument("--scenario", default="scenarios/earth_hormuz.yaml")
    ap.add_argument("--seed", type=int, default=5000)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    scenario = load_scenario(args.scenario) if args.scenario else None
    data = load_corpus()
    net = DeepPolicyNet.load(args.weights)
    ref = DeepPolicyNet.load(args.weights)   # 凍結参照(BC方策)— KLアンカー用
    m0 = eval_agreement(net, data)
    env = NationEnv(args.preset, args.nation, seed=99, horizon=24, scenario=scenario)
    r0 = evaluate(env, net, [11, 22], 24)
    print(f"[ft] start: eval {r0:.2f} budget-acc {m0['budget_acc']:.3f} "
          f"macro-F1 {m0['macro_f1']:.3f} (kl_beta={args.beta})", flush=True)

    log = [{"episode": 0, "eval_reward": r0, "budget_acc": m0["budget_acc"],
            "macro_f1": m0["macro_f1"]}]
    buf = []
    for ep in range(args.episodes):
        env.seed = args.seed + (ep % 8)
        batch, ep_ret = run_gather(env, net)
        buf.extend(batch)
        if len(buf) >= args.batch_eps * 24:
            ref_logits = np.stack([ref.forward(b[0])["budget_logits"] for b in buf])
            net.update_batch(buf, lr=args.lr, entropy_coef=args.entropy,
                             kl_coef=args.beta, ref_budget_logits=ref_logits)
            buf = []
        if (ep + 1) % max(1, args.episodes // 8) == 0:
            r = evaluate(env, net, [11, 22], 24)
            m = eval_agreement(net, data)
            log.append({"episode": ep + 1, "eval_reward": r,
                        "budget_acc": m["budget_acc"], "macro_f1": m["macro_f1"]})
            print(f"[ft] ep {ep+1}/{args.episodes}: eval {r:.2f} "
                  f"budget-acc {m['budget_acc']:.3f} macro-F1 {m['macro_f1']:.3f}",
                  flush=True)

    net.save(args.out)
    (Path(args.out).with_suffix(".curve.json")).write_text(
        json.dumps({"beta": args.beta, "log": log}, ensure_ascii=False))
    print(f"[ft] saved {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
