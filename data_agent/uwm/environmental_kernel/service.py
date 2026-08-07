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
        replay_path = root / "temporal_replay.json"
        self._temporal_replay = _read(replay_path) if replay_path.exists() else None
        payloads = (self._scene, self._gate, self._rollout, self._map)
        if self._temporal_replay:
            payloads = (*payloads, self._temporal_replay)
        bundle_ids = {payload.get("bundle_id") for payload in payloads}
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

    def list_nodes(self, search: str = "") -> dict[str, Any]:
        query = search.strip().lower()
        replay_nodes = {row.get("node_id"): row for row in ((self._temporal_replay or {}).get("node_series") or [])}
        rows = []
        for node in (self._scene.get("state") or {}).get("spatial_nodes") or []:
            node_id = str(node.get("node_id") or "")
            if query and query not in node_id.lower() and query not in str(node.get("county") or "").lower() and query not in str(node.get("township") or "").lower():
                continue
            replay = replay_nodes.get(node_id) or {}
            rows.append({
                "node_id": node_id,
                "county": node.get("county"),
                "township": node.get("township"),
                "pm25_ugm3": node.get("pm25_ugm3"),
                "temperature_c": node.get("temperature_c"),
                "temporal_replay_available": bool(replay),
                "replay_record_count": replay.get("record_count", 0),
            })
        return {"schema": "uwm.environmental_nodes.v1", "nodes": rows, "total": len(rows)}

    def temporal_replay(self, node_id: str) -> dict[str, Any]:
        if not self._temporal_replay:
            raise ValueError("temporal_proxy_replay_unavailable")
        row = next((item for item in self._temporal_replay.get("node_series") or [] if item.get("node_id") == node_id), None)
        if not row:
            raise ValueError("environmental_node_not_found")
        return {
            "schema": "uwm.environmental_temporal_state_replay_response.v1",
            "bundle_id": self._scene["bundle_id"],
            "node": deepcopy(row),
            "source_quality": deepcopy(self._temporal_replay.get("source_quality") or {}),
            "claim_boundary": "历史代理状态回放，不是未来日历预测，也不是干预政策效果。",
        }

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
