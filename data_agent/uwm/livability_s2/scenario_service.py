"""Snapshot-backed S2 scenario service for online parcel rollouts."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel.counterfactual_rollout import (
    run_counterfactual_rollout,
)
from data_agent.uwm.geospatial_kernel.land_use_action import (
    bind_server_actor,
    build_change_land_use_action,
    validate_land_use_action,
)
from data_agent.uwm.geospatial_kernel.state_graph import build_state_graph

from .product import PRODUCT_FILENAMES


class S2ProductInvalid(RuntimeError):
    """Raised when a snapshot is missing, malformed or digest-tampered."""


class S2RunNotFound(KeyError):
    """Raised when a process-memory run is unavailable."""


class S2ScenarioService:
    """Load validated offline products and execute bounded online rollouts."""

    def __init__(self, product_dir: Path):
        self.product_dir = Path(product_dir)
        self._bundle: dict[str, Any] | None = None
        self._runs: dict[str, dict[str, Any]] = {}

    def catalog(self) -> dict[str, Any]:
        bundle = self._load_bundle()
        return {
            "schema": "uwm.livability_s2.catalog.v1",
            "ready": True,
            "scope": bundle["manifest"].get("scope"),
            "parcel_count": len(bundle["parcels"].get("features") or []),
            "planning_resource_count": len(
                bundle["planning_resources"].get("features") or []
            ),
            "facility_count": len(bundle["facilities"].get("features") or []),
            "kernel_version": bundle["graph"].get("kernel_version"),
            "snapshot_digest": bundle["graph"].get("snapshot_digest"),
            "land_use_classes": list(bundle["dictionary"].get("classes") or []),
            "dictionary_version": bundle["dictionary"].get("version"),
            "transition_matrix_version": bundle["matrix"].get("version"),
            "facility_inventory_complete": bool(
                bundle["manifest"].get("facility_inventory_complete")
            ),
            "synthetic_parcels_created": False,
            "online_raw_vector_access": False,
            "claim_boundary": deepcopy(bundle["manifest"].get("claim_boundary") or {}),
        }

    def list_parcels(self) -> dict[str, Any]:
        return deepcopy(self._load_bundle()["parcels"])

    def parcel_detail(self, parcel_id: str) -> dict[str, Any]:
        bundle = self._load_bundle()
        parcel = next(
            (
                feature
                for feature in bundle["parcels"].get("features") or []
                if str(feature.get("id")) == str(parcel_id)
            ),
            None,
        )
        if parcel is None:
            raise ValueError("parcel_not_found")
        direct_edges = [
            edge
            for edge in bundle["graph"].get("edges") or []
            if parcel_id in {edge.get("source_node_id"), edge.get("target_node_id")}
        ]
        return {
            "schema": "uwm.livability_s2.parcel_detail.v1",
            "parcel": deepcopy(parcel),
            "graph_context": {
                "direct_edge_count": len(direct_edges),
                "direct_edges": deepcopy(direct_edges),
            },
            "snapshot_digest": bundle["graph"]["snapshot_digest"],
            "claim_boundary": deepcopy(bundle["manifest"].get("claim_boundary") or {}),
        }

    def validate_action(
        self,
        *,
        parcel_id: str,
        from_land_use_class: str,
        to_land_use_class: str,
        snapshot_digest: str,
        rationale: str,
        requested_at: str,
        actor_id: str,
    ) -> dict[str, Any]:
        bundle = self._load_bundle()
        action = bind_server_actor(
            build_change_land_use_action(
                parcel_id=parcel_id,
                from_land_use_class=from_land_use_class,
                to_land_use_class=to_land_use_class,
                rationale=rationale,
                snapshot_digest=snapshot_digest,
                dictionary_version=str(bundle["dictionary"].get("version")),
                transition_matrix_version=str(bundle["matrix"].get("version")),
                requested_at=requested_at,
            ),
            actor_id=actor_id,
        )
        parcel = self._parcel_node(bundle["graph"], parcel_id)
        validation = validate_land_use_action(
            action,
            parcel=parcel,
            actual_snapshot_digest=str(bundle["graph"].get("snapshot_digest")),
            land_use_dictionary=bundle["dictionary"],
            transition_matrix=bundle["matrix"],
        )
        return {
            "schema": "uwm.livability_s2.action_validation.v1",
            "action": action,
            "validation": validation,
            "approval_claim": False,
        }

    def rollout(
        self,
        *,
        parcel_id: str,
        from_land_use_class: str,
        to_land_use_class: str,
        snapshot_digest: str,
        rationale: str,
        requested_at: str,
        actor_id: str,
        alternative_land_use_class: str | None,
    ) -> dict[str, Any]:
        bundle = self._load_bundle()
        action_result = self.validate_action(
            parcel_id=parcel_id,
            from_land_use_class=from_land_use_class,
            to_land_use_class=to_land_use_class,
            snapshot_digest=snapshot_digest,
            rationale=rationale,
            requested_at=requested_at,
            actor_id=actor_id,
        )
        validation = action_result["validation"]
        if not validation["valid"]:
            raise ValueError("action_invalid:" + validation["errors"][0])
        rollout = run_counterfactual_rollout(
            graph=bundle["graph"],
            intervention_action=action_result["action"],
            land_use_dictionary=bundle["dictionary"],
            transition_matrix=bundle["matrix"],
            alternative_land_use_class=alternative_land_use_class,
        )
        run_id = _run_id(
            actor_id=actor_id,
            requested_at=requested_at,
            parcel_id=parcel_id,
            rollout_digest=str(rollout.get("rollout_digest")),
        )
        result = {
            "schema": "uwm.livability_s2.run.v1",
            "run_id": run_id,
            "actor_id": actor_id,
            "requested_at": requested_at,
            "parcel_id": parcel_id,
            "snapshot_digest": bundle["graph"]["snapshot_digest"],
            "rollout": rollout,
            "persistence_boundary": "process_memory_only",
            "approval_claim": False,
        }
        self._runs[run_id] = deepcopy(result)
        return result

    def get_run(self, run_id: str) -> dict[str, Any]:
        if run_id not in self._runs:
            raise S2RunNotFound("run_not_found")
        return deepcopy(self._runs[run_id])

    def _load_bundle(self) -> dict[str, Any]:
        if self._bundle is not None:
            return self._bundle
        payloads: dict[str, dict[str, Any]] = {}
        for key, filename in PRODUCT_FILENAMES.items():
            path = self.product_dir / filename
            if not path.is_file():
                raise S2ProductInvalid(f"snapshot_missing:{filename}")
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise S2ProductInvalid(f"snapshot_invalid_json:{filename}") from error
            if not isinstance(payload, dict):
                raise S2ProductInvalid(f"snapshot_not_object:{filename}")
            if payload.get("content_digest") != _content_digest(payload):
                raise S2ProductInvalid(f"content_digest_mismatch:{filename}")
            payloads[key] = payload
        nodes_payload = payloads["graph_nodes"]
        edges_payload = payloads["graph_edges"]
        if nodes_payload.get("state_graph_snapshot_digest") != edges_payload.get(
            "state_graph_snapshot_digest"
        ):
            raise S2ProductInvalid("state_graph_snapshot_digest_disagreement")
        graph = build_state_graph(
            nodes=nodes_payload.get("nodes") or [],
            edges=edges_payload.get("edges") or [],
            kernel_version=str(nodes_payload.get("kernel_version") or ""),
        )
        if graph["snapshot_digest"] != nodes_payload.get("state_graph_snapshot_digest"):
            raise S2ProductInvalid("state_graph_snapshot_digest_mismatch")
        self._bundle = {
            "parcels": payloads["parcels"],
            "planning_resources": payloads["planning_resources"],
            "facilities": payloads["facilities"],
            "dictionary": payloads["land_use_dictionary"],
            "matrix": payloads["transition_matrix"],
            "manifest": payloads["evidence_manifest"],
            "report": payloads["build_report"],
            "graph": graph,
        }
        return self._bundle

    @staticmethod
    def _parcel_node(graph: dict[str, Any], parcel_id: str) -> dict[str, Any]:
        for node in graph.get("nodes") or []:
            if node.get("node_id") == parcel_id and node.get("node_type") == "parcel":
                return node
        raise ValueError("parcel_not_found")


def _content_digest(payload: dict[str, Any]) -> str:
    content = {key: value for key, value in payload.items() if key != "content_digest"}
    encoded = json.dumps(
        content,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _run_id(*, actor_id: str, requested_at: str, parcel_id: str, rollout_digest: str) -> str:
    encoded = "\x1f".join(
        [str(actor_id), str(requested_at), str(parcel_id), str(rollout_digest)]
    ).encode("utf-8")
    return "s2_run_" + hashlib.sha256(encoded).hexdigest()[:20]
