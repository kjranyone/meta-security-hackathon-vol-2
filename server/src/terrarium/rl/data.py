"""教師データ( jsonl )の共有ローダ。

5つの実験スクリプトに散っていた読み込みロジックを1箇所に集める。
フォーマットは2種類:
  hard: {"obs": [...], "action": {...}, "fallback": bool?, ...meta}
  soft: {"obs": [...], "actions": [{...} x k], "fallbacks": [bool x k], ...meta}

semantics(既存スクリプトと同一):
  - drop_fallback=True: フォールバック混入サンプル/状態を除外(旧キャッシュの
    タグなしレコードは v9 監査(1.2%)を踏まえそのまま読む)
  - obs は float32 へ正規化
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np

SERVER_ROOT = Path(__file__).resolve().parents[3]

# 実験で参照される既定のコーパス(コミット済み)
DEFAULT_HARD = [
    "models/teacher_w1_clean.jsonl",
    "models/teacher_w2_d.jsonl",
    "models/teacher_w2_e.jsonl",
]
DEFAULT_SOFT = [
    "models/teacher_soft_f.jsonl",
    "models/teacher_soft_g.jsonl",
]


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.exists() else SERVER_ROOT / path


def load_hard(paths: list[str] | None = None, drop_fallback: bool = True) -> list[dict]:
    """hard形式(1行=1サンプル)を読む。{"obs": float32, "action": dict, "meta": dict}"""
    data: list[dict] = []
    n_drop = 0
    for path in paths or DEFAULT_HARD:
        with _resolve(path).open() as f:
            for line in f:
                r = json.loads(line)
                if drop_fallback and r.get("fallback"):
                    n_drop += 1
                    continue
                data.append({
                    "obs": np.asarray(r["obs"], dtype=np.float32),
                    "action": r["action"],
                    "meta": {k: v for k, v in r.items() if k not in ("obs", "action", "fallback")},
                })
    if n_drop:
        print(f"[data] dropped {n_drop} fallback-tagged samples from {len(paths or DEFAULT_HARD)} files")
    return data


def soft_to_item(r: dict) -> dict:
    """soft形式1レコードを統合アイテムへ: 多数決hard + 経験分布target。"""
    acts = r["actions"]
    k = len(acts)
    budgets = [a["budget_idx"] for a in acts]
    maj = Counter(budgets).most_common(1)[0][0]
    dist = np.zeros(6)
    for b in budgets:
        dist[b] += 1.0 / k
    act = dict(acts[0])
    act["budget_idx"] = maj
    return {"obs": np.asarray(r["obs"], dtype=np.float32), "action": act,
            "soft": dist, "budgets": budgets,
            "meta": {kk: r.get(kk) for kk in ("preset", "scenario", "nation")}}


def load_soft_items(paths: list[str] | None = None, drop_fallback: bool = True) -> list[dict]:
    """soft形式(kサンプリング)を統合アイテム列に。いずれかのサンプルが
    フォールバックなら状態ごと除外(bc_soft/bc_finalと同一規律)。"""
    items: list[dict] = []
    n_drop = 0
    for path in paths or DEFAULT_SOFT:
        with _resolve(path).open() as f:
            for line in f:
                r = json.loads(line)
                if drop_fallback and any(r.get("fallbacks", [])):
                    n_drop += 1
                    continue
                items.append(soft_to_item(r))
    if n_drop:
        print(f"[data] dropped {n_drop} fallback-contaminated soft states")
    return items


def load_mixed(hard: list[str] | None, soft: list[str] | None = None,
               dagger: list[str] | None = None, dagger_weight: float = 1.0) -> list[dict]:
    """bc_final用: hard(one-hot) + soft(経験分布) + DAGger(重み付き)を統合。
    各アイテム: {obs, action, soft(target分布), source, w}。Noneのソースは読まない。"""
    data: list[dict] = []
    if hard:
        for d in load_hard(hard):
            item = dict(d)
            item["soft"] = np.eye(6)[d["action"]["budget_idx"]]
            item["source"], item["w"] = "hard", 1.0
            data.append(item)
    if soft:
        for d in load_soft_items(soft):
            item = dict(d)
            item["source"], item["w"] = "soft", 1.0
            data.append(item)
    if dagger:
        for d in load_hard(dagger):
            item = dict(d)
            item["soft"] = np.eye(6)[d["action"]["budget_idx"]]
            item["source"], item["w"] = "dagger", dagger_weight
            data.append(item)
    return data


def soft_nll(net, items: list[dict]) -> float:
    """-mean_k log p(a_k): kサンプル全てへの平均対数尤度(小さいほど良い)。"""
    tot, n = 0.0, 0
    for s in items:
        z = net.forward(s["obs"])["budget_logits"]
        z = z - z.max()
        pr = np.exp(z) / np.exp(z).sum()
        for b in s["budgets"]:
            tot -= np.log(pr[b] + 1e-12)
            n += 1
    return tot / max(1, n)


def self_consistency(items: list[dict]) -> dict:
    """D1: 同一状態でkサンプルがどれだけ一致するか。"""
    n = len(items)
    agree = sum(1 for s in items if len(set(s["budgets"])) == 1)
    top = sum(1 for s in items
              if Counter(s["budgets"]).most_common(1)[0][1] >= 2)
    mean_top = float(np.mean([max(Counter(s["budgets"]).values()) / len(s["budgets"])
                              for s in items]))
    return {"n": n, "all_agree": agree / n, "majority_ge_2of3": top / n,
            "mean_top_share": mean_top}
