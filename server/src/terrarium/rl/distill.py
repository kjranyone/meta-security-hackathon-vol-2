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


def behavior_clone(net, data: list[dict], epochs: int = 12, lr: float = 2e-3) -> list[float]:
    """行動クローニング: 教師行動への交差エントロピー。"""
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="LLM→RL distillation")
    ap.add_argument("--preset", default="earth")
    ap.add_argument("--nations", default=None, help="teacher nations (comma list; default=all)")
    ap.add_argument("--episodes-per-nation", type=int, default=2)
    ap.add_argument("--horizon", type=int, default=24)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--scenario", default="scenarios/earth_hormuz.yaml")
    ap.add_argument("--bc-epochs", type=int, default=12)
    ap.add_argument("--finetune", type=int, default=800, help="A2C fine-tune episodes (0=skip)")
    ap.add_argument("--eval-nation", default="JPN")
    ap.add_argument("--out", default=None)
    ap.add_argument("--hidden", type=int, default=64, help="target net hidden width")
    args = ap.parse_args(argv)

    from ..sim.interventions import load_scenario
    scenario = load_scenario(args.scenario) if args.scenario else None

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

    net = PolicyNet(obs_dim=OBS_DIM, hidden=int(getattr(args, 'hidden', 64)), seed=args.seed)
    behavior_clone(net, data, epochs=args.bc_epochs)

    # 蒸留前後の評価（教師なしのA2C純訓練との比較用に同じ評価プロトコル）
    env = NationEnv(args.preset, args.eval_nation, seed=99, horizon=args.horizon,
                    scenario=scenario)
    from .train import evaluate
    before = evaluate(env, net, [11, 22], args.horizon)
    if args.finetune > 0:
        for ep in range(args.finetune):
            env.seed = 5000 + (ep % 8)
            run_episode(env, net, train=True, lr=2e-3)
    after = evaluate(env, net, [11, 22], args.horizon)
    print(f"[distill] eval {args.eval_nation}: BC {before:.2f} -> BC+A2C {after:.2f}")

    out = Path(args.out) if args.out else SERVER_ROOT / "models" / "generalist_llm.npz"
    net.save(out)
    (out.with_suffix(".curve.json")).write_text(json.dumps([
        {"phase": "bc", "eval_reward": before},
        {"phase": "bc+a2c", "eval_reward": after, "episodes": args.finetune},
    ]))
    print(f"[distill] saved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
