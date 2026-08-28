"""F1実験 + D1測定: soft-target蒸留(k回サンプリング教師)vs hard-label BC。

soft corpus(同一状態でk=3回のLLM教師サンプリング)から:
  - D1: 教師自己一致率(同一obsでk回が一致する割合)= 到達可能な天井
  - F1: 同一状態・同一分割で (a)多数決hard-label BC vs (b)経験分布soft-target BC
    を比較。評価は (i)多数決ラベルへのmacro-F1 と (ii)soft NLL(kサンプルの
    平均対数尤度 — 確率的教師への適合の正しい尺度)。

Usage:
  uv run python scripts/bc_soft.py --hidden 512,512
  uv run python scripts/bc_soft.py --hidden 2048,2048,2048,2048 --save soft
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


def load_soft_corpus(paths: list[str]):
    from terrarium.rl.data import load_soft_items
    return load_soft_items(paths)

def train(net, data, soft: bool, epochs=60, lr=1e-3, batch_size=32, seed=0):
    """hard/soft BC。valid macro-F1でearly-stop。返り値: (best_metrics, history)"""
    train, valid = stratified_split(data, seed=seed)
    m0 = eval_agreement(net, valid)
    best = {"f1": m0["macro_f1"], "epoch": 0, "state": [p.copy() for p in net.params],
            "metrics": m0}
    cnt = Counter(s["action"]["budget_idx"] for s in train)
    K = len(cnt)
    wmap = {c: len(train) / (K * n) for c, n in cnt.items()}
    for ep in range(epochs):
        rng = np.random.default_rng(ep + 1)
        idx = rng.permutation(len(train))
        lr_ep = lr * (0.5 ** (ep // 30))
        for s0 in range(0, len(train), batch_size):
            rows = idx[s0:s0 + batch_size]
            batch = [(train[i]["obs"], train[i]["action"]["budget_idx"],
                      train[i]["action"]["posture_idx"],
                      train[i]["action"]["rationing"], train[i]["action"]["propaganda"])
                     for i in rows]
            w = np.array([wmap[train[i]["action"]["budget_idx"]] for i in rows])
            sb = np.stack([train[i]["soft"] for i in rows]) if soft else None
            net.imitate_batch(batch, lr=lr_ep, weights=w, soft_budget=sb)
        m_va = eval_agreement(net, valid)
        if m_va["macro_f1"] > best["f1"]:
            best = {"f1": m_va["macro_f1"], "epoch": ep + 1,
                    "state": [p.copy() for p in net.params], "metrics": m_va}
    for p, s in zip(net.params, best["state"]):
        p[...] = s
    return best["metrics"], best["epoch"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="models/teacher_soft_f.jsonl,models/teacher_soft_g.jsonl")
    ap.add_argument("--hidden", default="512,512")
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--save", default=None, help="save soft model to models/<name>.npz")
    args = ap.parse_args(argv)

    states = load_soft_corpus(args.data.split(","))
    if not states:
        print("no soft data yet")
        return 1
    from terrarium.rl.data import self_consistency
    d1 = self_consistency(states)
    print("[D1] teacher self-consistency:", json.dumps(d1, indent=2))

    hidden = [int(h) for h in args.hidden.split(",")]
    results = {}
    for arm in ("hard", "soft"):
        net = DeepPolicyNet(obs_dim=OBS_DIM, hidden=hidden, seed=args.seed)
        m, ep = train(net, states, soft=(arm == "soft"), epochs=args.epochs)
        from terrarium.rl.data import soft_nll
        nll = soft_nll(net, states)
        results[arm] = {"macro_f1": m["macro_f1"], "acc": m["budget_acc"],
                        "best_epoch": ep, "soft_nll": nll,
                        "per_class": {str(k): v["recall"] for k, v in m["per_class"].items()}}
        print(f"[F1:{arm}] macro-F1 {m['macro_f1']:.3f} acc {m['budget_acc']:.3f} "
              f"(epoch {ep}) soft-NLL {nll:.3f} "
              f"per_class {results[arm]['per_class']}", flush=True)
        if arm == "soft" and args.save:
            net.save(SERVER_ROOT / "models" / f"{args.save}_{'x'.join(map(str, hidden))}.npz")
            print(f"saved soft model -> models/{args.save}_{'x'.join(map(str, hidden))}.npz")

    out = {"d1": d1, "hidden": hidden, "corpus": len(states), "results": results}
    (SERVER_ROOT / "models" / "bc_soft_result.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2))
    print("saved -> models/bc_soft_result.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
