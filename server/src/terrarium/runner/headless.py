"""Headless CLI runner.

Example:
  uv run python -m terrarium.runner.headless \
      --preset default --seed 42 --ticks 36 --policy mock_llm \
      --scenario scenarios/chokepoint_closure.yaml --out logs/run_choke
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..agents.llm import make_policy_factory
from ..sim.engine import Engine
from ..sim.interventions import load_scenario
from ..util.env import load_env
from ..world.presets import load_preset


def main(argv: list[str] | None = None) -> int:
    load_env(Path(__file__).resolve().parents[3] / ".env")
    ap = argparse.ArgumentParser(description="Terrarium headless simulation runner")
    ap.add_argument("--preset", default="default")
    ap.add_argument("--gen-seed", type=int, default=None,
                    help="generate the world from this seed instead of loading --preset")
    ap.add_argument("--gen-nations", type=int, default=8)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--ticks", type=int, default=36)
    ap.add_argument("--policy", default="heuristic", choices=["heuristic", "mock_llm", "llm"])
    ap.add_argument("--scenario", default=None, help="scenario YAML with god interventions")
    ap.add_argument("--out", default=None, help="output dir (default logs/<name>)")
    ap.add_argument("--name", default=None)
    args = ap.parse_args(argv)

    if args.gen_seed is not None:
        from ..world.worldgen import GenParams, generate_world

        spec = generate_world(GenParams(seed=args.gen_seed, n_nations=args.gen_nations))
        base_name = f"gen{args.gen_seed}"
    else:
        spec = load_preset(args.preset)
        base_name = args.preset
    scenario = load_scenario(args.scenario)
    run_name = args.name or (
        f"{base_name}_{scenario.name}" if args.scenario else f"{base_name}_baseline"
    )
    out = Path(args.out) if args.out else Path(__file__).resolve().parents[3] / "logs" / run_name

    factory = make_policy_factory(args.policy, seed=args.seed)
    policies = {ns.id: factory(ns) for ns in spec.nations}

    eng = Engine(spec, policies, seed=args.seed, out_dir=out, run_name=run_name)
    eng.run(args.ticks, scenario)
    eng.write_outputs()

    last = eng.series[-1] if eng.series else {}
    print(f"[terrarium] run '{run_name}' -> {out}")
    print(f"[terrarium] ticks={args.ticks} events={len(eng.event_log.records)} wars={len(eng.wars)}")
    print(f"[terrarium] final: {last}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
