"""Axial hex grid utilities (pointy-top, odd-r offset input)."""
from __future__ import annotations

from typing import Iterable

# offset (odd-r) -> axial
def offset_to_axial(col: int, row: int) -> tuple[int, int]:
    q = col - (row - (row & 1)) // 2
    return q, row


def axial_to_offset(q: int, r: int) -> tuple[int, int]:
    col = q + (r - (r & 1)) // 2
    return col, r


AXIAL_DIRS = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]


def neighbors(q: int, r: int) -> Iterable[tuple[int, int]]:
    for dq, dr in AXIAL_DIRS:
        yield q + dq, r + dr


def hex_distance(a: tuple[int, int], b: tuple[int, int]) -> int:
    dq, dr = a[0] - b[0], a[1] - b[1]
    return (abs(dq) + abs(dq + dr) + abs(dr)) // 2


def pixel(q: int, r: int, size: float) -> tuple[float, float]:
    """Pointy-top layout pixel center."""
    x = size * 3.0 ** 0.5 * (q + r / 2)
    y = size * 1.5 * r
    return x, y


def hex_corners(cx: float, cy: float, size: float) -> list[tuple[float, float]]:
    import math

    pts = []
    for i in range(6):
        ang = math.pi / 180 * (60 * i - 30)  # pointy-top
        pts.append((cx + size * math.cos(ang), cy + size * math.sin(ang)))
    return pts
