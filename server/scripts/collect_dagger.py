"""P1(DAgger): 学習済みRL方策の訪問状態をLLM教師がラベリングする収集機。

BCの分布シフト(配備崩壊42カ国)への古典的処置。エンジンはRL方策の行動で
進行し、各状態で教師の仮想的決定(実行はしない)をラベルとして記録する。
決定論エンジンなので「学生が訪れた状態分布」を正確に集められる。

Usage:
  uv run python scripts/collect_dagger.py --weights models/generalist_llm_deep_bc.npz \
      --preset earth --nations JPN,TWN --scenario scenarios/earth_hormuz.yaml \
      --episodes 1 --horizon 24 --out models/teacher_dagger_r1.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from terrarium.agents.llm import ZaiLLMPolicy
from terrarium.rl.distill import decisions_to_action
from terrarium.rl.env import NationEnv
from terrarium.rl.nets import DeepPolicyNet
from terrarium.sim.interventions import load_scenario
from terrarium.world.presets import load_preset

SERVER_ROOT = Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="DAgger state labeling with LLM teacher")
    ap.add_argument("--weights", required=True, help="student (deep net) weights")
    ap.add_argument("--preset", default="earth")
    ap.add_argument("--nations", required=True)
    ap.add_argument("--scenario", default=None)
    ap.add_argument("--episodes", type=int, default=1)
    ap.add_argument("--horizon", type=int, default=24)
    ap.add_argument("--seed", type=int, default=900)
    ap.add_argument("--deterministic", type=int, default=1,
                    help="学生の行動をargmax(決定論)にする")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    spec = load_preset(args.preset)
    personas = {ns.id: ns.persona for ns in spec.nations}
    valid = {ns.id for ns in spec.nations}
    nations = [n.strip() for n in args.nations.split(",") if n.strip() in valid]
    scenario = load_scenario(args.scenario) if args.scenario else None
    net = DeepPolicyNet.load(args.weights)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    n_new = n_fb = 0
    with out.open("a", encoding="utf-8") as fout:
        for i, nid in enumerate(nations):
            teacher = ZaiLLMPolicy(nid, personas.get(nid, ""))
            for ep in range(args.episodes):
                seed = args.seed + i * 97 + ep * 13
                env = NationEnv(args.preset, nid, seed=seed, horizon=args.horizon,
                                scenario=scenario)
                obs = env.reset()
                done = False
                while not done:
                    view = env.eng.nation_view(nid)
                    # 教師ラベル(実行しない)
                    from terrarium.agents.llm import robust_decide
                    d, fb = robust_decide(teacher, view)
                    n_fb += int(fb)
                    # 学生の行動で世界を進める
                    a = net.act(obs, deterministic=bool(args.deterministic))
                    act = {k: a[k] for k in ("budget_idx", "posture_idx",
                                             "rationing", "propaganda") if k in a}
                    fout.write(json.dumps({
                        "obs": obs.tolist(), "action": decisions_to_action(d),
                        "fallback": bool(fb), "dagger": True,
                        "preset": args.preset,
                        "scenario": Path(args.scenario).stem if args.scenario else "none",
                        "nation": nid, "episode": ep, "seed": seed,
                    }) + "\n")
                    n_new += 1
                    obs, _, done, _ = env.step(act)
                fout.flush()
            print(f"[dagger] {nid}: ep{ep+1} done ({n_new} total, fb {n_fb}, "
                  f"{time.time() - t0:.0f}s)", flush=True)
            if teacher.calls == 0:
                print(f"[dagger] ERROR: zero real API calls for {nid}", file=sys.stderr)
                return 3
    print(f"[dagger] done: +{n_new} labeled states -> {out} (fallback {n_fb})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
