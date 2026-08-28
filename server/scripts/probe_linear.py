"""D2診断: 線形プローブ(多項ロジスティック回帰・numpy)とk-NN。

深層ネット(48.6MB)と同じ層化分割・指標で比較し、
「容量がボトルネックか、観測に情報が無いのか」を切り分ける。

Usage:
  uv run python scripts/probe_linear.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from terrarium.rl.env import OBS_DESC, OBS_DIM
from terrarium.rl.distill import stratified_split, eval_agreement

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


class LinearProbe:
    """多項ロジスティック回帰(softmax・L2・Adam)。プローブ用の最小実装。"""

    def __init__(self, d: int, k: int, l2: float = 1e-2, seed: int = 0):
        rng = np.random.default_rng(seed)
        self.W = rng.normal(0, 0.01, (d, k))
        self.b = np.zeros(k)
        self.l2 = l2
        self.m = [np.zeros_like(self.W), np.zeros_like(self.b)]
        self.v = [np.zeros_like(self.W), np.zeros_like(self.b)]
        self.t = 0

    def _adam(self, dW, db, lr):
        self.t += 1
        for i, g in enumerate((dW, db)):
            self.m[i] = 0.9 * self.m[i] + 0.1 * g
            self.v[i] = 0.999 * self.v[i] + 0.001 * g * g
            mhat = self.m[i] / (1 - 0.9 ** self.t)
            vhat = self.v[i] / (1 - 0.999 ** self.t)
            step = lr * mhat / (np.sqrt(vhat) + 1e-8)
            if i == 0:
                self.W -= step
            else:
                self.b -= step

    def fit(self, X, y, epochs: int = 400, lr: float = 0.05,
            class_weights: np.ndarray | None = None):
        K = self.W.shape[1]
        Y = np.eye(K)[y]
        w = class_weights if class_weights is not None else np.ones(len(y))
        w = w / w.sum()
        for ep in range(epochs):
            z = X @ self.W + self.b
            z = z - z.max(axis=1, keepdims=True)
            p = np.exp(z) / np.exp(z).sum(axis=1, keepdims=True)
            g = (p - Y) * w[:, None]          # dL/dz (重み付きCE)
            dW = X.T @ g + self.l2 * self.W
            db = g.sum(axis=0) + self.l2 * self.b
            self._adam(dW, db, lr)

    def predict(self, X):
        z = X @ self.W + self.b
        return z.argmax(axis=1)

    def probs(self, X):
        z = X @ self.W + self.b
        z = z - z.max(axis=1, keepdims=True)
        e = np.exp(z)
        return e / e.sum(axis=1, keepdims=True)


class _ProbeWrap:
    """eval_agreement互換の最小インターフェース(forwardのみ)。"""

    def __init__(self, probe: LinearProbe):
        self.probe = probe

    def forward(self, obs):
        p = self.probe.probs(obs[None, :])[0]
        # 残りの頭は評価しない(呼ばれない前提でダミー)
        return {"budget_logits": np.log(p + 1e-12),
                "posture_logits": np.zeros(3),
                "ration_logit": 0.0, "propa_logit": 0.0, "value": 0.0}


def knn_predict(Xtr, ytr, Xva, k: int = 7):
    d2 = ((Xva[:, None, :] - Xtr[None, :, :]) ** 2).sum(axis=2)
    out = []
    for i in range(len(Xva)):
        idx = np.argsort(d2[i])[:k]
        votes = Counter(ytr[idx])
        out.append(votes.most_common(1)[0][0])
    return np.array(out)


def main() -> int:
    data = load_corpus()
    print(f"corpus: {len(data)}")
    train, valid = stratified_split(data, seed=0)
    Xtr = np.stack([s["obs"] for s in train]).astype(np.float64)
    ytr = np.array([s["action"]["budget_idx"] for s in train])
    Xva = np.stack([s["obs"] for s in valid]).astype(np.float64)
    yva = np.array([s["action"]["budget_idx"] for s in valid])
    print(f"split: {len(train)} train / {len(valid)} valid")

    classes = sorted(set(ytr.tolist()))
    # 逆頻度クラス重み(深層BCと同一のトリートメント)
    cnt = Counter(ytr.tolist())
    wmap = {c: len(ytr) / (len(cnt) * n) for c, n in cnt.items()}
    w = np.array([wmap[c] for c in ytr])

    results = {}

    # --- 線形プローブ(L2グリッド、validで選択) ---
    best = None
    for l2 in (1e-3, 1e-2, 1e-1, 1.0):
        probe = LinearProbe(OBS_DIM, 6, l2=l2, seed=0)   # budget_idx空間は6クラス固定
        probe.fit(Xtr, ytr, class_weights=w)
        yh = probe.predict(Xva)
        # クラスID→インデックス対応: classesは0始まり前提(obsのbudget_idx)
        f1s = []
        for c in classes:
            tp = int(((yh == c) & (yva == c)).sum())
            pred = int((yh == c).sum())
            true = int((yva == c).sum())
            prec = tp / pred if pred else 0.0
            rec = tp / true if true else 0.0
            f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
        mf1 = float(np.mean(f1s))
        acc = float((yh == yva).mean())
        print(f"linear L2={l2:g}: valid acc {acc:.3f} macro-F1 {mf1:.3f}")
        if best is None or mf1 > best[0]:
            best = (mf1, l2, probe)
    results["linear"] = {"macro_f1": best[0], "l2": best[1]}

    # eval_agreement互換で詳細メトリクス
    m = eval_agreement(_ProbeWrap(best[2]), valid)
    print(f"LINEAR PROBE: acc {m['budget_acc']:.3f} (majority {m['majority_acc']:.3f}) "
          f"macro-F1 {m['macro_f1:.3f']}" if False else
          f"LINEAR PROBE: acc {m['budget_acc']:.3f} (majority {m['majority_acc']:.3f}) "
          f"macro-F1 {m['macro_f1']:.3f}")
    print("  per_class:", {k: round(v["recall"], 2) for k, v in m["per_class"].items()})

    # 特徴量重要度(重みのL2ノルム上位 — 解釈の手がかり)
    Wn = np.linalg.norm(best[2].W, axis=1)
    top = np.argsort(Wn)[-12:][::-1]
    print("  top features:", [(OBS_DESC[i], round(float(Wn[i]), 3)) for i in top])

    # --- k-NN ---
    for k in (3, 7, 15):
        yh = knn_predict(Xtr, ytr, Xva, k=k)
        f1s = []
        for c in classes:
            tp = int(((yh == c) & (yva == c)).sum())
            pred = int((yh == c).sum())
            true = int((yva == c).sum())
            prec = tp / pred if pred else 0.0
            rec = tp / true if true else 0.0
            f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
        print(f"kNN k={k}: acc {float((yh == yva).mean()):.3f} macro-F1 {float(np.mean(f1s)):.3f}")

    (SERVER_ROOT / "models" / "probe_linear_result.json").write_text(
        json.dumps({"linear": results["linear"],
                    "per_class": {str(k): v["recall"] for k, v in m["per_class"].items()},
                    "top_features": [(OBS_DESC[i], float(Wn[i])) for i in top]},
                   ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
