"""Counterfactual A/B runner: same seed, baseline vs intervention scenario.

Outputs side-by-side metric series and an event-count diff, answering the
hackathon's core question: "which intervention point changes the cascade?"

Example:
  uv run python -m terrarium.runner.ab --scenario scenarios/chokepoint_closure.yaml
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from ..agents.llm import make_policy_factory
from ..sim.engine import Engine
from ..sim.interventions import Scenario, load_scenario
from ..util.env import load_env
from ..world.presets import load_preset

SERVER_ROOT = Path(__file__).resolve().parents[3]


def run_once(spec, seed: int, ticks: int, policy: str, scenario: Scenario, name: str, out: Path,
             rl_nation: str | None = None, rl_weights: str | None = None,
             run_config: dict | None = None) -> Engine:
    factory = make_policy_factory(policy, seed=seed, rl_nation=rl_nation, rl_weights=rl_weights)
    policies = {ns.id: factory(ns) for ns in spec.nations}
    eng = Engine(spec, policies, seed=seed, out_dir=out, run_name=name, run_config=run_config)
    eng.run(ticks, scenario)
    eng.write_outputs()
    return eng


def main(argv: list[str] | None = None) -> int:
    load_env(SERVER_ROOT / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="default")
    ap.add_argument("--gen-seed", type=int, default=None,
                    help="generate the world from this seed instead of loading --preset")
    ap.add_argument("--gen-nations", type=int, default=8)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--ticks", type=int, default=36)
    ap.add_argument("--policy", default="mock_llm",
                    choices=["heuristic", "mock_llm", "llm", "rl", "hybrid"])
    ap.add_argument("--rl-nation", default=None)
    ap.add_argument("--rl-weights", default=None)
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    if args.gen_seed is not None:
        from ..world.worldgen import GenParams, generate_world

        world_spec = generate_world(GenParams(seed=args.gen_seed, n_nations=args.gen_nations))
    else:
        world_spec = load_preset(args.preset)

    scenario = load_scenario(args.scenario)
    base_name = f"gen{args.gen_seed}" if args.gen_seed is not None else args.preset
    out = Path(args.out) if args.out else SERVER_ROOT / "logs" / f"ab_{scenario.name}_{base_name}"
    out.mkdir(parents=True, exist_ok=True)

    base = run_once(world_spec, args.seed, args.ticks, args.policy, Scenario(name="baseline"), "baseline",
                    out / "baseline", args.rl_nation, args.rl_weights)
    treat = run_once(world_spec, args.seed, args.ticks, args.policy, scenario, scenario.name,
                     out / "treatment", args.rl_nation, args.rl_weights)

    # metric diff csv
    fields = ["tick"] + [f"base_{k}" for k in base.series[0] if k != "tick"] + [f"treat_{k}" for k in treat.series[0] if k != "tick"]
    with (out / "ab_series.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for b, t in zip(base.series, treat.series):
            row = {"tick": b["tick"]}
            for k, v in b.items():
                if k != "tick":
                    row[f"base_{k}"] = v
            for k, v in t.items():
                if k != "tick":
                    row[f"treat_{k}"] = v
            w.writerow(row)

    # divergence metric: mean abs diff of key series
    keys = ["world_gdp", "mean_stability", "wars", "price_energy", "price_food", "collapsed"]
    divergence = {}
    for k in keys:
        try:
            divergence[k] = round(
                sum(abs(b[k] - t[k]) for b, t in zip(base.series, treat.series)) / len(base.series), 4
            )
        except KeyError:
            divergence[k] = None

    # cascade: events downstream of god interventions in treatment
    god_events = [r for r in treat.event_log.records if r.type == "god_intervention"]
    cascade_sizes = {g.id: len(treat.event_log.descendants_of(g.id)) for g in god_events}

    report = {
        "scenario": scenario.name,
        "description": scenario.description,
        "seed": args.seed,
        "ticks": args.ticks,
        "event_counts_baseline": base._event_counts(),
        "event_counts_treatment": treat._event_counts(),
        "series_divergence_mean_abs": divergence,
        "god_intervention_cascade_sizes": cascade_sizes,
    }
    (out / "ab_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
