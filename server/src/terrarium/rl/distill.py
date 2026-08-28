"""LLM→RL 蒸留: 思考AIが教師データを生成し、学習AIがそれを模倣学習する。

「最先端のLLMが自律訓練する」プログラムの実体:
  1. 収集  — エンジン内でLLM(z.ai GLM)政府の決定を (観測OBS_DIM次元, 行動) として記録
  2. 蒸留  — 軽量RLネット(numpy MLP/GRU)が行動クローン(教師あり交差エントロピー)
  3. 微調整 — 自己対戦actor-criticでLLMの戦術を出発点に改善

LLM 1回の推論は高価だが、蒸留後の戦術AIはnumpy/CPUで即時に動く。
「LLMの戦略判断を、LLMなしで動く全国家に配布する」パイプラインである。

Usage:
  uv run python -m terrarium.rl.distill --preset earth --episodes-per-nation 2 \
      --scenario scenarios/earth_hormuz.yaml --finetune 800 --out models/generalist_llm.npz
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from .env import NationEnv, OBS_DIM, obs_from_view
from .nets import BUDGET_PRESETS, POSTURES, PolicyNet
from .train import run_episode

SERVER_ROOT = Path(__file__).resolve().parents[3]


def decisions_to_action(d) -> dict:
    """LLM/heuristicのDecisionsをRLの行動インデックスへ写像。
    予算はBUDGET_PRESETS中最も近いもの（L2）、姿勢は直接対応。"""
    bud = d.budget or {}
    keys = ("military", "welfare", "stockpile", "subsidy")
    vec = np.array([float(bud.get(k, 0.25)) for k in keys])
    dists = [float(np.linalg.norm(vec - np.array([p[k] for k in keys]))) for p in BUDGET_PRESETS]
    budget_idx = int(np.argmin(dists))
    posture = d.military_posture if d.military_posture in POSTURES else "neutral"
    return {
        "budget_idx": budget_idx,
        "posture_idx": POSTURES.index(posture),
        "rationing": int(bool(d.rationing)),
        "propaganda": int(bool(d.propaganda)),
    }


def collect_teacher_data(preset: str, nation_ids: list[str], episodes_per_nation: int,
                         scenario, horizon: int, seed: int, api: bool = True) -> list[dict]:
    """LLM政府をエンジン内で運転し (obs, action) を記録する。"""
    from ..world.presets import load_preset
    from ..agents.llm import ZaiLLMPolicy

    spec = load_preset(preset)
    personas = {ns.id: ns.persona for ns in spec.nations}
    data: list[dict] = []
    t0 = time.time()
    n_calls = 0
    for i, nid in enumerate(nation_ids):
        env = NationEnv(preset, nid, seed=seed + i, horizon=horizon, scenario=scenario)
        teacher = ZaiLLMPolicy(nid, personas.get(nid, ""))
        for ep in range(episodes_per_nation):
            obs = env.reset()
            done = False
            while not done:
                view = env.eng.nation_view(nid)
                d = teacher.decide(view)
                n_calls += 1
                act = decisions_to_action(d)
                data.append({"obs": obs.copy(), "action": act})
                obs, _, done, _ = env.step(act)
            ok = teacher.calls
            bad = teacher.fallbacks
            if ok == 0:
                raise RuntimeError(
                    f"LLM teacher made 0 real API calls ({bad} fallbacks). "
                    f"Check ZAI_API_KEY — 蒸留教師がフォールバック偽装になるのを防ぐ")
            print(f"[distill] {nid} ep{ep+1}: {len(data)} samples "
                  f"(real {ok} / fallback {bad}, {time.time()-t0:.0f}s)", flush=True)
    return data


def eval_agreement(net, data: list[dict]) -> dict:
    """教師との一致率メトリクス。budget多数派基線・macro-F1・クラス別recall・
    全頭一致を返す(「82%は何を意味するか」を測るための正直な指標)。"""
    from collections import Counter
    preds = []
    for s in data:
        out = net.forward(s["obs"])
        preds.append((int(np.argmax(out["budget_logits"])),
                      int(np.argmax(out["posture_logits"])),
                      1 if out["ration_logit"] > 0 else 0,
                      1 if out["propa_logit"] > 0 else 0))
    labels = [s["action"] for s in data]
    n = len(data)
    majority = Counter(a["budget_idx"] for a in labels).most_common(1)[0][1] / n
    classes = sorted({a["budget_idx"] for a in labels})
    conf = {c: {"tp": 0, "pred": 0, "true": 0} for c in classes}
    b_hit = p_hit = f_hit = 0
    for (pb, pp, pr, pg), a in zip(preds, labels):
        b_hit += int(pb == a["budget_idx"])
        p_hit += int(pp == a["posture_idx"])
        f_hit += int(pb == a["budget_idx"] and pp == a["posture_idx"]
                     and pr == a["rationing"] and pg == a["propaganda"])
        if pb in conf:
            conf[pb]["pred"] += 1
        conf[a["budget_idx"]]["true"] += 1
        if pb == a["budget_idx"]:
            conf[pb]["tp"] += 1
    f1s = []
    for c in classes:
        prec = conf[c]["tp"] / conf[c]["pred"] if conf[c]["pred"] else 0.0
        rec = conf[c]["tp"] / conf[c]["true"] if conf[c]["true"] else 0.0
        f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
    return {
        "n": n, "budget_acc": b_hit / n, "majority_acc": majority,
        "macro_f1": float(np.mean(f1s)),
        "per_class": {c: {"recall": conf[c]["tp"] / conf[c]["true"] if conf[c]["true"] else 0.0,
                          "support": conf[c]["true"]} for c in classes},
        "posture_acc": p_hit / n, "full_acc": f_hit / n,
    }


def stratified_split(data: list[dict], valid_frac: float = 0.2, seed: int = 0):
    """budget_idxで層化したtrain/valid分割(稀クラスをvalidに漏らさない)。"""
    by_class: dict[int, list[dict]] = {}
    for s in data:
        by_class.setdefault(s["action"]["budget_idx"], []).append(s)
    rng = np.random.default_rng(seed)
    train, valid = [], []
    for c in sorted(by_class):
        items = list(by_class[c])
        rng.shuffle(items)
        n_valid = max(1, int(round(len(items) * valid_frac))) if len(items) >= 2 else 0
        valid += items[:n_valid]
        train += items[n_valid:]
    return train, valid


def _behavior_clone_deep(net, data: list[dict], epochs: int, lr: float,
                         batch_size: int = 32, seed: int = 0):
    """DeepPolicyNet用BC: ミニバッチAdam + valid macro-F1でのearly-stopping。
    返り値: (history, valid_metrics_at_best)"""
    train, valid = stratified_split(data, seed=seed)
    print(f"[distill] BC deep: {len(train)} train / {len(valid)} valid "
          f"(stratified; classes={sorted({s['action']['budget_idx'] for s in data})})", flush=True)
    m0 = eval_agreement(net, valid)
    print(f"[distill] BC epoch 0: valid budget-acc {m0['budget_acc']:.3f} "
          f"macro-F1 {m0['macro_f1']:.3f} (majority {m0['majority_acc']:.3f})", flush=True)
    best = {"f1": m0["macro_f1"], "epoch": 0,
            "state": [p.copy() for p in net.params], "metrics": m0}
    history: list[dict] = []
    # 逆頻度クラス重み(稀クラスの学習を保証するため。教師分布の偏りへの対策)
    from collections import Counter as _Counter
    cnt = _Counter(s["action"]["budget_idx"] for s in train)
    K = len(cnt)
    wmap = {c: len(train) / (K * n) for c, n in cnt.items()}
    for ep in range(epochs):
        rng = np.random.default_rng(ep + 1)
        idx = rng.permutation(len(train))
        lr_ep = lr * (0.5 ** (ep // 30))   # 30エポック毎に半減(巨大ネットの過適合抑制)
        losses = []
        for s in range(0, len(train), batch_size):
            rows = idx[s:s + batch_size]
            batch = [(train[i]["obs"], train[i]["action"]["budget_idx"],
                      train[i]["action"]["posture_idx"],
                      train[i]["action"]["rationing"], train[i]["action"]["propaganda"])
                     for i in rows]
            w = np.array([wmap[train[i]["action"]["budget_idx"]] for i in rows])
            if not batch:
                continue
            losses.append(net.imitate_batch(batch, lr=lr_ep, weights=w))
        m_tr = eval_agreement(net, train)
        m_va = eval_agreement(net, valid)
        history.append({"epoch": ep + 1, "loss": float(np.mean(losses)),
                        "train_budget_acc": m_tr["budget_acc"],
                        "valid_budget_acc": m_va["budget_acc"],
                        "valid_macro_f1": m_va["macro_f1"]})
        print(f"[distill] BC epoch {ep+1}: loss {np.mean(losses):.3f} "
              f"train {m_tr['budget_acc']:.3f} | valid budget-acc {m_va['budget_acc']:.3f} "
              f"macro-F1 {m_va['macro_f1']:.3f} (majority {m_va['majority_acc']:.3f})", flush=True)
        if m_va["macro_f1"] > best["f1"]:
            best = {"f1": m_va["macro_f1"], "epoch": ep + 1,
                    "state": [p.copy() for p in net.params], "metrics": m_va}
    for p, s in zip(net.params, best["state"]):
        p[...] = s
    print(f"[distill] BC best: epoch {best['epoch']} "
          f"valid budget-acc {best['metrics']['budget_acc']:.3f} "
          f"macro-F1 {best['metrics']['macro_f1']:.3f} "
          f"(majority {best['metrics']['majority_acc']:.3f})", flush=True)
    return history, best["metrics"]


def behavior_clone(net, data: list[dict], epochs: int = 12, lr: float = 2e-3):
    """行動クローニング: 教師行動への交差エントロピー。
    DeepPolicyNet(imitate_batch持ち)はミニバッチAdam+hold-out early-stopping、
    PolicyNetは従来のSGDループ(既存テスト互換)。"""
    if hasattr(net, "imitate_batch"):
        return _behavior_clone_deep(net, data, epochs=epochs, lr=lr)
    losses = []
    for ep in range(epochs):
        idx = np.random.default_rng(ep).permutation(len(data))
        tot, hits, n = 0.0, 0, 0
        for i in idx:
            s = data[i]
            out = net.forward(s["obs"]) if hasattr(net, "forward") else None
            if out is None:  # GRUなどforward()を持たない場合はactで代用
                continue
            z_b = out["budget_logits"]
            z_p = out["posture_logits"]
            z_r = out["ration_logit"]
            z_g = out["propa_logit"]
            tb, tp = s["action"]["budget_idx"], s["action"]["posture_idx"]
            tr, tg = s["action"]["rationing"], s["action"]["propaganda"]
            p_b = _softmax(z_b); p_p = _softmax(z_p)
            pr = _sg(z_r) if tr else 1.0 - _sg(z_r)
            pg_ = _sg(z_g) if tg else 1.0 - _sg(z_g)
            loss = float(-np.log(p_b[tb] + 1e-12) - np.log(p_p[tp] + 1e-12)
                         - np.log(pr + 1e-12) - np.log(pg_ + 1e-12))
            tot += loss
            hits += int(int(np.argmax(z_b)) == tb)
            n += 1
            net.imitate(s["obs"], tb, tp, tr, tg, lr=lr)
        losses.append(tot / max(1, n))
        print(f"[distill] BC epoch {ep+1}: loss {losses[-1]:.3f} budget-acc {hits/max(1,n):.2f}",
              flush=True)
    return losses


def _sg(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


def _softmax(z):
    z = z - z.max()
    e = np.exp(z)
    return e / e.sum()


def load_teacher_files(paths: list[str], drop_fallback: bool = True) -> list[dict]:
    """教師データjsonl群を読み込みマージ(obs/actionキーは旧キャッシュと共通)。
    drop_fallback: 収集時にフォールバック(heuristic代行)とタグされたサンプルを除外。
    旧キャッシュ(タグなし)は v9監査(2/167=1.2%)を踏まえそのまま読む。"""
    data = []
    n_dropped = 0
    for p in paths:
        fp = Path(p)
        if not fp.is_absolute():
            fp = SERVER_ROOT / p if not fp.exists() else fp
        with fp.open() as f:
            for line in f:
                rec = json.loads(line)
                if drop_fallback and rec.get("fallback"):
                    n_dropped += 1
                    continue
                data.append({"obs": np.asarray(rec["obs"], dtype=np.float32),
                             "action": rec["action"],
                             **({"meta": {k: rec[k] for k in rec if k not in ("obs", "action")}}
                                if any(k not in ("obs", "action") for k in rec) else {})})
        print(f"[distill] loaded {len(data)} cumulative samples from {fp}")
    if n_dropped:
        print(f"[distill] dropped {n_dropped} fallback-tagged samples")
    return data


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="LLM→RL distillation")
    ap.add_argument("--preset", default="earth")
    ap.add_argument("--nations", default=None, help="teacher nations (comma list; default=all)")
    ap.add_argument("--episodes-per-nation", type=int, default=2)
    ap.add_argument("--horizon", type=int, default=24)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--scenario", default="scenarios/earth_hormuz.yaml")
    ap.add_argument("--data", default=None,
                    help="comma list of teacher jsonl files (skip live collection)")
    ap.add_argument("--bc-epochs", type=int, default=12)
    ap.add_argument("--bc-lr", type=float, default=1e-3)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--finetune", type=int, default=800, help="A2C fine-tune episodes (0=skip)")
    ap.add_argument("--finetune-lr", type=float, default=3e-4)
    ap.add_argument("--eval-nation", default="JPN")
    ap.add_argument("--out", default=None)
    ap.add_argument("--hidden", type=str, default="64",
                    help="hidden width; int for PolicyNet, comma list (e.g. 2048,2048,2048,2048) for DeepPolicyNet")
    args = ap.parse_args(argv)

    from ..sim.interventions import load_scenario
    scenario = load_scenario(args.scenario) if args.scenario else None

    if args.data:
        data = load_teacher_files(args.data.split(","))
    else:
        from ..world.presets import load_preset
        spec = load_preset(args.preset)
        nation_ids = (args.nations.split(",") if args.nations
                      else sorted(ns.id for ns in spec.nations))
        nation_ids = [n for n in nation_ids if n in {s.id for s in spec.nations}]
        print(f"[distill] teachers: {len(nation_ids)} nations x {args.episodes_per_nation} eps")
        data = collect_teacher_data(args.preset, nation_ids, args.episodes_per_nation,
                                    scenario, args.horizon, args.seed)
        cache = SERVER_ROOT / "models" / "llm_teacher_data.jsonl"
        cache.parent.mkdir(parents=True, exist_ok=True)
        with cache.open("w", encoding="utf-8") as f:
            for s in data:
                f.write(json.dumps({"obs": s["obs"].tolist(), "action": s["action"]}) + "\n")
        print(f"[distill] {len(data)} samples cached -> {cache}")

    if "," in args.hidden:
        from .nets import DeepPolicyNet
        net = DeepPolicyNet(obs_dim=OBS_DIM, hidden=[int(h) for h in args.hidden.split(",")],
                            seed=args.seed)
        n_params = sum(p.size for p in net.params)
        print(f"[distill] DeepPolicyNet hidden={net.hidden} params={n_params:,} "
              f"(~{n_params * 4 / 1e6:.1f}MB f32)")
    else:
        net = PolicyNet(obs_dim=OBS_DIM, hidden=int(args.hidden), seed=args.seed)
    result = behavior_clone(net, data, epochs=args.bc_epochs, lr=args.bc_lr)
    if isinstance(result, tuple):
        bc_history, bc_metrics = result
    else:
        bc_history, bc_metrics = result, eval_agreement(net, data)

    # 蒸留前後の評価（教師なしのA2C純訓練との比較用に同じ評価プロトコル）
    env = NationEnv(args.preset, args.eval_nation, seed=99, horizon=args.horizon,
                    scenario=scenario)
    from .train import evaluate
    before = evaluate(env, net, [11, 22], args.horizon)
    ft_log = []
    if args.finetune > 0:
        for ep in range(args.finetune):
            env.seed = 5000 + (ep % 8)
            run_episode(env, net, train=True, lr=args.finetune_lr)
            if (ep + 1) % max(1, args.finetune // 10) == 0:
                r = evaluate(env, net, [11, 22], args.horizon)
                m = eval_agreement(net, data)
                ft_log.append({"episode": ep + 1, "eval_reward": r,
                               "budget_acc": m["budget_acc"], "macro_f1": m["macro_f1"]})
                print(f"[distill] finetune {ep+1}/{args.finetune}: eval {r:.2f} "
                      f"budget-acc {m['budget_acc']:.3f} macro-F1 {m['macro_f1']:.3f}", flush=True)
    after = evaluate(env, net, [11, 22], args.horizon)
    print(f"[distill] eval {args.eval_nation}: BC {before:.2f} -> BC+A2C {after:.2f}")

    out = Path(args.out) if args.out else SERVER_ROOT / "models" / "generalist_llm.npz"
    net.save(out)
    (out.with_suffix(".curve.json")).write_text(json.dumps([
        {"phase": "bc", "eval_reward": before, "metrics": bc_metrics,
         "history": bc_history},
        {"phase": "bc+a2c", "eval_reward": after, "episodes": args.finetune,
         "finetune_log": ft_log},
    ], ensure_ascii=False))
    print(f"[distill] saved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
