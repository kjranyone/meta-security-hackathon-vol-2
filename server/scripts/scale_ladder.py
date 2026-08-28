"""D3診断: スケールラダー — 同データ・同プロトコルで隠れ幅を変えてBCし、
params数 vs hold-out macro-F1 の関係(模倣のスケーリング)を測る。

Usage:
  uv run python scripts/scale_ladder.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

from terrarium.rl.distill import _behavior_clone_deep
from terrarium.rl.env import OBS_DIM
from terrarium.rl.nets import DeepPolicyNet

SERVER_ROOT = Path(__file__).resolve().parents[1]

SIZES = [[64], [128], [256], [512, 512], [1024, 1024, 1024]]
LRS = [1e-3, 3e-4]


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


def main() -> int:
    data = load_corpus()
    print(f"corpus: {len(data)}")
    results = []
    for size in SIZES:
        for lr in LRS:
            net = DeepPolicyNet(obs_dim=OBS_DIM, hidden=size, seed=3)
            n_params = sum(p.size for p in net.params)
            t0 = time.time()
            _, m = _behavior_clone_deep(net, data, epochs=60, lr=lr, batch_size=32)
            row = {"hidden": size, "lr": lr, "params": n_params,
                   "macro_f1": m["macro_f1"], "acc": m["budget_acc"],
                   "majority": m["majority_acc"], "train_s": round(time.time() - t0)}
            results.append(row)
            print(f"LADDER {size} lr={lr:g}: params {n_params:,} "
                  f"macro-F1 {m['macro_f1']:.3f} acc {m['budget_acc']:.3f} "
                  f"({row['train_s']}s)", flush=True)
    (SERVER_ROOT / "models" / "scale_ladder.json").write_text(
        json.dumps(results, indent=2))
    print("saved -> models/scale_ladder.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
