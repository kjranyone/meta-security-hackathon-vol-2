"""LLM教師データのバッチ収集(多シナリオ・追記可能・監査付き)。

distill.py の収集フェーズを単独実行可能にしたもの:
  - 複数シナリオ×複数国の直積を指定順に走査し、(観測, 行動) を逐次jsonlへ追記
  - 1ペア(nation×scenario×episode)終了毎にflush — 長時間runの部分成果が残る
  - 各サンプルに preset/scenario/nation/episode/seed のメタを記録
  - calls/fallbacks 監査はdistillと同じ規律(API実呼び出しゼロならfail)

Usage:
  uv run python scripts/collect_teacher_batch.py --preset earth \
      --nations JPN,IND --scenarios scenarios/earth_hormuz.yaml \
      --episodes 1 --horizon 24 --seed 100 --out models/teacher_w1_a.jsonl
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
from terrarium.sim.interventions import load_scenario
from terrarium.world.presets import load_preset

SERVER_ROOT = Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="batch LLM teacher data collection")
    ap.add_argument("--preset", default="earth")
    ap.add_argument("--nations", required=True, help="comma list of teacher nations")
    ap.add_argument("--scenarios", required=True,
                    help="comma list of scenario yaml paths (use 'none' for no scenario)")
    ap.add_argument("--episodes", type=int, default=1, help="episodes per (nation, scenario)")
    ap.add_argument("--horizon", type=int, default=24)
    ap.add_argument("--seed", type=int, default=100)
    ap.add_argument("--out", required=True, help="output jsonl (append)")
    ap.add_argument("--samples-per-state", type=int, default=1,
                    help="k>1: 同一状態でk回サンプリングし soft-target/自己一致率測定用に"
                         "1行にactionsリストで記録(soft corpus形式)")
    args = ap.parse_args(argv)

    spec = load_preset(args.preset)
    personas = {ns.id: ns.persona for ns in spec.nations}
    valid = {ns.id for ns in spec.nations}
    nations = [n.strip() for n in args.nations.split(",") if n.strip()]
    bad = [n for n in nations if n not in valid]
    if bad:
        print(f"[collect] unknown nations {bad} in preset {args.preset}", file=sys.stderr)
        return 2

    scen_paths = []
    for s in args.scenarios.split(","):
        s = s.strip()
        if not s:
            continue
        scen_paths.append(None if s == "none" else s)
    scen_names = ["none" if p is None else Path(p).stem for p in scen_paths]
    scenarios = [load_scenario(p) if p else None for p in scen_paths]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n_existing = 0
    if out.exists():
        with out.open() as f:
            n_existing = sum(1 for _ in f)

    t0 = time.time()
    pairs = [(nid, si) for nid in nations for si in range(len(scenarios))]
    total_calls = 0
    total_fallbacks = 0
    n_new = 0
    with out.open("a", encoding="utf-8") as fout:
        for idx, (nid, si) in enumerate(pairs):
            teacher = ZaiLLMPolicy(nid, personas.get(nid, ""))
            calls0, fb0 = teacher.calls, teacher.fallbacks
            for ep in range(args.episodes):
                seed = args.seed + idx * 97 + ep * 13
                env = NationEnv(args.preset, nid, seed=seed, horizon=args.horizon,
                                scenario=scenarios[si])
                obs = env.reset()
                done = False
                while not done:
                    view = env.eng.nation_view(nid)
                    acts, fbs = [], []
                    for _ in range(max(1, args.samples_per_state)):
                        for attempt in range(2):
                            c0, f0 = teacher.calls, teacher.fallbacks
                            d = teacher.decide(view)
                            fb = (teacher.fallbacks > f0) or \
                                str(d.rationale).startswith("[LLM parse fallback]")
                            if not fb:
                                break
                            time.sleep(20)
                        acts.append(decisions_to_action(d))
                        fbs.append(bool(fb))
                    if args.samples_per_state > 1:
                        fout.write(json.dumps({
                            "obs": obs.tolist(), "actions": acts, "fallbacks": fbs,
                            "preset": args.preset, "scenario": scen_names[si],
                            "nation": nid, "episode": ep, "seed": seed,
                        }) + "\n")
                    else:
                        fout.write(json.dumps({
                            "obs": obs.tolist(), "action": acts[0], "fallback": fbs[0],
                            "preset": args.preset, "scenario": scen_names[si],
                            "nation": nid, "episode": ep, "seed": seed,
                        }) + "\n")
                    n_new += 1
                    obs, _, done, _ = env.step(acts[0])
                fout.flush()
            d_calls, d_fb = teacher.calls - calls0, teacher.fallbacks - fb0
            total_calls += d_calls
            total_fallbacks += d_fb
            print(f"[collect] {scen_names[si]}×{nid}: {args.episodes}ep "
                  f"(real {d_calls} / fallback {d_fb}, total {n_existing + n_new} rec, "
                  f"{time.time() - t0:.0f}s)", flush=True)
            if d_calls == 0:
                print(f"[collect] ERROR: zero real API calls for {nid} — "
                      f"check ZAI_API_KEY", file=sys.stderr)
                return 3
    print(f"[collect] done: +{n_new} samples -> {out} "
          f"(calls {total_calls}, fallbacks {total_fallbacks})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
