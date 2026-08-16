"""Procedural world generator CLI.

Example:
  uv run python -m terrarium.runner.genworld --seed 7 --nations 8
  uv run python -m terrarium.runner.genworld --seed 13 --nations 10 --out presets/gen_13.yaml
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from ..world.models import Commodity
from ..world.worldgen import CONSUMPTION, YIELD_PER_UNIT, GenParams, generate_world

SERVER_ROOT = Path(__file__).resolve().parents[3]


def world_summary(spec) -> str:
    lines = []
    supply = {"energy": 0.0, "food": 0.0, "chips": 0.0}
    for n in spec.nations:
        for res in n.resources:
            if res.value == "finance":
                continue
            c = {"oil": "energy", "gas": "energy", "grain": "food", "fab": "chips",
                 "mineral": "minerals", "orbit": "space"}[res.value]
            supply[c] += YIELD_PER_UNIT
    demand = {k: v * len(spec.nations) for k, v in CONSUMPTION.items()}
    lines.append(f"nations={len(spec.nations)} chokepoints={len(spec.chokepoints)} routes={len(spec.routes)}")
    for c in ("energy", "food", "chips", "minerals", "space"):
        ratio = supply[c] / demand[c] if demand[c] else 0
        lines.append(f"  {c:7s} supply={supply[c]:5.1f} demand={demand[c]:5.1f} ratio={ratio:.2f}")
    for n in spec.nations:
        routes_in = sum(1 for r in spec.routes if r.importer == n.id)
        routes_out = sum(1 for r in spec.routes if r.exporter == n.id)
        lines.append(f"  {n.id} {n.name:14s} ({n.centroid[0]:7.1f},{n.centroid[1]:6.1f}) "
                     f"res={[r.value for r in n.resources]} import={routes_in} export={routes_out} agg={n.aggression}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate a balanced world from a seed")
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--nations", type=int, default=8)
    ap.add_argument("--chokepoints", type=int, default=6)
    ap.add_argument("--out", default=None, help="YAML output path (default presets/gen_<seed>.yaml)")
    args = ap.parse_args(argv)

    params = GenParams(seed=args.seed, n_nations=args.nations, n_chokepoints=args.chokepoints)
    spec = generate_world(params)
    out = Path(args.out) if args.out else SERVER_ROOT / "presets" / f"gen_{args.seed}.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(spec.model_dump(mode="json"), allow_unicode=True, sort_keys=False), encoding="utf-8")

    print(f"[worldgen] seed={args.seed} -> {out}")
    print(world_summary(spec))
    return 0


if __name__ == "__main__":
    sys.exit(main())
