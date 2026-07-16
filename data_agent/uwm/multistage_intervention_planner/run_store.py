"""File-backed audit store for multi-stage intervention planning runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class MultiStageRunStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def save(self, run: dict[str, Any]) -> Path:
        run_id = str(run.get("run_id") or "").strip()
        if not run_id:
            raise ValueError("run_id is required")
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{run_id}.json"
        path.write_text(
            json.dumps(run, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    def load(self, run_id: str) -> dict[str, Any]:
        safe_run_id = "".join(
            character for character in str(run_id) if character.isalnum() or character in {"-", "_"}
        )
        if not safe_run_id or safe_run_id != run_id:
            raise ValueError("invalid run_id")
        path = self.root / f"{safe_run_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"run not found: {safe_run_id}")
        return json.loads(path.read_text(encoding="utf-8"))
