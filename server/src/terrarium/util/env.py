"""Tiny .env loader (no external dependency)."""
from __future__ import annotations

import os
from pathlib import Path


def load_env(path: str | Path = ".env") -> dict[str, str]:
    p = Path(path)
    if not p.exists():
        return {}
    loaded: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)
        loaded[k] = v
    return loaded
