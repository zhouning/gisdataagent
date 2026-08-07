"""Snapshot-backed S2 scenario service for online parcel rollouts."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from shapely.geometry import mapping, shape

from data_agent.uwm.geospatial_kernel.counterfactual_rollout import (
    run_counterfactual_rollout,
)
from data_agent.uwm.geospatial_kernel.direct_transition import apply_direct_transition
from data_agent.uwm.geospatial_kernel.facility_action import (
    bind_server_facility_actor,
    build_facility_action,
    validate_facility_action,
)
from data_agent.uwm.geospatial_kernel.land_use_action import (
    bind_server_actor,
    build_change_land_use_action,
    validate_land_use_action,
)
from data_agent.uwm.geospatial_kernel.state_graph import build_state_graph

from .business_assessment import assess_s2_business_impact
from .dependency_dag import (
    build_dependency_dag,
    mutation_detection_report,
    plan_recomputation_scope,
)
from .execution_integrity import build_execution_dependency_receipt
from .product import PRODUCT_FILENAMES
from .run_store import S2RunStore
from .technical_audit import build_s2_technical_audit


PLANNING_PROJECTS_FILENAME = "uwm_livability_s2_planning_projects.json"


class S2ProductInvalid(RuntimeError):
    """Raised when a snapshot is missing, malformed or digest-tampered."""


class S2RunNotFound(KeyError):
    """Raised when a process-memory run is unavailable."""


class S2RunInvalid(RuntimeError):
    """Raised when a durable audit record fails integrity validation."""


class S2ScenarioService:
    """Load validated offline products and execute bounded online rollouts."""

    def __init__(self, product_dir: Path, run_store_dir: Path | None = None):
        self.product_dir = Path(product_dir)
        self._bundle: dict[str, Any] | None = None
        self._runs: dict[str, dict[str, Any]] = {}
        self._run_store = S2RunStore(run_store_dir) if run_store_dir else None

    def catalog(self) -> dict[str, Any]:
        bundle = self._load_bundle()
        dependency_dag = build_dependency_dag()
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
            "observed_facility_classes": sorted(
                {
                    str((feature.get("properties") or {}).get("canonical_class"))
                    for feature in bundle["facilities"].get("features") or []
                    if (feature.get("properties") or {}).get("canonical_class")
                    and (feature.get("properties") or {}).get("canonical_class")
                    != "unmapped"
                }
            ),
            "supported_business_actions": [
                "change_land_use",
                "add_facility",
                "remove_facility",
            ],
            "planning_project_count": len(
                (bundle.get("planning_projects") or {}).get("projects") or []
            ),
            "planning_project_evidence_version": (
                bundle.get("planning_projects") or {}
            ).get("version"),
            "synthetic_parcels_created": False,
            "online_raw_vector_access": False,
            "run_persistence": (
                "durable_digest_verified_file_store"
                if self._run_store
                else "process_memory_only"
            ),
            "module_dependency_dag": {
                "available": bool(dependency_dag["ready"]),
                "version": dependency_dag["version"],
                "module_count": len(dependency_dag["modules"]),
                "edge_count": len(dependency_dag["edges"]),
            },
            "claim_boundary": deepcopy(bundle["manifest"].get("claim_boundary") or {}),
        }

    def list_parcels(self) -> dict[str, Any]:
        return deepcopy(self._load_bundle()["parcels"])

    def list_facilities(self) -> dict[str, Any]:
        return deepcopy(self._load_bundle()["facilities"])

    def list_planning_projects(self) -> dict[str, Any]:
        payload = self._load_bundle().get("planning_projects")
        if not payload:
            return {
                "schema": "uwm.livability_s2.planning_project_evidence.v1",
                "version": None,
                "project_count": 0,
                "projects": [],
                "claim_boundary": "planning_project_evidence_unavailable",
            }
        return deepcopy(payload)

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
        action_type: str = "change_land_use",
        facility_class: str | None = None,
        facility_id: str | None = None,
        service_radius_m: float | None = None,
        radius_evidence_source: str | None = None,
        critical_facility: bool = False,
        planning_project_id: str | None = None,
    ) -> dict[str, Any]:
        bundle = self._load_bundle()
        if action_type in {"add_facility", "remove_facility"}:
            target_feature = self._parcel_feature(bundle, parcel_id)
            target_properties = target_feature.get("properties") or {}
            planning_area_id = str(target_properties.get("planning_area_id") or "")
            placement_source = target_feature
            if action_type == "remove_facility" and facility_id:
                placement_source = self._facility_feature(bundle, facility_id) or target_feature
            placement_point = shape(placement_source["geometry"]).representative_point()
            action = bind_server_facility_actor(
                build_facility_action(
                    action_type=action_type,
                    parcel_id=parcel_id,
                    planning_area_id=planning_area_id,
                    facility_class=str(facility_class or ""),
                    facility_id=facility_id,
                    service_radius_m=float(service_radius_m or 0.0),
                    radius_evidence_source=str(radius_evidence_source or ""),
                    placement_geometry_wgs84=mapping(placement_point),
                    distance_crs=str(target_properties.get("distance_crs") or ""),
                    rationale=rationale,
                    snapshot_digest=snapshot_digest,
                    requested_at=requested_at,
                ),
                actor_id=actor_id,
                authorized_planning_area_ids=[planning_area_id],
            )
            validation = validate_facility_action(action, graph=bundle["graph"])
        else:
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
        intervention_graph = None
        if validation.get("valid") and action_type in {"add_facility", "remove_facility"}:
            intervention_graph = apply_direct_transition(
                graph=bundle["graph"],
                action=action,
                action_validation=validation,
            )["state_graph"]
        business_assessment = assess_s2_business_impact(
            parcels=bundle["parcels"],
            facilities=bundle["facilities"],
            parcel_id=parcel_id,
            action_type=action_type,
            facility_class=facility_class,
            facility_id=facility_id,
            service_radius_m=service_radius_m,
            radius_evidence_source=radius_evidence_source,
            critical_facility=critical_facility,
            facility_inventory_complete=bool(
                bundle["manifest"].get("facility_inventory_complete")
            ),
            transition_status=str((validation.get("transition") or {}).get("status") or "unresolved"),
            baseline_graph=bundle["graph"],
            intervention_graph=intervention_graph,
        )
        project_evidence = _planning_project_evidence(
            bundle,
            planning_project_id=planning_project_id,
            parcel_id=parcel_id,
            facility_class=facility_class,
        )
        if project_evidence:
            business_assessment["planning_project_evidence"] = project_evidence
            business_assessment["action"]["planning_project_id"] = planning_project_id
        return {
            "schema": "uwm.livability_s2.action_validation.v1",
            "action": action,
            "validation": validation,
            "business_assessment_preview": business_assessment,
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
        action_type: str = "change_land_use",
        facility_class: str | None = None,
        facility_id: str | None = None,
        service_radius_m: float | None = None,
        radius_evidence_source: str | None = None,
        critical_facility: bool = False,
        planning_project_id: str | None = None,
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
            action_type=action_type,
            facility_class=facility_class,
            facility_id=facility_id,
            service_radius_m=service_radius_m,
            radius_evidence_source=radius_evidence_source,
            critical_facility=critical_facility,
            planning_project_id=planning_project_id,
        )
        validation = action_result["validation"]
        if not validation["valid"]:
            raise ValueError("action_invalid:" + validation["errors"][0])
        rollout_graph, execution_scope = _bounded_rollout_graph(
            bundle["graph"],
            parcel_id=parcel_id,
            facility_id=(
                str(action_result["action"].get("facility_id") or "")
                if action_type == "remove_facility"
                else None
            ),
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
        business_assessment = action_result["business_assessment_preview"]
        run_id = _run_id(
            actor_id=actor_id,
            requested_at=requested_at,
            parcel_id=parcel_id,
            rollout_digest=str(rollout.get("rollout_digest")),
        )
        map_evidence = _map_evidence(
            bundle,
            parcel_id=parcel_id,
            rollout=rollout,
            business_assessment=business_assessment,
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
            "business_assessment": business_assessment,
            "map_evidence": map_evidence,
            "persistence_boundary": (
                "durable_digest_verified_file_store"
                if self._run_store
                else "process_memory_only"
            ),
            "approval_claim": False,
        }
        result["technical_audit"] = build_s2_technical_audit(
            bundle=bundle,
            rollout=rollout,
            business_assessment=business_assessment,
            map_evidence=map_evidence,
            execution_scope=execution_scope,
        )
        result["dependency_scope"] = plan_recomputation_scope(
            str(action_result["action"].get("action_type") or "")
        )
        result["dependency_mutation_detection"] = mutation_detection_report()
        result["execution_dependency_receipt"] = (
            build_execution_dependency_receipt(result)
        )
        self._runs[run_id] = deepcopy(result)
        if self._run_store:
            self._run_store.save(result)
        return result

    def get_run(self, run_id: str, *, actor_id: str) -> dict[str, Any]:
        if run_id in self._runs and self._runs[run_id].get("actor_id") == actor_id:
            return deepcopy(self._runs[run_id])
        if self._run_store:
            try:
                stored = self._run_store.get(run_id, actor_id=actor_id)
            except (RuntimeError, ValueError, json.JSONDecodeError) as error:
                raise S2RunInvalid(str(error)) from error
            if stored is not None:
                self._runs[run_id] = deepcopy(stored)
                return stored
        raise S2RunNotFound("run_not_found")

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
            "planning_projects": _load_planning_projects(self.product_dir),
        }
        return self._bundle

    @staticmethod
    def _parcel_node(graph: dict[str, Any], parcel_id: str) -> dict[str, Any]:
        for node in graph.get("nodes") or []:
            if node.get("node_id") == parcel_id and node.get("node_type") == "parcel":
                return node
        raise ValueError("parcel_not_found")

    @staticmethod
    def _parcel_feature(bundle: dict[str, Any], parcel_id: str) -> dict[str, Any]:
        for feature in bundle["parcels"].get("features") or []:
            if str(feature.get("id")) == parcel_id:
                return feature
        raise ValueError("parcel_not_found")

    @staticmethod
    def _facility_feature(
        bundle: dict[str, Any], facility_id: str
    ) -> dict[str, Any] | None:
        for feature in bundle["facilities"].get("features") or []:
            if str(feature.get("id")) == str(facility_id):
                return feature
        return None


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


def _load_planning_projects(product_dir: Path) -> dict[str, Any] | None:
    path = product_dir / PLANNING_PROJECTS_FILENAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise S2ProductInvalid("planning_project_evidence_invalid_json") from error
    if payload.get("schema") != "uwm.livability_s2.planning_project_evidence.v1":
        raise S2ProductInvalid("planning_project_evidence_schema_mismatch")
    if payload.get("content_digest") != _content_digest(payload):
        raise S2ProductInvalid("planning_project_evidence_digest_mismatch")
    return payload


def _planning_project_evidence(
    bundle: dict[str, Any],
    *,
    planning_project_id: str | None,
    parcel_id: str,
    facility_class: str | None,
) -> dict[str, Any] | None:
    if not planning_project_id:
        return None
    payload = bundle.get("planning_projects") or {}
    project = next(
        (
            row
            for row in payload.get("projects") or []
            if str(row.get("project_id")) == planning_project_id
        ),
        None,
    )
    if project is None:
        raise ValueError("planning_project_not_found")
    parcel = next(
        (
            feature
            for feature in bundle["parcels"].get("features") or []
            if str(feature.get("id")) == parcel_id
        ),
        None,
    )
    planning_area_id = str((parcel.get("properties") or {}).get("planning_area_id") or "")
    if str(project.get("planning_area_id") or "") != planning_area_id:
        raise ValueError("planning_project_area_mismatch")
    mapped_class = project.get("canonical_facility_class")
    if mapped_class and facility_class and mapped_class != facility_class:
        raise ValueError("planning_project_facility_class_mismatch")
    return deepcopy(project)


def _run_id(*, actor_id: str, requested_at: str, parcel_id: str, rollout_digest: str) -> str:
    encoded = "\x1f".join(
        [str(actor_id), str(requested_at), str(parcel_id), str(rollout_digest)]
    ).encode("utf-8")
    return "s2_run_" + hashlib.sha256(encoded).hexdigest()[:20]


def _bounded_rollout_graph(
    graph: dict[str, Any], *, parcel_id: str, facility_id: str | None = None
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
    facility_edges = []
    if facility_id:
        included_ids.add(str(facility_id))
        facility_edges = [
            edge
            for edge in edges
            if facility_id
            in {str(edge.get("source_node_id")), str(edge.get("target_node_id"))}
        ]
        for edge in facility_edges:
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
        edges=deepcopy(
            list({
                str(edge.get("edge_id")): edge
                for edge in direct_edges + facility_edges + cross_scale_edges
            }.values())
        ),
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
        "facility_edge_count": len(facility_edges),
        "cross_scale_edge_count": len(cross_scale_edges),
    }


def _map_evidence(
    bundle: dict[str, Any],
    *,
    parcel_id: str,
    rollout: dict[str, Any],
    business_assessment: dict[str, Any],
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
    baseline = business_assessment.get("baseline") or {}
    intervention = business_assessment.get("intervention") or {}
    newly_covered_ids = set(business_assessment.get("newly_covered_parcel_ids") or [])
    newly_uncovered_ids = set(business_assessment.get("newly_uncovered_parcel_ids") or [])
    result = {
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
        "baseline_service_areas": deepcopy(
            baseline.get("service_areas") or _feature_collection([])
        ),
        "intervention_service_areas": deepcopy(
            intervention.get("service_areas") or _feature_collection([])
        ),
        "newly_covered_parcels": _feature_collection(
            [feature for feature in parcels if str(feature.get("id")) in newly_covered_ids]
        ),
        "newly_uncovered_parcels": _feature_collection(
            [feature for feature in parcels if str(feature.get("id")) in newly_uncovered_ids]
        ),
        "direct_state_delta": deepcopy(rollout.get("direct_state_delta") or {}),
        "business_recommendation": {
            "recommendation": business_assessment.get("recommendation"),
            "triggered_rules": deepcopy(
                business_assessment.get("triggered_rules") or []
            ),
            "evidence_level": business_assessment.get("evidence_level"),
            "assessment_digest": business_assessment.get("assessment_digest"),
        },
        "proxy_distance_bands_m": [50, 150, 300],
        "distance_band_claim": "projected_distance_proxy_not_walkability_or_statutory_buffer",
    }
    result["evidence_digest"] = _content_digest(result)
    return result


def _feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": deepcopy(features)}
