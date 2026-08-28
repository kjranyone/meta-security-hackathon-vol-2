"""純Python pydanticシム(WASMビルド用)。

pydantic-core(Rust)はPyodideに無いため、terrariumが使う機能だけを再現する:
型付きフィールド+既定値、Field(default_factory=...)、ネストdict→モデル/enumの
強制変換(get_type_hints駆動)、model_dump()。スカラー検証は行わない —
specはネイティブ側で model_dump した JSON を渡す前提で、正当性は
ネイティブ実行が保証している。
"""
from __future__ import annotations

import enum as _enum
import json as _json
import typing as _t

_Hints = {}


class _FieldInfo:
    __slots__ = ("default", "default_factory")

    def __init__(self, default=None, default_factory=None):
        self.default = default
        self.default_factory = default_factory


def Field(default=None, *, default_factory=None, **_ignored):
    return _FieldInfo(default, default_factory)


def _collect_fields(cls):
    names: list[str] = []
    for k in reversed(cls.__mro__):
        for name in getattr(k, "__annotations__", {}):
            if name not in names and not name.startswith("_"):
                names.append(name)
    return names


def _hints(cls):
    if cls not in _Hints:
        try:
            _Hints[cls] = _t.get_type_hints(cls)
        except Exception:
            _Hints[cls] = {}
    return _Hints[cls]


def _is_union(tp):
    return _t.get_origin(tp) in (_t.Union,) or str(_t.get_origin(tp)).endswith("UnionType")


def _coerce(v, tp):
    """dict→BaseModel、str→Enum の強制変換(ネスト list/dict/Optional 対応)。
    型が付かない/スカラーはそのまま。"""
    if v is None or tp is None:
        return v
    origin = _t.get_origin(tp)
    if origin is list:
        args = _t.get_args(tp) or (None,)
        return [_coerce(x, args[0]) for x in v]
    if origin is dict:
        args = _t.get_args(tp)
        return {k: _coerce(x, args[1] if len(args) > 1 else None) for k, x in v.items()}
    if _is_union(tp):
        for a in _t.get_args(tp):
            if a is type(None):
                continue
            r = _coerce(v, a)
            if r is not v:
                return r
        return v
    if isinstance(tp, type) and issubclass(tp, _enum.Enum):
        return v if isinstance(v, tp) else tp(v)
    if isinstance(tp, type) and isinstance(v, dict) and hasattr(tp, "model_dump"):
        return tp(**v)
    return v


def _dump(v):
    if hasattr(v, "model_dump"):
        return v.model_dump()
    if isinstance(v, _enum.Enum):
        return v.value
    if isinstance(v, dict):
        return {k: _dump(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_dump(x) for x in v]
    return v


class BaseModel:
    def __init__(self, **data):
        cls = type(self)
        _missing = object()
        hints = _hints(cls)
        for name in _collect_fields(cls):
            if name in data:
                v = data.pop(name)
                setattr(self, name, _coerce(v, hints.get(name)))
                continue
            fi = getattr(cls, name, _missing)
            if fi is _missing:
                raise TypeError(f"{cls.__name__}: missing required field {name!r}")
            if isinstance(fi, _FieldInfo):
                v = fi.default_factory() if fi.default_factory is not None else fi.default
            else:
                v = fi   # プレーンなクラス既定値(None含む)
            setattr(self, name, _coerce(v, hints.get(name)))
        if data:
            raise TypeError(f"{cls.__name__}: unexpected fields {sorted(data)}")

    def model_dump(self):
        return {name: _dump(getattr(self, name)) for name in _collect_fields(type(self))}

    def model_dump_json(self):
        return _json.dumps(self.model_dump())

    def copy(self, **update):
        d = self.model_dump()
        d.update(update)
        return type(self)(**d)
