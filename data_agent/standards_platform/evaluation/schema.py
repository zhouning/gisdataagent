"""Schema primitives for Standards Platform derivation evaluation."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _require_text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


@dataclass(frozen=True)
class DerivationEvalItem:
    """One gold or predicted derivation artifact.

    The `match` dictionary is part of identity. `payload` is evidence for
    reporting and review, but does not affect scoring identity.
    """

    strategy: str
    source_key: str
    target_kind: str
    target_key: str
    match: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for key in ("strategy", "source_key", "target_kind", "target_key"):
            value = getattr(self, key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{key} is required")
        if not isinstance(self.match, dict):
            raise ValueError("match must be an object")
        if not isinstance(self.payload, dict):
            raise ValueError("payload must be an object")

    @property
    def identity(self) -> tuple[str, str, str, str, str]:
        return (
            self.strategy,
            self.source_key,
            self.target_kind,
            self.target_key,
            _canonical_json(self.match),
        )

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "DerivationEvalItem":
        return cls(
            strategy=_require_text(data, "strategy"),
            source_key=_require_text(data, "source_key"),
            target_kind=_require_text(data, "target_kind"),
            target_key=_require_text(data, "target_key"),
            match=dict(data.get("match") or {}),
            payload=dict(data.get("payload") or {}),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "source_key": self.source_key,
            "target_kind": self.target_kind,
            "target_key": self.target_key,
            "match": dict(self.match),
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class DerivationEvalSet:
    """A named set of derivation eval items."""

    items: tuple[DerivationEvalItem, ...]
    dataset_id: str = "unnamed"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        seen: set[tuple[str, str, str, str, str]] = set()
        for item in self.items:
            if item.identity in seen:
                raise ValueError(f"duplicate eval item identity: {item.identity}")
            seen.add(item.identity)
        if not isinstance(self.metadata, dict):
            raise ValueError("metadata must be an object")

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "DerivationEvalSet":
        raw_items = data.get("items")
        if not isinstance(raw_items, list):
            raise ValueError("items must be a list")
        items = tuple(DerivationEvalItem.from_mapping(item) for item in raw_items)
        dataset_id = data.get("dataset_id") or "unnamed"
        if not isinstance(dataset_id, str):
            raise ValueError("dataset_id must be a string")
        metadata = dict(data.get("metadata") or {})
        return cls(items=items, dataset_id=dataset_id, metadata=metadata)

    @classmethod
    def from_json_file(cls, path: str | Path) -> "DerivationEvalSet":
        raw = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("eval set JSON root must be an object")
        return cls.from_mapping(data)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "metadata": dict(self.metadata),
            "items": [item.to_mapping() for item in self.items],
        }
