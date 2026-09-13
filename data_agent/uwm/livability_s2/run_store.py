"""Durable, digest-verified file store for S2 run audit records."""

from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RUN_ID_PATTERN = re.compile(r"^s2_run_[a-f0-9]{20}$")


class S2RunStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def save(self, payload: dict[str, Any]) -> None:
        run_id = str(payload.get("run_id") or "")
        path = self._path(run_id)
        self.root.mkdir(parents=True, exist_ok=True)
        record = {
            "schema": "uwm.livability_s2.run_record.v1",
            "run_id": run_id,
            "actor_id": payload.get("actor_id"),
            "stored_at": datetime.now(timezone.utc).isoformat(),
            "payload_digest": _digest(payload),
            "payload": deepcopy(payload),
        }
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(record, ensure_ascii=False, allow_nan=False, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def get(self, run_id: str, *, actor_id: str) -> dict[str, Any] | None:
        path = self._path(run_id)
        if not path.is_file():
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("schema") != "uwm.livability_s2.run_record.v1":
            raise RuntimeError("run_record_schema_invalid")
        payload = record.get("payload")
        if not isinstance(payload, dict) or record.get("payload_digest") != _digest(payload):
            raise RuntimeError("run_record_digest_mismatch")
        if str(record.get("actor_id") or "") != actor_id:
            return None
        return deepcopy(payload)

    def _path(self, run_id: str) -> Path:
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError("run_id_invalid")
        return self.root / f"{run_id}.json"


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
