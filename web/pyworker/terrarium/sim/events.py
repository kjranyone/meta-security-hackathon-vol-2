"""Event sourcing: append-only JSONL log with causal parent links."""
from __future__ import annotations

import json
from pathlib import Path
from typing import IO, Optional

from ..world.models import EventRecord


class EventLog:
    def __init__(self, out: Optional[IO[str]] = None):
        self.records: list[EventRecord] = []
        self._out = out
        self._counter = 0
        self._index: dict[str, EventRecord] = {}   # id -> record（by_idを線形探索させない）

    def emit(
        self,
        tick: int,
        type: str,
        text: str,
        actor: Optional[str] = None,
        targets: Optional[list[str]] = None,
        parents: Optional[list[str]] = None,
        data: Optional[dict] = None,
    ) -> EventRecord:
        self._counter += 1
        rec = EventRecord(
            id=f"e{self._counter:06d}",
            tick=tick,
            type=type,
            actor=actor,
            targets=targets or [],
            parents=parents or [],
            data=data or {},
            text=text,
        )
        self.records.append(rec)
        self._index[rec.id] = rec
        if self._out is not None:
            self._out.write(json.dumps(rec.model_dump(), ensure_ascii=False) + "\n")
            self._out.flush()
        return rec

    def by_id(self, eid: str) -> Optional[EventRecord]:
        return self._index.get(eid)

    def cascade_ancestors(self, eid: str) -> list[str]:
        """All transitive ancestors (the causal upstream of an event)."""
        seen: set[str] = set()
        stack = [eid]
        while stack:
            cur = self.by_id(stack.pop())
            if cur is None:
                continue
            for p in cur.parents:
                if p not in seen:
                    seen.add(p)
                    stack.append(p)
        return sorted(seen)

    def descendants_of(self, eid: str) -> list[EventRecord]:
        children: dict[str, list[EventRecord]] = {}
        for rec in self.records:
            for p in rec.parents:
                children.setdefault(p, []).append(rec)
        out: list[EventRecord] = []
        stack = [eid]
        while stack:
            for child in children.get(stack.pop(), []):
                out.append(child)
                stack.append(child.id)
        return out


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
