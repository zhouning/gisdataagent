from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping


class EnvironmentalKernelConflict(RuntimeError):
    def __init__(self, code: str, *, actor: str):
        super().__init__(code)
        self.code = code
        self.actor = actor


class EnvironmentalKernelService:
    def __init__(self, product_dir: Path):
        root = Path(product_dir)
        self._scene = _read(root / "scene.json")
        self._gate = _read(root / "evidence_gate.json")
        self._rollout = _read(root / "current_rollout.json")
        self._map = _read(root / "map.json")
        bundle_ids = {payload.get("bundle_id") for payload in (self._scene, self._gate, self._rollout, self._map)}
        if len(bundle_ids) != 1 or None in bundle_ids:
            raise ValueError("environmental_kernel_bundle_mismatch")

    def scene(self) -> dict[str, Any]:
        return deepcopy(self._scene)

    def evidence_gate(self) -> dict[str, Any]:
        return deepcopy(self._gate)

    def current_rollout(self) -> dict[str, Any]:
        return deepcopy(self._rollout)

    def map_payload(self) -> dict[str, Any]:
        return deepcopy(self._map)

    def run(self, *, request: Mapping[str, Any], actor: str) -> dict[str, Any]:
        state = self._scene.get("state") or {}
        if request.get("state_snapshot_digest") != state.get("snapshot_digest"):
            raise EnvironmentalKernelConflict("environmental_state_snapshot_conflict", actor=actor)
        if self._rollout.get("intervention_status") == "action_response_closed":
            raise EnvironmentalKernelConflict("environmental_action_response_closed", actor=actor)
        result = deepcopy(self._rollout)
        result["actor"] = actor
        result["client_actor_accepted"] = False
        return result


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("environmental_kernel_product_must_be_object")
    return payload
