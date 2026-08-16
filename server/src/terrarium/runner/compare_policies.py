"""Policy comparison experiment: heuristic vs RL vs hybrid for one nation.

Answers the architecture question: does the learned tactical layer (alone or
combined with the LLM strategy layer) outperform hand-written doctrine for
the target nation under a stress scenario?

Example:
  uv run python -m terrarium.runner.compare_policies --preset default \
      --nation SAH --scenario scenarios/drought_sahelia.yaml --seeds 5

  # hybrid needs ZAI_API_KEY in server/.env
  uv run python -m terrarium.runner.compare_policies --nation VLT --with-hybrid \
      --scenario scenarios/chokepoint_closure.yaml
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..agents.llm import make_policy_factory
from ..sim.engine import Engine
from ..sim.interventions import load_scenario
from ..util.env import load_env
from ..world.presets import load_preset

SERVER_ROOT = Path(__file__).resolve().parents[3]


def run_one(spec, seed: int, ticks: int, policy: str, scenario, rl_nation, rl_weights) -> dict:
    factory = make_policy_factory(policy, seed=seed, rl_nation=rl_nation, rl_weights=rl_weights)
    policies = {ns.id: factory(ns) for ns in spec.nations}
    eng = Engine(spec, policies, seed=seed, out_dir=None)
    eng.run(ticks, scenario)
    nat = eng.nations[rl_nation]
    shortages = sum(1 for r in eng.event_log.records
                    if r.type == "shortage" and (r.actor == rl_nation or rl_nation in r.targets))
    return {
        "gdp": round(nat.gdp, 3),
        "stability": round(nat.stability, 2),
        "approval": round(nat.approval, 2),
        "military": round(nat.military, 2),
        "collapsed": nat.collapsed,
        "shortages": shortages,
        "wars": len(nat.at_war_with),
    }


def main(argv: list[str] | None = None) -> int:
    load_env(SERVER_ROOT / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="default")
    ap.add_argument("--nation", required=True)
    ap.add_argument("--scenario", default=None)
    ap.add_argument("--ticks", type=int, default=36)
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--start-seed", type=int, default=42)
    ap.add_argument("--rl-weights", default=None)
    ap.add_argument("--with-hybrid", action="store_true",
                    help="also evaluate the LLM+RL hybrid (needs ZAI_API_KEY)")
    args = ap.parse_args(argv)

    spec = load_preset(args.preset)
    scenario = load_scenario(args.scenario)
    seeds = [args.start_seed + i for i in range(args.seeds)]

    modes = ["heuristic", "rl"] + (["hybrid"] if args.with_hybrid else [])
    results: dict[str, list[dict]] = {}
    for mode in modes:
        runs = [run_one(spec, s, args.ticks, mode, scenario, args.nation, args.rl_weights)
                for s in seeds]
        results[mode] = runs

    def agg(runs):
        keys = ["gdp", "stability", "approval", "military", "shortages"]
        out = {k: round(sum(r[k] for r in runs) / len(runs), 2) for k in keys}
        out["collapsed_rate"] = round(sum(1 for r in runs if r["collapsed"]) / len(runs), 2)
        return out

    summary = {m: agg(runs) for m, runs in results.items()}
    report = {
        "preset": args.preset, "nation": args.nation,
        "scenario": args.scenario or "baseline", "seeds": seeds, "ticks": args.ticks,
        "summary": summary, "raw": results,
    }
    out_path = SERVER_ROOT.parent / "analysis" / f"compare_{args.preset}_{args.nation}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\npolicy comparison — {args.nation} @ {args.preset} / {args.scenario or 'baseline'} "
          f"({args.seeds} seeds x {args.ticks} ticks)")
    hdr = f"{'policy':10s} {'gdp':>8s} {'stabil':>7s} {'approv':>7s} {'short':>6s} {'collapse':>8s}"
    print(hdr)
    for m, a in summary.items():
        print(f"{m:10s} {a['gdp']:8.2f} {a['stability']:7.1f} {a['approval']:7.1f} "
              f"{a['shortages']:6.1f} {a['collapsed_rate']:8.0%}")
    print(f"\n[report] {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
