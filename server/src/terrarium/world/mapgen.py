"""Deterministic map generation from a WorldSpec (no RNG: pure function of spec)."""
from __future__ import annotations

from .hexgrid import hex_distance, neighbors, offset_to_axial
from .models import HexTile, NationSpec, ResourceKind, Terrain, WorldSpec


def generate_map(spec: WorldSpec) -> dict[tuple[int, int], HexTile]:
    tiles: dict[tuple[int, int], HexTile] = {}
    for row in range(spec.rows):
        for col in range(spec.cols):
            q, r = offset_to_axial(col, row)
            tiles[(q, r)] = HexTile(q=q, r=r, terrain=Terrain.OCEAN)

    for nation in spec.nations:
        cq, cr = offset_to_axial(*nation.center)
        for (q, r), tile in tiles.items():
            d = hex_distance((q, r), (cq, cr))
            if d <= nation.radius:
                tile.terrain = nation.terrain_bias
                tile.owner = nation.id

    # resources: deterministic offsets around each capital
    offsets = [(0, 0), (1, 0), (0, -1), (-1, 0), (1, -1), (-1, 1), (0, 1), (-1, -1)]
    for nation in spec.nations:
        cq, cr = offset_to_axial(*nation.center)
        for i, res in enumerate(nation.resources):
            dq, dr = offsets[i % len(offsets)]
            tile = tiles.get((cq + dq, cr + dr))
            if tile is not None and tile.owner == nation.id:
                tile.resource = res

    # chokepoints must sit on ocean between nations; BFS to nearest ocean hex
    for cp in spec.chokepoints:
        start = tiles.get((cp.q, cp.r))
        if start is None:
            continue
        if start.terrain is Terrain.OCEAN:
            continue
        frontier = [(cp.q, cp.r)]
        seen = {(cp.q, cp.r)}
        while frontier:
            cur = frontier.pop(0)
            cand = tiles.get(cur)
            if cand is not None and cand.terrain is Terrain.OCEAN:
                cp.q, cp.r = cur
                break
            for nb in neighbors(*cur):
                if nb not in seen and nb in tiles:
                    seen.add(nb)
                    frontier.append(nb)
    return tiles


def nation_hexes(tiles: dict[tuple[int, int], HexTile], nation_id: str) -> list[HexTile]:
    return [t for t in tiles.values() if t.owner == nation_id]
