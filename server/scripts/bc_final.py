"""最終統合BC: hard(波1-2) + soft(k=3サンプリング) + DAgger(配備世界の学生訪問状態)
を1つのtarget分布列に統合して訓練する。

- hard/DAgger: one-hot target。DAggerは配備分布を覆盖するため重み倍率をかけられる
- soft: kサンプルの経験分布(確率的教師の較正)
- 層化hold-out(全ソース統合で層化)でearly-stop、macro-F1/per-classを報告

Usage:
  uv run python scripts/bc_final.py --hidden 2048,2048,2048,2048 \
      --hard models/teacher_w1_clean.jsonl,models/teacher_w2_d.jsonl,models/teacher_w2_e.jsonl \
      --soft models/teacher_soft_f.jsonl,models/teacher_soft_g.jsonl \
      --dagger models/teacher_dagger_r1.jsonl --dagger-weight 2.0 \
      --out models/generalist_llm_v12.npz
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from terrarium.rl.distill import eval_agreement, stratified_split
from terrarium.rl.env import OBS_DIM
from terrarium.rl.nets import DeepPolicyNet

SERVER_ROOT = Path(__file__).resolve().parents[1]


def _p(path: str) -> Path:
    p = Path(path)
    return p if p.exists() else SERVER_ROOT / path


def load_items(paths: list[str], source: str, weight: float = 1.0):
    items = []
    for path in paths:
        for line in open(_p(path)):
            r = json.loads(line)
            if r.get("fallback") or any(r.get("fallbacks", [])):
                continue
            if "actions" in r:  # soft形式 → 多数決+経験分布
                k = len(r["actions"])
                budgets = [a["budget_idx"] for a in r["actions"]]
                maj = Counter(budgets).most_common(1)[0][0]
                dist = np.zeros(6)
                for b in budgets:
                    dist[b] += 1.0 / k
                act = dict(r["actions"][0])
                act["budget_idx"] = maj
            else:
                act = r["action"]
                dist = np.eye(6)[act["budget_idx"]]
            items.append({"obs": np.asarray(r["obs"], dtype=np.float32),
                          "action": act, "soft": dist,
                          "source": source, "w": weight})
    return items


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hard", default="models/teacher_w1_clean.jsonl,models/teacher_w2_d.jsonl,models/teacher_w2_e.jsonl")
    ap.add_argument("--soft", default="")
    ap.add_argument("--dagger", default="")
    ap.add_argument("--dagger-weight", type=float, default=2.0)
    ap.add_argument("--hidden", default="2048,2048,2048,2048")
    ap.add_argument("--epochs", type=int, default=80)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--out", default="models/generalist_llm_v12.npz")
    args = ap.parse_args(argv)

    data = load_items(args.hard.split(","), "hard") if args.hard else []
    data += load_items(args.soft.split(","), "soft") if args.soft else []
    data += (load_items(args.dagger.split(","), "dagger", args.dagger_weight)
             if args.dagger else [])
    if not data:
        print("no data")
        return 1
    cnt = Counter(d["source"] for d in data)
    print(f"corpus: {len(data)} ({dict(cnt)})")

    train, valid = stratified_split(data, seed=0)
    bcnt = Counter(d["action"]["budget_idx"] for d in train)
    print(f"train {len(train)} / valid {len(valid)}; budget dist {dict(sorted(bcnt.items()))}")

    hidden = [int(h) for h in args.hidden.split(",")]
    net = DeepPolicyNet(obs_dim=OBS_DIM, hidden=hidden, seed=args.seed)
    n_params = sum(p.size for p in net.params)
    print(f"net: {hidden} ({n_params:,} params)")

    K = len(bcnt)
    wmap = {c: len(train) / (K * n) for c, n in bcnt.items()}
    m0 = eval_agreement(net, valid)
    best = {"f1": m0["macro_f1"], "epoch": 0, "state": [p.copy() for p in net.params],
            "metrics": m0}
    for ep in range(args.epochs):
        rng = np.random.default_rng(ep + 1)
        idx = rng.permutation(len(train))
        lr_ep = args.lr * (0.5 ** (ep // 30))
        losses = []
        for s0 in range(0, len(train), args.batch_size):
            rows = idx[s0:s0 + args.batch_size]
            batch = [(train[i]["obs"], train[i]["action"]["budget_idx"],
                      train[i]["action"]["posture_idx"],
                      train[i]["action"]["rationing"], train[i]["action"]["propaganda"])
                     for i in rows]
            w = np.array([wmap[train[i]["action"]["budget_idx"]] * train[i]["w"]
                          for i in rows])
            sb = np.stack([train[i]["soft"] for i in rows])
            losses.append(net.imitate_batch(batch, lr=lr_ep, weights=w, soft_budget=sb))
        m_va = eval_agreement(net, valid)
        if (ep + 1) % 10 == 0 or ep == 0:
            print(f"[final] ep {ep+1}: loss {np.mean(losses):.3f} "
                  f"valid acc {m_va['budget_acc']:.3f} macro-F1 {m_va['macro_f1']:.3f} "
                  f"(majority {m_va['majority_acc']:.3f})", flush=True)
        if m_va["macro_f1"] > best["f1"]:
            best = {"f1": m_va["macro_f1"], "epoch": ep + 1,
                    "state": [p.copy() for p in net.params], "metrics": m_va}
    for p, s in zip(net.params, best["state"]):
        p[...] = s
    m = best["metrics"]
    print(f"[final] best ep {best['epoch']}: acc {m['budget_acc']:.3f} "
          f"macro-F1 {m['macro_f1']:.3f}")
    print("per_class:", {k: round(v["recall"], 2) for k, v in m["per_class"].items()})

    net.save(SERVER_ROOT / args.out if not Path(args.out).is_absolute() else args.out)
    out_path = SERVER_ROOT / args.out if not Path(args.out).is_absolute() else Path(args.out)
    out_path.with_suffix(".curve.json").write_text(json.dumps(
        {"corpus": {"total": len(data), **cnt},
         "best_epoch": best["epoch"], "metrics": m,
         "hidden": hidden, "params": n_params}, ensure_ascii=False))
    print(f"saved -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
