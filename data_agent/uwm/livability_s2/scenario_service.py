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
        rollout_graph, execution_scope = _bounded_rollout_graph(
            bundle["graph"], parcel_id=parcel_id
        )
        action_result["action"]["source_snapshot_digest"] = bundle["graph"][
            "snapshot_digest"
        ]
        action_result["action"]["snapshot_digest"] = rollout_graph["snapshot_digest"]
        rollout = run_counterfactual_rollout(
            graph=rollout_graph,
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
            "execution_scope": execution_scope,
            "rollout": rollout,
            "map_evidence": _map_evidence(bundle, parcel_id=parcel_id, rollout=rollout),
            "persistence_boundary": "process_memory_only",
            "approval_claim": False,
        }
        self._runs[run_id] = deepcopy(result)
        return result

    def get_run(self, run_id: str, *, actor_id: str) -> dict[str, Any]:
        if run_id not in self._runs or self._runs[run_id].get("actor_id") != actor_id:
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
        bundle_ids = {str(payload.get("bundle_id") or "") for payload in payloads.values()}
        if len(bundle_ids) != 1 or "" in bundle_ids:
            raise S2ProductInvalid("bundle_id_mismatch")
        expected_schemas = {
            "parcels": "uwm.livability_s2.parcels.v1",
            "planning_resources": "uwm.livability_s2.planning_resources.v1",
            "facilities": "uwm.livability_s2.facilities.v1",
            "graph_nodes": "uwm.livability_s2.graph_nodes.v1",
            "graph_edges": "uwm.livability_s2.graph_edges.v1",
            "land_use_dictionary": "uwm.land_use_dictionary.v1",
            "transition_matrix": "uwm.geospatial_kernel.land_use_transition_matrix.v1",
            "evidence_manifest": "uwm.livability_s2.evidence_manifest.v1",
            "build_report": "uwm.livability_s2.build_report.v1",
        }
        for key, schema in expected_schemas.items():
            if payloads[key].get("schema") != schema:
                raise S2ProductInvalid(f"schema_mismatch:{key}")
        if payloads["transition_matrix"].get("dictionary_version") != payloads[
            "land_use_dictionary"
        ].get("version"):
            raise S2ProductInvalid("transition_matrix_dictionary_version_mismatch")
        if (
            payloads["evidence_manifest"].get("claim_boundary") or {}
        ).get("max_claim_level") != "bounded_action_conditioned_spatial_scenario":
            raise S2ProductInvalid("claim_boundary_mismatch")
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


def _bounded_rollout_graph(
    graph: dict[str, Any], *, parcel_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    edges = graph.get("edges") or []
    nodes = {str(node.get("node_id")): node for node in graph.get("nodes") or []}
    direct_edges = [
        edge
        for edge in edges
        if parcel_id in {edge.get("source_node_id"), edge.get("target_node_id")}
    ]
    included_ids = {parcel_id}
    for edge in direct_edges:
        included_ids.add(str(edge.get("source_node_id")))
        included_ids.add(str(edge.get("target_node_id")))
    village_ids = {
        node_id
        for node_id in included_ids
        if (nodes.get(node_id) or {}).get("node_type") == "village_context"
    }
    cross_scale_edges = [
        edge
        for edge in edges
        if edge.get("source_node_id") in village_ids
        and edge.get("relation_type") in {"cross_scale_context", "village_within_admin"}
    ]
    for edge in cross_scale_edges:
        included_ids.add(str(edge.get("source_node_id")))
        included_ids.add(str(edge.get("target_node_id")))
    local_graph = build_state_graph(
        nodes=[deepcopy(nodes[node_id]) for node_id in sorted(included_ids)],
        edges=deepcopy(direct_edges + cross_scale_edges),
        kernel_version=str(graph.get("kernel_version") or ""),
    )
    return local_graph, {
        "scope": "target_parcel_bounded_local_subgraph",
        "source_snapshot_digest": graph.get("snapshot_digest"),
        "source_snapshot_node_count": len(graph.get("nodes") or []),
        "source_snapshot_edge_count": len(edges),
        "rollout_snapshot_digest": local_graph["snapshot_digest"],
        "rollout_node_count": len(local_graph["nodes"]),
        "rollout_edge_count": len(local_graph["edges"]),
        "direct_edge_count": len(direct_edges),
        "cross_scale_edge_count": len(cross_scale_edges),
    }


def _map_evidence(
    bundle: dict[str, Any], *, parcel_id: str, rollout: dict[str, Any]
) -> dict[str, Any]:
    affected_ids = {
        str(message.get("target_node_id"))
        for message in ((rollout.get("intervention") or {}).get("t2") or {}).get(
            "messages", []
        )
    }
    parcels = bundle["parcels"].get("features") or []
    resources = bundle["planning_resources"].get("features") or []
    facilities = bundle["facilities"].get("features") or []
    return {
        "target_parcel": _feature_collection(
            [feature for feature in parcels if str(feature.get("id")) == parcel_id]
        ),
        "affected_parcels": _feature_collection(
            [
                feature
                for feature in parcels
                if str(feature.get("id")) in affected_ids
                and str(feature.get("id")) != parcel_id
            ]
        ),
        "planning_resources": _feature_collection(
            [feature for feature in resources if str(feature.get("id")) in affected_ids]
        ),
        "facilities": _feature_collection(
            [feature for feature in facilities if str(feature.get("id")) in affected_ids]
        ),
        "proxy_distance_bands_m": [50, 150, 300],
        "distance_band_claim": "projected_distance_proxy_not_walkability_or_statutory_buffer",
    }


def _feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": deepcopy(features)}
