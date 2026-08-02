"""Evidence-gated spatial topology contracts shared by GWM adapters."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import torch

from .contracts import DAMGKBatch


GWM_SPATIAL_TOPOLOGY_SCHEMA = "gwm.geospatial_kernel.spatial_topology.v1"
GWM_SPATIAL_TOPOLOGY_ADMISSION_SCHEMA = (
    "gwm.geospatial_kernel.spatial_topology_admission.v1"
)
GWM_NETWORK_LINEAR_REFERENCE_SCHEMA = (
    "gwm.geospatial_kernel.network_linear_reference.v1"
)
GWM_ACTION_NODE_CROSSWALK_SCHEMA = (
    "gwm.geospatial_kernel.action_node_crosswalk.v1"
)
GWM_TEMPORAL_SERIES_CROSSWALK_SCHEMA = (
    "gwm.geospatial_kernel.temporal_series_crosswalk.v1"
)
GWM_COMPOSITE_ACTION_CROSSWALK_SCHEMA = (
    "gwm.geospatial_kernel.composite_action_crosswalk.v1"
)
GWM_AUTHORITATIVE_TOPOLOGY_EVIDENCE_SCHEMA = (
    "gwm.geospatial_kernel.authoritative_topology_evidence.v1"
)
GWM_SPATIAL_TOPOLOGY_NODE_COLUMNS = (
    "node_key",
    "node_role",
    "admission_status",
    "source_id",
    "source_artifact_sha256",
)
GWM_SPATIAL_TOPOLOGY_EDGE_COLUMNS = (
    "source_node_key",
    "target_node_key",
    "relation_type",
    "feature_name",
    "value",
    "admission_status",
    "source_id",
    "source_artifact_sha256",
)
GWM_SPATIAL_TOPOLOGY_ADMISSION_GATES = (
    "source_identity_and_hashes",
    "node_role_semantics",
    "directed_relation_semantics",
    "authoritative_connectivity",
    "metric_feature_semantics",
    "temporal_validity",
    "license_and_access",
)
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "contract_sha256"}
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


@dataclass(frozen=True)
class GWMSpatialTopologyContract:
    """Frozen node, relation, geometry and reachability semantics."""

    contract_id: str
    node_keys: tuple[str, ...]
    node_roles: tuple[str, ...]
    relation_types: tuple[str, ...]
    edge_feature_names: tuple[str, ...]
    allowed_role_pairs: tuple[tuple[str, str, str], ...]
    required_paths: tuple[tuple[str, str], ...]
    source_artifacts: tuple[tuple[str, str, str], ...] = ()
    required_effective_interval: tuple[str, str] | None = None
    admission_evidence_artifact: tuple[str, str, str] | None = None

    def __post_init__(self) -> None:
        if not self.contract_id.strip():
            raise ValueError("spatial_topology_contract_id_required")
        _require_unique_nonempty(self.node_keys, "node_keys")
        if len(self.node_roles) != len(self.node_keys) or any(
            not value.strip() for value in self.node_roles
        ):
            raise ValueError("spatial_topology_node_roles_invalid")
        _require_unique_nonempty(self.relation_types, "relation_types")
        _require_unique_nonempty(self.edge_feature_names, "edge_feature_names")
        if not self.allowed_role_pairs or len(set(self.allowed_role_pairs)) != len(
            self.allowed_role_pairs
        ):
            raise ValueError("spatial_topology_allowed_role_pairs_invalid")
        known_roles = set(self.node_roles)
        known_relations = set(self.relation_types)
        for relation, source_role, target_role in self.allowed_role_pairs:
            if (
                relation not in known_relations
                or source_role not in known_roles
                or target_role not in known_roles
            ):
                raise ValueError("spatial_topology_allowed_role_pair_unknown")
        declared_relations = {row[0] for row in self.allowed_role_pairs}
        if declared_relations != known_relations:
            raise ValueError("spatial_topology_relation_role_policy_incomplete")
        known_nodes = set(self.node_keys)
        if len(set(self.required_paths)) != len(self.required_paths):
            raise ValueError("spatial_topology_required_paths_must_be_unique")
        for source, target in self.required_paths:
            if source not in known_nodes or target not in known_nodes or source == target:
                raise ValueError("spatial_topology_required_path_invalid")
        for name, path, digest in self.source_artifacts:
            if not name or not path or not _SHA256.fullmatch(digest):
                raise ValueError("spatial_topology_source_artifact_invalid")
        if self.required_effective_interval is not None:
            start, end = self.required_effective_interval
            if _utc_timestamp(start, "contract_effective_start") >= _utc_timestamp(
                end, "contract_effective_end"
            ):
                raise ValueError("spatial_topology_effective_interval_invalid")
        if self.admission_evidence_artifact is not None:
            name, path, digest = self.admission_evidence_artifact
            if not name or not path or not _SHA256.fullmatch(digest):
                raise ValueError(
                    "spatial_topology_admission_evidence_artifact_invalid"
                )

    @property
    def node_role_by_key(self) -> dict[str, str]:
        return dict(zip(self.node_keys, self.node_roles, strict=True))

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "schema": GWM_SPATIAL_TOPOLOGY_SCHEMA,
            "contract_id": self.contract_id,
            "node_keys": list(self.node_keys),
            "node_roles": list(self.node_roles),
            "relation_types": list(self.relation_types),
            "edge_feature_names": list(self.edge_feature_names),
            "allowed_role_pairs": [
                {
                    "relation_type": relation,
                    "source_role": source_role,
                    "target_role": target_role,
                }
                for relation, source_role, target_role in self.allowed_role_pairs
            ],
            "required_paths": [
                {"source_node_key": source, "target_node_key": target}
                for source, target in self.required_paths
            ],
            "admission_policy": "non_compensatory_certificate_and_admitted_rows",
            "source_artifacts": [
                {"name": name, "path": path, "sha256": digest}
                for name, path, digest in self.source_artifacts
            ],
        }
        if self.required_effective_interval is not None:
            payload["required_effective_interval"] = {
                "start_inclusive": self.required_effective_interval[0],
                "end_inclusive": self.required_effective_interval[1],
            }
        if self.admission_evidence_artifact is not None:
            name, path, digest = self.admission_evidence_artifact
            payload["admission_evidence_artifact"] = {
                "name": name,
                "path": path,
                "sha256": digest,
            }
        payload["contract_sha256"] = _canonical_sha256(payload)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> GWMSpatialTopologyContract:
        if payload.get("schema") != GWM_SPATIAL_TOPOLOGY_SCHEMA:
            raise ValueError("spatial_topology_schema_mismatch")
        if payload.get("contract_sha256") != _canonical_sha256(payload):
            raise ValueError("spatial_topology_contract_hash_mismatch")
        if payload.get("admission_policy") != (
            "non_compensatory_certificate_and_admitted_rows"
        ):
            raise ValueError("spatial_topology_admission_policy_mismatch")
        required_effective_interval = payload.get("required_effective_interval")
        admission_evidence_artifact = payload.get("admission_evidence_artifact")
        return cls(
            contract_id=str(payload["contract_id"]),
            node_keys=tuple(str(value) for value in payload["node_keys"]),
            node_roles=tuple(str(value) for value in payload["node_roles"]),
            relation_types=tuple(str(value) for value in payload["relation_types"]),
            edge_feature_names=tuple(
                str(value) for value in payload["edge_feature_names"]
            ),
            allowed_role_pairs=tuple(
                (
                    str(row["relation_type"]),
                    str(row["source_role"]),
                    str(row["target_role"]),
                )
                for row in payload["allowed_role_pairs"]
            ),
            required_paths=tuple(
                (str(row["source_node_key"]), str(row["target_node_key"]))
                for row in payload["required_paths"]
            ),
            source_artifacts=tuple(
                (str(row["name"]), str(row["path"]), str(row["sha256"]))
                for row in payload.get("source_artifacts", ())
            ),
            required_effective_interval=(
                (
                    str(required_effective_interval["start_inclusive"]),
                    str(required_effective_interval["end_inclusive"]),
                )
                if required_effective_interval is not None
                else None
            ),
            admission_evidence_artifact=(
                (
                    str(admission_evidence_artifact["name"]),
                    str(admission_evidence_artifact["path"]),
                    str(admission_evidence_artifact["sha256"]),
                )
                if admission_evidence_artifact is not None
                else None
            ),
        )


class SpatialTopologyGateStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class GWMSpatialTopologyAdmissionCertificate:
    schema: str
    contract_sha256: str
    gate_statuses: dict[str, SpatialTopologyGateStatus]
    certificate_status: SpatialTopologyGateStatus
    first_nonpass_gate: str | None
    model_input_admitted: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "contract_sha256": self.contract_sha256,
            "gate_statuses": {
                gate: status.value for gate, status in self.gate_statuses.items()
            },
            "certificate_status": self.certificate_status.value,
            "first_nonpass_gate": self.first_nonpass_gate,
            "model_input_admitted": self.model_input_admitted,
            "aggregation": "non_compensatory_all_gates_must_pass",
            "claim_boundary": {
                "topology_tensor_compiled": False,
                "general_gwm_validated": False,
            },
        }


@dataclass(frozen=True)
class GWMNetworkLinearReferenceEndpoint:
    """A hash-bound endpoint address on an authoritative directed network."""

    node_key: str
    node_role: str
    network_id: str
    path_reach_id: str
    linear_reference_id: str
    measure: float
    measure_semantics: str
    longitude: float
    latitude: float
    source_id: str
    source_artifact_sha256: str

    def __post_init__(self) -> None:
        text_values = (
            self.node_key,
            self.node_role,
            self.network_id,
            self.path_reach_id,
            self.linear_reference_id,
            self.measure_semantics,
            self.source_id,
        )
        if any(not value.strip() for value in text_values):
            raise ValueError("network_linear_reference_endpoint_text_required")
        if not np.isfinite(self.measure) or not 0.0 <= self.measure <= 100.0:
            raise ValueError("network_linear_reference_measure_out_of_range")
        if (
            not np.isfinite(self.longitude)
            or not -180.0 <= self.longitude <= 180.0
            or not np.isfinite(self.latitude)
            or not -90.0 <= self.latitude <= 90.0
        ):
            raise ValueError("network_linear_reference_coordinate_invalid")
        if not _SHA256.fullmatch(self.source_artifact_sha256):
            raise ValueError("network_linear_reference_source_hash_invalid")

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_key": self.node_key,
            "node_role": self.node_role,
            "network_id": self.network_id,
            "path_reach_id": self.path_reach_id,
            "linear_reference_id": self.linear_reference_id,
            "measure": self.measure,
            "measure_semantics": self.measure_semantics,
            "longitude": self.longitude,
            "latitude": self.latitude,
            "source_id": self.source_id,
            "source_artifact_sha256": self.source_artifact_sha256,
        }


@dataclass(frozen=True)
class GWMNetworkLinearReferenceValidation:
    """Validated endpoint addresses and path binding, without metric promotion."""

    source: GWMNetworkLinearReferenceEndpoint
    target: GWMNetworkLinearReferenceEndpoint
    directed_path_reach_ids: tuple[str, ...]
    audit: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": GWM_NETWORK_LINEAR_REFERENCE_SCHEMA,
            "source": self.source.as_dict(),
            "target": self.target.as_dict(),
            "directed_path_reach_ids": list(self.directed_path_reach_ids),
            "audit": self.audit,
        }


@dataclass(frozen=True)
class GWMTemporalSeriesCrosswalkEndpoint:
    """A hash-bound observed or derived series used in a semantic crosswalk."""

    series_key: str
    publisher: str
    series_id: str
    spatial_support_id: str
    observation_semantics: str
    unit: str
    temporal_resolution: str
    timestamp_semantics: str
    source_id: str
    source_artifact_sha256: str

    def __post_init__(self) -> None:
        text_values = (
            self.series_key,
            self.publisher,
            self.series_id,
            self.spatial_support_id,
            self.observation_semantics,
            self.unit,
            self.temporal_resolution,
            self.timestamp_semantics,
            self.source_id,
        )
        if any(not value.strip() for value in text_values):
            raise ValueError("temporal_series_crosswalk_endpoint_text_required")
        if not _SHA256.fullmatch(self.source_artifact_sha256):
            raise ValueError("temporal_series_crosswalk_source_hash_invalid")

    def as_dict(self) -> dict[str, Any]:
        return {
            "series_key": self.series_key,
            "publisher": self.publisher,
            "series_id": self.series_id,
            "spatial_support_id": self.spatial_support_id,
            "observation_semantics": self.observation_semantics,
            "unit": self.unit,
            "temporal_resolution": self.temporal_resolution,
            "timestamp_semantics": self.timestamp_semantics,
            "source_id": self.source_id,
            "source_artifact_sha256": self.source_artifact_sha256,
        }


@dataclass(frozen=True)
class GWMTemporalSeriesCrosswalkValidation:
    """Fail-closed semantic identity evidence for two temporal series."""

    left_series: GWMTemporalSeriesCrosswalkEndpoint
    right_series: GWMTemporalSeriesCrosswalkEndpoint
    audit: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": GWM_TEMPORAL_SERIES_CROSSWALK_SCHEMA,
            "left_series": self.left_series.as_dict(),
            "right_series": self.right_series.as_dict(),
            "audit": self.audit,
        }


def validate_gwm_temporal_series_crosswalk(
    left_series: GWMTemporalSeriesCrosswalkEndpoint,
    right_series: GWMTemporalSeriesCrosswalkEndpoint,
    *,
    allowed_source_artifact_sha256s: Sequence[str],
    source_series_semantics_verified: bool,
    unit_semantics_verified: bool,
    timestamp_alignment_semantics_verified: bool,
    bounded_sample_value_mapping_supported: bool,
    temporal_process_relationship_supported: bool,
    full_period_value_coverage_verified: bool,
    full_period_deterministic_mapping_verified: bool,
    explicit_official_identifier_mapping_verified: bool,
    required_effective_period_verified: bool,
    publication_semantics_verified: bool,
    public_redistribution_authority_verified: bool,
) -> GWMTemporalSeriesCrosswalkValidation:
    """Validate series identity without promoting a bounded or correlated match."""

    if left_series.series_key == right_series.series_key:
        raise ValueError("temporal_series_crosswalk_distinct_series_required")
    evidence_flags = (
        source_series_semantics_verified,
        unit_semantics_verified,
        timestamp_alignment_semantics_verified,
        bounded_sample_value_mapping_supported,
        temporal_process_relationship_supported,
        full_period_value_coverage_verified,
        full_period_deterministic_mapping_verified,
        explicit_official_identifier_mapping_verified,
        required_effective_period_verified,
        publication_semantics_verified,
        public_redistribution_authority_verified,
    )
    if any(not isinstance(value, bool) for value in evidence_flags):
        raise ValueError("temporal_series_crosswalk_evidence_flags_must_be_boolean")
    if (
        full_period_deterministic_mapping_verified
        and not full_period_value_coverage_verified
    ):
        raise ValueError(
            "temporal_series_crosswalk_full_period_mapping_requires_coverage"
        )
    allowed_hashes = set(allowed_source_artifact_sha256s)
    if not allowed_hashes or any(
        not _SHA256.fullmatch(value) for value in allowed_hashes
    ):
        raise ValueError("temporal_series_crosswalk_allowed_hashes_invalid")
    endpoint_hashes = {
        left_series.source_artifact_sha256,
        right_series.source_artifact_sha256,
    }
    if not endpoint_hashes <= allowed_hashes:
        raise ValueError("temporal_series_crosswalk_source_not_bound")

    deterministic_identity_evidence = bool(
        full_period_value_coverage_verified
        and full_period_deterministic_mapping_verified
    )
    semantic_identity_evidence = bool(
        explicit_official_identifier_mapping_verified
        or deterministic_identity_evidence
    )
    if explicit_official_identifier_mapping_verified and deterministic_identity_evidence:
        identity_evidence_class = (
            "official_identifier_and_full_period_deterministic_mapping"
        )
    elif explicit_official_identifier_mapping_verified:
        identity_evidence_class = "official_identifier_mapping"
    elif deterministic_identity_evidence:
        identity_evidence_class = "full_period_deterministic_mapping"
    else:
        identity_evidence_class = "none"
    gates = {
        "source_artifact_hashes_bound": True,
        "source_series_semantics_verified": source_series_semantics_verified,
        "unit_semantics_verified": unit_semantics_verified,
        "timestamp_alignment_semantics_verified": (
            timestamp_alignment_semantics_verified
        ),
        "official_or_full_period_deterministic_mapping_verified": (
            semantic_identity_evidence
        ),
        "required_effective_period_verified": required_effective_period_verified,
    }
    first_nonpass_gate = next(
        (name for name, passed in gates.items() if not passed),
        None,
    )
    series_crosswalk_verified = bool(all(gates.values()))
    model_input_eligible = bool(
        series_crosswalk_verified and publication_semantics_verified
    )
    public_release_eligible = bool(
        model_input_eligible and public_redistribution_authority_verified
    )
    first_nonpass_model_input_gate = first_nonpass_gate
    if series_crosswalk_verified and not publication_semantics_verified:
        first_nonpass_model_input_gate = "publication_semantics_verified"

    return GWMTemporalSeriesCrosswalkValidation(
        left_series=left_series,
        right_series=right_series,
        audit={
            **gates,
            "full_period_value_coverage_verified": (
                full_period_value_coverage_verified
            ),
            "full_period_deterministic_mapping_verified": (
                full_period_deterministic_mapping_verified
            ),
            "explicit_official_identifier_mapping_verified": (
                explicit_official_identifier_mapping_verified
            ),
            "identity_evidence_class": identity_evidence_class,
            "bounded_sample_value_mapping_supported": (
                bounded_sample_value_mapping_supported
            ),
            "bounded_sample_value_mapping_is_identity_evidence": False,
            "temporal_process_relationship_supported": (
                temporal_process_relationship_supported
            ),
            "temporal_process_relationship_is_identity_evidence": False,
            "series_crosswalk_verified": series_crosswalk_verified,
            "publication_semantics_verified": publication_semantics_verified,
            "model_input_eligible": model_input_eligible,
            "public_redistribution_authority_verified": (
                public_redistribution_authority_verified
            ),
            "public_release_eligible": public_release_eligible,
            "first_nonpass_gate": first_nonpass_gate,
            "first_nonpass_model_input_gate": first_nonpass_model_input_gate,
            "aggregation": "non_compensatory_all_identity_gates_must_pass",
            "claim_boundary": {
                "bounded_sample_promoted_to_identity": False,
                "correlation_promoted_to_identity": False,
                "series_identity_verified": series_crosswalk_verified,
                "model_input_eligible": model_input_eligible,
                "public_release_eligible": public_release_eligible,
                "physical_node_identity_verified": False,
                "propagation_time_verified": False,
                "general_gwm_validated": False,
            },
        },
    )


@dataclass(frozen=True)
class GWMCompositeActionCrosswalkValidation:
    """Fail-closed decomposition of one aggregate action into components."""

    aggregate_action_series: GWMTemporalSeriesCrosswalkEndpoint
    component_series: tuple[GWMTemporalSeriesCrosswalkEndpoint, ...]
    required_component_keys: tuple[str, ...]
    required_temporal_resolution: str
    audit: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": GWM_COMPOSITE_ACTION_CROSSWALK_SCHEMA,
            "aggregate_action_series": self.aggregate_action_series.as_dict(),
            "component_series": [row.as_dict() for row in self.component_series],
            "required_component_keys": list(self.required_component_keys),
            "required_temporal_resolution": self.required_temporal_resolution,
            "audit": self.audit,
        }


def validate_gwm_composite_action_crosswalk(
    aggregate_action_series: GWMTemporalSeriesCrosswalkEndpoint,
    component_series: Sequence[GWMTemporalSeriesCrosswalkEndpoint],
    *,
    required_component_keys: Sequence[str],
    required_temporal_resolution: str,
    allowed_source_artifact_sha256s: Sequence[str],
    official_component_definition_verified: bool,
    component_series_semantics_verified: bool,
    component_physical_identities_verified: bool,
    unit_semantics_verified: bool,
    timestamp_alignment_semantics_verified: bool,
    full_period_component_coverage_verified: bool,
    deterministic_component_sum_identity_verified: bool,
    bypass_and_unmetered_release_completeness_verified: bool,
    required_effective_period_verified: bool,
    publication_semantics_verified: bool,
    public_redistribution_authority_verified: bool,
    daily_values_upsampled_or_interpolated: bool = False,
    event_values_forward_filled: bool = False,
    proximity_used_as_component_identity_evidence: bool = False,
    partial_component_sum_used_as_aggregate: bool = False,
) -> GWMCompositeActionCrosswalkValidation:
    """Validate an aggregate action decomposition without synthetic promotion."""

    components = tuple(component_series)
    required_keys = tuple(required_component_keys)
    if not components:
        raise ValueError("composite_action_crosswalk_components_required")
    if not required_keys or any(not value.strip() for value in required_keys):
        raise ValueError("composite_action_crosswalk_required_component_keys_invalid")
    if len(required_keys) != len(set(required_keys)):
        raise ValueError("composite_action_crosswalk_required_component_keys_duplicate")
    if not required_temporal_resolution.strip():
        raise ValueError("composite_action_crosswalk_temporal_resolution_required")

    component_keys = tuple(row.series_key for row in components)
    if aggregate_action_series.series_key in component_keys:
        raise ValueError("composite_action_crosswalk_aggregate_is_component")
    if len(component_keys) != len(set(component_keys)):
        raise ValueError("composite_action_crosswalk_component_keys_duplicate")

    evidence_flags = (
        official_component_definition_verified,
        component_series_semantics_verified,
        component_physical_identities_verified,
        unit_semantics_verified,
        timestamp_alignment_semantics_verified,
        full_period_component_coverage_verified,
        deterministic_component_sum_identity_verified,
        bypass_and_unmetered_release_completeness_verified,
        required_effective_period_verified,
        publication_semantics_verified,
        public_redistribution_authority_verified,
        daily_values_upsampled_or_interpolated,
        event_values_forward_filled,
        proximity_used_as_component_identity_evidence,
        partial_component_sum_used_as_aggregate,
    )
    if any(not isinstance(value, bool) for value in evidence_flags):
        raise ValueError("composite_action_crosswalk_evidence_flags_must_be_boolean")

    allowed_hashes = set(allowed_source_artifact_sha256s)
    if not allowed_hashes or any(
        not _SHA256.fullmatch(value) for value in allowed_hashes
    ):
        raise ValueError("composite_action_crosswalk_allowed_hashes_invalid")
    endpoint_hashes = {
        aggregate_action_series.source_artifact_sha256,
        *(row.source_artifact_sha256 for row in components),
    }
    if not endpoint_hashes <= allowed_hashes:
        raise ValueError("composite_action_crosswalk_source_not_bound")

    component_list_complete = bool(
        len(component_keys) == len(required_keys)
        and set(component_keys) == set(required_keys)
    )
    all_components_native_resolution = all(
        row.temporal_resolution == required_temporal_resolution
        for row in components
    )
    aggregate_native_resolution = (
        aggregate_action_series.temporal_resolution == required_temporal_resolution
    )
    prohibited_synthetic_transform_absent = not (
        daily_values_upsampled_or_interpolated or event_values_forward_filled
    )
    diagnostic_identity_promotion_absent = not (
        proximity_used_as_component_identity_evidence
        or partial_component_sum_used_as_aggregate
    )
    sum_prerequisites = bool(
        official_component_definition_verified
        and component_list_complete
        and component_series_semantics_verified
        and component_physical_identities_verified
        and unit_semantics_verified
        and timestamp_alignment_semantics_verified
        and aggregate_native_resolution
        and all_components_native_resolution
        and full_period_component_coverage_verified
        and prohibited_synthetic_transform_absent
        and diagnostic_identity_promotion_absent
    )
    if deterministic_component_sum_identity_verified and not sum_prerequisites:
        raise ValueError(
            "composite_action_crosswalk_sum_identity_requires_all_prerequisites"
        )

    gates = {
        "source_artifact_hashes_bound": True,
        "official_component_definition_verified": (
            official_component_definition_verified
        ),
        "official_component_list_complete": component_list_complete,
        "component_series_semantics_verified": component_series_semantics_verified,
        "component_physical_identities_verified": (
            component_physical_identities_verified
        ),
        "unit_semantics_verified": unit_semantics_verified,
        "aggregate_native_temporal_resolution_verified": (
            aggregate_native_resolution
        ),
        "all_component_native_temporal_resolutions_verified": (
            all_components_native_resolution
        ),
        "timestamp_alignment_semantics_verified": (
            timestamp_alignment_semantics_verified
        ),
        "prohibited_synthetic_temporal_transform_absent": (
            prohibited_synthetic_transform_absent
        ),
        "diagnostic_identity_promotion_absent": diagnostic_identity_promotion_absent,
        "full_period_component_coverage_verified": (
            full_period_component_coverage_verified
        ),
        "deterministic_component_sum_identity_verified": (
            deterministic_component_sum_identity_verified
        ),
        "bypass_and_unmetered_release_completeness_verified": (
            bypass_and_unmetered_release_completeness_verified
        ),
        "required_effective_period_verified": required_effective_period_verified,
    }
    first_nonpass_gate = next(
        (name for name, passed in gates.items() if not passed),
        None,
    )
    composite_action_crosswalk_verified = bool(all(gates.values()))
    model_input_eligible = bool(
        composite_action_crosswalk_verified and publication_semantics_verified
    )
    public_release_eligible = bool(
        model_input_eligible and public_redistribution_authority_verified
    )
    first_nonpass_model_input_gate = first_nonpass_gate
    if composite_action_crosswalk_verified and not publication_semantics_verified:
        first_nonpass_model_input_gate = "publication_semantics_verified"

    return GWMCompositeActionCrosswalkValidation(
        aggregate_action_series=aggregate_action_series,
        component_series=components,
        required_component_keys=required_keys,
        required_temporal_resolution=required_temporal_resolution,
        audit={
            **gates,
            "daily_values_upsampled_or_interpolated": (
                daily_values_upsampled_or_interpolated
            ),
            "daily_values_promoted_to_required_resolution": (
                daily_values_upsampled_or_interpolated
            ),
            "daily_values_accepted_as_native_required_resolution": False,
            "event_values_forward_filled": event_values_forward_filled,
            "event_values_promoted_to_required_resolution": (
                event_values_forward_filled
            ),
            "event_values_accepted_as_native_required_resolution": False,
            "proximity_used_as_component_identity_evidence": (
                proximity_used_as_component_identity_evidence
            ),
            "proximity_is_component_identity_evidence": False,
            "partial_component_sum_used_as_aggregate": (
                partial_component_sum_used_as_aggregate
            ),
            "partial_component_sum_is_aggregate_identity_evidence": False,
            "component_sum_prerequisites_verified": sum_prerequisites,
            "composite_action_crosswalk_verified": (
                composite_action_crosswalk_verified
            ),
            "publication_semantics_verified": publication_semantics_verified,
            "model_input_eligible": model_input_eligible,
            "public_redistribution_authority_verified": (
                public_redistribution_authority_verified
            ),
            "public_release_eligible": public_release_eligible,
            "first_nonpass_gate": first_nonpass_gate,
            "first_nonpass_model_input_gate": first_nonpass_model_input_gate,
            "aggregation": "non_compensatory_all_decomposition_gates_must_pass",
            "claim_boundary": {
                "aggregate_action_decomposition_verified": (
                    composite_action_crosswalk_verified
                ),
                "physical_action_boundary_finalized": (
                    composite_action_crosswalk_verified
                ),
                "model_input_eligible": model_input_eligible,
                "public_release_eligible": public_release_eligible,
                "synthetic_temporal_transform_detected": not (
                    prohibited_synthetic_transform_absent
                ),
                "synthetic_temporal_transform_accepted": False,
                "proximity_promoted_to_component_identity": False,
                "partial_sum_promoted_to_aggregate_identity": False,
                "general_gwm_validated": False,
            },
        },
    )


@dataclass(frozen=True)
class GWMActionNodeCrosswalkEndpoint:
    """A hash-bound observed series or physical node used in an action crosswalk."""

    node_key: str
    node_role: str
    station_id: str
    station_name: str
    series_id: str
    observation_semantics: str
    temporal_resolution: str
    network_id: str
    path_reach_id: str
    longitude: float
    latitude: float
    source_id: str
    source_artifact_sha256: str

    def __post_init__(self) -> None:
        text_values = (
            self.node_key,
            self.node_role,
            self.station_id,
            self.station_name,
            self.series_id,
            self.observation_semantics,
            self.temporal_resolution,
            self.network_id,
            self.path_reach_id,
            self.source_id,
        )
        if any(not value.strip() for value in text_values):
            raise ValueError("action_node_crosswalk_endpoint_text_required")
        if (
            not np.isfinite(self.longitude)
            or not -180.0 <= self.longitude <= 180.0
            or not np.isfinite(self.latitude)
            or not -90.0 <= self.latitude <= 90.0
        ):
            raise ValueError("action_node_crosswalk_coordinate_invalid")
        if not _SHA256.fullmatch(self.source_artifact_sha256):
            raise ValueError("action_node_crosswalk_source_hash_invalid")

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_key": self.node_key,
            "node_role": self.node_role,
            "station_id": self.station_id,
            "station_name": self.station_name,
            "series_id": self.series_id,
            "observation_semantics": self.observation_semantics,
            "temporal_resolution": self.temporal_resolution,
            "network_id": self.network_id,
            "path_reach_id": self.path_reach_id,
            "longitude": self.longitude,
            "latitude": self.latitude,
            "source_id": self.source_id,
            "source_artifact_sha256": self.source_artifact_sha256,
        }


@dataclass(frozen=True)
class GWMActionNodeCrosswalkValidation:
    """Fail-closed action-series to physical-node crosswalk evidence."""

    action_series: GWMActionNodeCrosswalkEndpoint
    physical_node: GWMActionNodeCrosswalkEndpoint
    audit: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": GWM_ACTION_NODE_CROSSWALK_SCHEMA,
            "action_series": self.action_series.as_dict(),
            "physical_node": self.physical_node.as_dict(),
            "audit": self.audit,
        }


def _great_circle_distance_m(
    left: GWMActionNodeCrosswalkEndpoint,
    right: GWMActionNodeCrosswalkEndpoint,
) -> float:
    lon1 = math.radians(left.longitude)
    lat1 = math.radians(left.latitude)
    lon2 = math.radians(right.longitude)
    lat2 = math.radians(right.latitude)
    delta_lon = lon2 - lon1
    delta_lat = lat2 - lat1
    value = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2.0) ** 2
    )
    central_angle = 2.0 * math.atan2(math.sqrt(value), math.sqrt(1.0 - value))
    return 6_371_008.8 * central_angle


def validate_gwm_action_node_crosswalk(
    action_series: GWMActionNodeCrosswalkEndpoint,
    physical_node: GWMActionNodeCrosswalkEndpoint,
    *,
    allowed_source_artifact_sha256s: Sequence[str],
    maximum_endpoint_separation_m: float,
    action_series_semantics_verified: bool,
    physical_node_semantics_verified: bool,
    official_semantic_mapping_verified: bool,
    exact_series_identity_verified: bool,
    temporal_process_relationship_supported: bool,
    required_effective_period_verified: bool,
) -> GWMActionNodeCrosswalkValidation:
    """Validate an action-node candidate without promoting diagnostic similarity."""

    if action_series.node_key == physical_node.node_key:
        raise ValueError("action_node_crosswalk_distinct_nodes_required")
    if not np.isfinite(maximum_endpoint_separation_m) or (
        maximum_endpoint_separation_m <= 0.0
    ):
        raise ValueError("action_node_crosswalk_separation_threshold_invalid")
    evidence_flags = (
        action_series_semantics_verified,
        physical_node_semantics_verified,
        official_semantic_mapping_verified,
        exact_series_identity_verified,
        temporal_process_relationship_supported,
        required_effective_period_verified,
    )
    if any(not isinstance(value, bool) for value in evidence_flags):
        raise ValueError("action_node_crosswalk_evidence_flags_must_be_boolean")
    allowed_hashes = set(allowed_source_artifact_sha256s)
    if not allowed_hashes or any(
        not _SHA256.fullmatch(value) for value in allowed_hashes
    ):
        raise ValueError("action_node_crosswalk_allowed_hashes_invalid")
    endpoint_hashes = {
        action_series.source_artifact_sha256,
        physical_node.source_artifact_sha256,
    }
    if not endpoint_hashes <= allowed_hashes:
        raise ValueError("action_node_crosswalk_source_not_bound")

    separation_m = _great_circle_distance_m(action_series, physical_node)
    same_network = action_series.network_id == physical_node.network_id
    same_path_reach = (
        same_network and action_series.path_reach_id == physical_node.path_reach_id
    )
    within_threshold = separation_m <= maximum_endpoint_separation_m
    semantic_identity_evidence = (
        official_semantic_mapping_verified or exact_series_identity_verified
    )
    candidate_supported = bool(
        same_path_reach
        and within_threshold
        and action_series_semantics_verified
        and physical_node_semantics_verified
    )
    crosswalk_verified = bool(
        candidate_supported
        and semantic_identity_evidence
        and required_effective_period_verified
    )
    gates = {
        "source_artifact_hashes_bound": True,
        "endpoint_network_identity_matches": same_network,
        "same_path_reach_verified": same_path_reach,
        "endpoint_separation_within_threshold": within_threshold,
        "action_series_semantics_verified": action_series_semantics_verified,
        "physical_node_semantics_verified": physical_node_semantics_verified,
        "official_mapping_or_exact_identity_verified": semantic_identity_evidence,
        "required_effective_period_verified": required_effective_period_verified,
    }
    first_nonpass_gate = next(
        (name for name, passed in gates.items() if not passed),
        None,
    )
    return GWMActionNodeCrosswalkValidation(
        action_series=action_series,
        physical_node=physical_node,
        audit={
            **gates,
            "official_semantic_mapping_verified": official_semantic_mapping_verified,
            "exact_series_identity_verified": exact_series_identity_verified,
            "endpoint_separation_m": round(separation_m, 6),
            "maximum_endpoint_separation_m": maximum_endpoint_separation_m,
            "temporal_process_relationship_supported": (
                temporal_process_relationship_supported
            ),
            "temporal_process_relationship_is_admission_evidence": False,
            "physical_action_node_candidate_supported": candidate_supported,
            "action_node_crosswalk_verified": crosswalk_verified,
            "first_nonpass_gate": first_nonpass_gate,
            "claim_boundary": {
                "same_reach_action_node_candidate_supported": candidate_supported,
                "diagnostic_temporal_similarity_promoted_to_identity": False,
                "official_action_node_crosswalk_verified": crosswalk_verified,
                "propagation_time_verified": False,
                "spatial_topology_model_input_admitted": False,
                "general_gwm_validated": False,
            },
        },
    )


def validate_gwm_network_linear_reference(
    source: GWMNetworkLinearReferenceEndpoint,
    target: GWMNetworkLinearReferenceEndpoint,
    *,
    directed_path_reach_ids: Sequence[str],
    allowed_source_artifact_sha256s: Sequence[str],
) -> GWMNetworkLinearReferenceValidation:
    """Bind two measured endpoints to a directed path, but not to a distance."""

    path = tuple(str(value).strip() for value in directed_path_reach_ids)
    if not path or any(not value for value in path):
        raise ValueError("network_linear_reference_path_required")
    if len(set(path)) != len(path):
        raise ValueError("network_linear_reference_path_reaches_must_be_unique")
    if source.node_key == target.node_key:
        raise ValueError("network_linear_reference_distinct_nodes_required")
    if source.network_id != target.network_id:
        raise ValueError("network_linear_reference_network_mismatch")
    if path[0] != source.path_reach_id or path[-1] != target.path_reach_id:
        raise ValueError("network_linear_reference_path_endpoint_mismatch")
    allowed_hashes = set(allowed_source_artifact_sha256s)
    if not allowed_hashes or any(not _SHA256.fullmatch(value) for value in allowed_hashes):
        raise ValueError("network_linear_reference_allowed_hashes_invalid")
    endpoint_hashes = {
        source.source_artifact_sha256,
        target.source_artifact_sha256,
    }
    if not endpoint_hashes <= allowed_hashes:
        raise ValueError("network_linear_reference_source_not_bound")

    return GWMNetworkLinearReferenceValidation(
        source=source,
        target=target,
        directed_path_reach_ids=path,
        audit={
            "source_artifact_hashes_bound": True,
            "endpoint_network_identity_matches": True,
            "directed_path_endpoints_match": True,
            "directed_path_reach_count": len(path),
            "endpoint_linear_references_verified": True,
            "network_distance_verified": False,
            "propagation_time_verified": False,
            "claim_boundary": {
                "endpoint_linear_references_validated": True,
                "directed_path_bound": True,
                "network_distance_admitted": False,
                "metric_topology_gate_passed": False,
                "general_gwm_validated": False,
            },
        },
    )


def evaluate_gwm_spatial_topology_admission(
    contract: GWMSpatialTopologyContract,
    *,
    checks: Mapping[str, bool | None | SpatialTopologyGateStatus | str],
) -> GWMSpatialTopologyAdmissionCertificate:
    """Evaluate spatial evidence without averaging failed gates."""

    extras = sorted(set(checks) - set(GWM_SPATIAL_TOPOLOGY_ADMISSION_GATES))
    if extras:
        raise ValueError("unknown_spatial_topology_admission_gates:" + ",".join(extras))
    statuses = {
        gate: _normalize_gate_status(checks.get(gate))
        for gate in GWM_SPATIAL_TOPOLOGY_ADMISSION_GATES
    }
    if any(status is SpatialTopologyGateStatus.FAIL for status in statuses.values()):
        overall = SpatialTopologyGateStatus.FAIL
    elif any(
        status is SpatialTopologyGateStatus.INDETERMINATE
        for status in statuses.values()
    ):
        overall = SpatialTopologyGateStatus.INDETERMINATE
    else:
        overall = SpatialTopologyGateStatus.PASS
    first_nonpass = next(
        (
            gate
            for gate in GWM_SPATIAL_TOPOLOGY_ADMISSION_GATES
            if statuses[gate] is not SpatialTopologyGateStatus.PASS
        ),
        None,
    )
    return GWMSpatialTopologyAdmissionCertificate(
        schema=GWM_SPATIAL_TOPOLOGY_ADMISSION_SCHEMA,
        contract_sha256=contract.as_dict()["contract_sha256"],
        gate_statuses=statuses,
        certificate_status=overall,
        first_nonpass_gate=first_nonpass,
        model_input_admitted=overall is SpatialTopologyGateStatus.PASS,
    )


@dataclass(frozen=True)
class GWMSpatialTopologyCompilation:
    """A stable typed-edge tensor representation plus its evidence audit."""

    schema: str
    contract_sha256: str
    node_keys: tuple[str, ...]
    node_roles: tuple[str, ...]
    relation_types: tuple[str, ...]
    edge_feature_names: tuple[str, ...]
    edge_index: torch.Tensor
    edge_features: torch.Tensor
    edge_types: torch.Tensor
    audit: dict[str, Any]


def compile_gwm_spatial_topology(
    node_records: pd.DataFrame,
    edge_records: pd.DataFrame,
    *,
    contract: GWMSpatialTopologyContract,
    admission_certificate: GWMSpatialTopologyAdmissionCertificate,
) -> GWMSpatialTopologyCompilation:
    """Compile admitted spatial evidence into typed directed kernel edges."""

    contract_sha256 = contract.as_dict()["contract_sha256"]
    if admission_certificate.schema != GWM_SPATIAL_TOPOLOGY_ADMISSION_SCHEMA:
        raise ValueError("spatial_topology_admission_schema_mismatch")
    if admission_certificate.contract_sha256 != contract_sha256:
        raise ValueError("spatial_topology_admission_contract_mismatch")
    expected_certificate = _certificate_from_statuses(
        contract_sha256,
        admission_certificate.gate_statuses,
    )
    if (
        admission_certificate.certificate_status
        is not expected_certificate.certificate_status
        or admission_certificate.first_nonpass_gate
        != expected_certificate.first_nonpass_gate
        or admission_certificate.model_input_admitted
        is not expected_certificate.model_input_admitted
    ):
        raise ValueError("spatial_topology_admission_certificate_inconsistent")
    if not admission_certificate.model_input_admitted:
        raise ValueError(
            "spatial_topology_admission_blocked:"
            f"{admission_certificate.first_nonpass_gate}"
        )

    nodes = _select_required_columns(
        node_records,
        GWM_SPATIAL_TOPOLOGY_NODE_COLUMNS,
        kind="node",
    )
    edges = _select_required_columns(
        edge_records,
        GWM_SPATIAL_TOPOLOGY_EDGE_COLUMNS,
        kind="edge",
    )
    if nodes.empty or edges.empty:
        raise ValueError("spatial_topology_records_empty")
    _normalize_text_columns(nodes, GWM_SPATIAL_TOPOLOGY_NODE_COLUMNS[:-1])
    _normalize_text_columns(edges, GWM_SPATIAL_TOPOLOGY_EDGE_COLUMNS[:-2])
    allowed_source_hashes = {digest for _, _, digest in contract.source_artifacts}
    _validate_admitted_evidence(
        nodes,
        kind="node",
        allowed_source_hashes=allowed_source_hashes,
    )
    _validate_admitted_evidence(
        edges,
        kind="edge",
        allowed_source_hashes=allowed_source_hashes,
    )

    if nodes["node_key"].duplicated().any():
        raise ValueError("spatial_topology_duplicate_node_key")
    expected_nodes = set(contract.node_keys)
    actual_nodes = set(nodes["node_key"])
    if actual_nodes != expected_nodes:
        raise ValueError("spatial_topology_node_set_mismatch")
    expected_roles = contract.node_role_by_key
    if not nodes["node_role"].eq(nodes["node_key"].map(expected_roles)).all():
        raise ValueError("spatial_topology_node_role_mismatch")

    for column in ("source_node_key", "target_node_key"):
        unexpected = sorted(set(edges[column]) - expected_nodes)
        if unexpected:
            raise ValueError(
                f"spatial_topology_unrequested_{column}:" + ",".join(unexpected)
            )
    if edges["source_node_key"].eq(edges["target_node_key"]).any():
        raise ValueError("spatial_topology_self_edge_unsupported")
    unexpected_relations = sorted(
        set(edges["relation_type"]) - set(contract.relation_types)
    )
    if unexpected_relations:
        raise ValueError(
            "spatial_topology_unrequested_relation_type:"
            + ",".join(unexpected_relations)
        )
    unexpected_features = sorted(
        set(edges["feature_name"]) - set(contract.edge_feature_names)
    )
    if unexpected_features:
        raise ValueError(
            "spatial_topology_unrequested_feature_name:"
            + ",".join(unexpected_features)
        )

    edge_key_columns = [
        "source_node_key",
        "target_node_key",
        "relation_type",
    ]
    feature_key_columns = [*edge_key_columns, "feature_name"]
    if edges.duplicated(feature_key_columns).any():
        raise ValueError("spatial_topology_duplicate_edge_feature")
    edges["value"] = pd.to_numeric(edges["value"], errors="raise")
    if not np.isfinite(edges["value"].to_numpy(dtype=float)).all():
        raise ValueError("spatial_topology_edge_feature_nonfinite")
    _validate_metric_feature_values(edges)

    allowed_pairs = set(contract.allowed_role_pairs)
    edge_keys = edges.loc[:, edge_key_columns].drop_duplicates()
    for row in edge_keys.itertuples(index=False):
        role_pair = (
            row.relation_type,
            expected_roles[row.source_node_key],
            expected_roles[row.target_node_key],
        )
        if role_pair not in allowed_pairs:
            raise ValueError("spatial_topology_relation_role_direction_mismatch")
    feature_counts = edges.groupby(edge_key_columns, dropna=False)[
        "feature_name"
    ].nunique()
    if not feature_counts.eq(len(contract.edge_feature_names)).all():
        raise ValueError("spatial_topology_incomplete_edge_feature_grid")

    node_order = {value: index for index, value in enumerate(contract.node_keys)}
    relation_order = {
        value: index for index, value in enumerate(contract.relation_types)
    }
    edge_keys = edge_keys.assign(
        _source_order=edge_keys["source_node_key"].map(node_order),
        _target_order=edge_keys["target_node_key"].map(node_order),
        _relation_order=edge_keys["relation_type"].map(relation_order),
    ).sort_values(["_source_order", "_target_order", "_relation_order"])
    ordered_edge_keys = list(
        edge_keys.loc[:, edge_key_columns].itertuples(index=False, name=None)
    )
    _validate_required_paths(ordered_edge_keys, contract.required_paths)

    indexed = edges.set_index(feature_key_columns)
    feature_rows = []
    for edge_key in ordered_edge_keys:
        feature_rows.append(
            [
                float(indexed.loc[(*edge_key, feature_name), "value"])
                for feature_name in contract.edge_feature_names
            ]
        )
    source_indices = [node_order[row[0]] for row in ordered_edge_keys]
    target_indices = [node_order[row[1]] for row in ordered_edge_keys]
    edge_type_indices = [relation_order[row[2]] for row in ordered_edge_keys]
    evidence = pd.concat(
        [
            nodes.loc[:, ["source_id", "source_artifact_sha256"]],
            edges.loc[:, ["source_id", "source_artifact_sha256"]],
        ],
        ignore_index=True,
    ).drop_duplicates()
    audit = {
        "node_count": len(contract.node_keys),
        "edge_count": len(ordered_edge_keys),
        "relation_type_count": len(contract.relation_types),
        "edge_feature_count": len(contract.edge_feature_names),
        "required_path_count": len(contract.required_paths),
        "required_paths_verified": True,
        "relation_role_directions_verified": True,
        "complete_edge_feature_grid": True,
        "source_artifact_count": len(evidence),
        "claim_boundary": {
            "topology_tensor_compiled": True,
            "general_geospatial_kernel_validated": False,
            "general_gwm_validated": False,
        },
    }
    return GWMSpatialTopologyCompilation(
        schema=GWM_SPATIAL_TOPOLOGY_SCHEMA,
        contract_sha256=contract_sha256,
        node_keys=contract.node_keys,
        node_roles=contract.node_roles,
        relation_types=contract.relation_types,
        edge_feature_names=contract.edge_feature_names,
        edge_index=torch.tensor(
            [source_indices, target_indices], dtype=torch.long
        ),
        edge_features=torch.tensor(feature_rows, dtype=torch.float32),
        edge_types=torch.tensor(edge_type_indices, dtype=torch.long),
        audit=audit,
    )


def attach_gwm_spatial_topology(
    batch: DAMGKBatch,
    compilation: GWMSpatialTopologyCompilation,
) -> DAMGKBatch:
    """Replace only graph tensors while preserving node-aligned batch fields."""

    if batch.node_state.shape[0] != len(compilation.node_keys):
        raise ValueError("spatial_topology_node_count_mismatch")
    device = batch.node_state.device
    return replace(
        batch,
        edge_index=compilation.edge_index.to(device=device),
        edge_features=compilation.edge_features.to(
            device=device, dtype=batch.node_state.dtype
        ),
        edge_types=compilation.edge_types.to(device=device),
        edge_valid_mask=torch.ones(
            compilation.edge_types.shape[0], dtype=torch.bool, device=device
        ),
    )


def assess_gwm_authoritative_topology_evidence(
    *,
    repo_root: Path,
    contract: GWMSpatialTopologyContract,
    required_system_ids: Sequence[str],
    evidence_path: Path | None = None,
) -> dict[str, Any]:
    """Validate a contract-pinned authoritative topology evidence package."""

    required_ids = tuple(dict.fromkeys(str(value) for value in required_system_ids))
    result: dict[str, Any] = {
        "declared": contract.admission_evidence_artifact is not None,
        "materialized": False,
        "artifact_check": None,
        "schema_verified": False,
        "contract_id_verified": False,
        "required_system_ids": list(required_ids),
        "observed_system_ids": [],
        "required_systems_present": False,
        "source_authorities_verified": False,
        "source_artifact_checks": [],
        "authoritative_connectivity_verified": False,
        "metric_feature_semantics_verified": False,
        "topology_effective_period_verified": False,
        "license_and_access_verified": None,
        "topology_tensor_structurally_compiled": False,
        "systems": {},
        "compilations": [],
        "validation_errors": [],
    }
    artifact = contract.admission_evidence_artifact
    if artifact is None:
        return result

    name, relative_path, expected_sha256 = artifact
    path = evidence_path if evidence_path is not None else repo_root / relative_path
    actual_sha256 = (
        hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    )
    artifact_check = {
        "name": name,
        "path": relative_path,
        "actual_path": _display_path(path, repo_root),
        "expected_sha256": expected_sha256,
        "actual_sha256": actual_sha256,
        "passed": actual_sha256 == expected_sha256,
    }
    result["artifact_check"] = artifact_check
    result["materialized"] = path.is_file()
    if not artifact_check["passed"]:
        result["validation_errors"].append(
            "authoritative_topology_evidence_artifact_hash_mismatch"
        )
        return result

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != GWM_AUTHORITATIVE_TOPOLOGY_EVIDENCE_SCHEMA:
            raise ValueError("authoritative_topology_evidence_schema_mismatch")
        result["schema_verified"] = True
        if payload.get("contract_id") != contract.contract_id:
            raise ValueError("authoritative_topology_evidence_contract_id_mismatch")
        result["contract_id_verified"] = True

        source_authorities = payload.get("source_authorities")
        if not isinstance(source_authorities, list) or not source_authorities:
            raise ValueError("authoritative_topology_source_authorities_required")
        authority_by_hash: dict[str, dict[str, Any]] = {}
        for row in source_authorities:
            digest = str(row.get("source_artifact_sha256", ""))
            source_id = str(row.get("source_id", "")).strip()
            authority = str(row.get("authority", "")).strip()
            access_basis = str(row.get("license_or_access_basis", "")).strip()
            if (
                not _SHA256.fullmatch(digest)
                or not source_id
                or not authority
                or not access_basis
                or digest in authority_by_hash
            ):
                raise ValueError("authoritative_topology_source_authority_invalid")
            authority_by_hash[digest] = dict(row)

        allowed_source_hashes = {
            digest for _, _, digest in contract.source_artifacts
        }
        if not set(authority_by_hash) <= allowed_source_hashes:
            raise ValueError("authoritative_topology_source_not_contract_bound")
        source_artifact_checks = []
        artifact_by_hash = {
            digest: (name, relative_path)
            for name, relative_path, digest in contract.source_artifacts
        }
        for digest, authority in authority_by_hash.items():
            artifact_name, artifact_path = artifact_by_hash[digest]
            source_path = repo_root / artifact_path
            actual = (
                hashlib.sha256(source_path.read_bytes()).hexdigest()
                if source_path.is_file()
                else None
            )
            source_artifact_checks.append(
                {
                    "name": artifact_name,
                    "source_id": authority["source_id"],
                    "path": artifact_path,
                    "actual_path": _display_path(source_path, repo_root),
                    "expected_sha256": digest,
                    "actual_sha256": actual,
                    "passed": actual == digest,
                }
            )
        result["source_artifact_checks"] = source_artifact_checks
        if not all(row["passed"] for row in source_artifact_checks):
            raise ValueError("authoritative_topology_source_hash_mismatch")

        metric_definitions = payload.get("metric_definitions")
        if not isinstance(metric_definitions, list):
            raise ValueError("authoritative_topology_metric_definitions_required")
        metric_by_name = {
            str(row.get("feature_name", "")): row for row in metric_definitions
        }
        if set(metric_by_name) != set(contract.edge_feature_names):
            raise ValueError("authoritative_topology_metric_definition_set_mismatch")
        expected_units = {
            "network_distance_km": "km",
            "propagation_time_hours": "hour",
            "topology_confidence": "unitless_0_1",
        }
        for feature_name, definition in metric_by_name.items():
            if not str(definition.get("definition", "")).strip():
                raise ValueError("authoritative_topology_metric_definition_required")
            digest = str(definition.get("source_artifact_sha256", ""))
            if digest not in authority_by_hash:
                raise ValueError("authoritative_topology_metric_source_unverified")
            expected_unit = expected_units.get(feature_name)
            if expected_unit is not None and definition.get("unit") != expected_unit:
                raise ValueError("authoritative_topology_metric_unit_mismatch")

        systems = payload.get("systems")
        if not isinstance(systems, list) or not systems:
            raise ValueError("authoritative_topology_systems_required")
        observed_ids = [str(row.get("system_id", "")) for row in systems]
        if any(not value for value in observed_ids) or len(observed_ids) != len(
            set(observed_ids)
        ):
            raise ValueError("authoritative_topology_system_ids_invalid")
        result["observed_system_ids"] = observed_ids
        result["required_systems_present"] = set(required_ids) <= set(observed_ids)

        structural_certificate = evaluate_gwm_spatial_topology_admission(
            contract,
            checks={gate: True for gate in GWM_SPATIAL_TOPOLOGY_ADMISSION_GATES},
        )
        system_results: dict[str, dict[str, Any]] = {}
        compilations = []
        for system in systems:
            system_id = str(system["system_id"])
            system_result: dict[str, Any] = {
                "system_id": system_id,
                "authoritative_connectivity_verified": False,
                "metric_feature_semantics_verified": False,
                "topology_effective_period_verified": False,
                "topology_tensor_structurally_compiled": False,
                "action_to_outcome_network_distance_km": None,
                "intervening_control_structure_count": None,
                "all_intervening_control_nodes_explicit": False,
                "validation_error": None,
            }
            try:
                node_records = pd.DataFrame(system["node_records"])
                edge_records = pd.DataFrame(system["edge_records"])
                used_pairs = set(
                    zip(
                        pd.concat(
                            [
                                node_records["source_id"],
                                edge_records["source_id"],
                            ],
                            ignore_index=True,
                        ).astype(str),
                        pd.concat(
                            [
                                node_records["source_artifact_sha256"],
                                edge_records["source_artifact_sha256"],
                            ],
                            ignore_index=True,
                        ).astype(str),
                        strict=True,
                    )
                )
                for source_id, digest in used_pairs:
                    authority = authority_by_hash.get(digest)
                    if authority is None or authority["source_id"] != source_id:
                        raise ValueError(
                            "authoritative_topology_record_source_unverified"
                        )
                interval = system["effective_interval"]
                interval_start = _utc_timestamp(
                    interval["start_inclusive"], "evidence_effective_start"
                )
                interval_end = _utc_timestamp(
                    interval["end_inclusive"], "evidence_effective_end"
                )
                effective_verified = False
                if contract.required_effective_interval is not None:
                    required_start = _utc_timestamp(
                        contract.required_effective_interval[0],
                        "contract_effective_start",
                    )
                    required_end = _utc_timestamp(
                        contract.required_effective_interval[1],
                        "contract_effective_end",
                    )
                    effective_verified = (
                        interval_start <= required_start and interval_end >= required_end
                    )
                compilation = compile_gwm_spatial_topology(
                    node_records,
                    edge_records,
                    contract=contract,
                    admission_certificate=structural_certificate,
                )
                distance = _directed_feature_path_sum(
                    edge_records,
                    source_node_key="controlled_release",
                    target_node_key="downstream_gauge",
                    feature_name="network_distance_km",
                )
                controls = system.get("intervening_control_nodes", [])
                if (
                    not isinstance(controls, list)
                    or any(not isinstance(value, str) or not value for value in controls)
                    or len(controls) != len(set(controls))
                    or {"controlled_release", "downstream_gauge"} & set(controls)
                ):
                    raise ValueError(
                        "authoritative_topology_intervening_control_nodes_invalid"
                    )
                node_keys = set(node_records["node_key"].astype(str))
                controls_explicit_on_path = all(
                    control in node_keys
                    and _node_on_directed_path(
                        edge_records,
                        source_node_key="controlled_release",
                        through_node_key=control,
                        target_node_key="downstream_gauge",
                    )
                    for control in controls
                )
                checks = system.get("checks", {})
                if (
                    checks.get("all_intervening_control_nodes_explicit") is True
                    and not controls_explicit_on_path
                ):
                    raise ValueError(
                        "authoritative_topology_intervening_control_nodes_not_explicit_on_path"
                    )
                connectivity_verified = bool(
                    checks.get("authoritative_connectivity_verified") is True
                    and compilation.audit["required_paths_verified"]
                    and compilation.audit["relation_role_directions_verified"]
                )
                metric_verified = bool(
                    checks.get("metric_feature_semantics_verified") is True
                    and compilation.audit["complete_edge_feature_grid"]
                    and distance > 0.0
                )
                system_result.update(
                    {
                        "authoritative_connectivity_verified": connectivity_verified,
                        "metric_feature_semantics_verified": metric_verified,
                        "topology_effective_period_verified": effective_verified,
                        "topology_tensor_structurally_compiled": True,
                        "action_to_outcome_network_distance_km": round(distance, 9),
                        "intervening_control_structure_count": len(controls),
                        "all_intervening_control_nodes_explicit": bool(
                            checks.get("all_intervening_control_nodes_explicit")
                            is True
                            and controls_explicit_on_path
                        ),
                    }
                )
                compilations.append(
                    {
                        "system_id": system_id,
                        "contract_sha256": compilation.contract_sha256,
                        "node_keys": list(compilation.node_keys),
                        "node_roles": list(compilation.node_roles),
                        "edge_index": compilation.edge_index.tolist(),
                        "edge_features": compilation.edge_features.tolist(),
                        "edge_types": compilation.edge_types.tolist(),
                        "audit": compilation.audit,
                    }
                )
            except (KeyError, TypeError, ValueError) as exc:
                system_result["validation_error"] = str(exc)
            system_results[system_id] = system_result

        required_results = [system_results.get(value) for value in required_ids]
        required_complete = bool(required_results) and all(
            row is not None for row in required_results
        )
        result["source_authorities_verified"] = True
        result["authoritative_connectivity_verified"] = bool(
            required_complete
            and all(
                row["authoritative_connectivity_verified"]
                for row in required_results
                if row is not None
            )
        )
        result["metric_feature_semantics_verified"] = bool(
            required_complete
            and all(
                row["metric_feature_semantics_verified"]
                for row in required_results
                if row is not None
            )
        )
        result["topology_effective_period_verified"] = bool(
            required_complete
            and all(
                row["topology_effective_period_verified"]
                for row in required_results
                if row is not None
            )
        )
        result["topology_tensor_structurally_compiled"] = bool(
            required_complete
            and all(
                row["topology_tensor_structurally_compiled"]
                for row in required_results
                if row is not None
            )
        )
        license_values = [
            row.get("license_and_access_verified") for row in authority_by_hash.values()
        ]
        result["license_and_access_verified"] = (
            False
            if any(value is False for value in license_values)
            else True
            if license_values and all(value is True for value in license_values)
            else None
        )
        result["systems"] = system_results
        result["compilations"] = compilations
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        result["validation_errors"].append(str(exc))
    return result


def _node_on_directed_path(
    edge_records: pd.DataFrame,
    *,
    source_node_key: str,
    through_node_key: str,
    target_node_key: str,
) -> bool:
    required = {
        "source_node_key",
        "target_node_key",
        "admission_status",
    }
    if not required <= set(edge_records.columns):
        return False
    admitted = edge_records.loc[
        edge_records["admission_status"].astype(str).eq("admitted")
    ]
    adjacency: dict[str, set[str]] = {}
    for source, target in admitted[
        ["source_node_key", "target_node_key"]
    ].drop_duplicates().itertuples(index=False, name=None):
        adjacency.setdefault(str(source), set()).add(str(target))

    def reachable(source: str, target: str) -> bool:
        frontier = [source]
        visited: set[str] = set()
        while frontier:
            current = frontier.pop()
            if current == target:
                return True
            if current in visited:
                continue
            visited.add(current)
            frontier.extend(adjacency.get(current, set()) - visited)
        return False

    return reachable(source_node_key, through_node_key) and reachable(
        through_node_key, target_node_key
    )


def _utc_timestamp(value: Any, field: str) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"spatial_topology_{field}_invalid") from exc
    if timestamp.tzinfo is None:
        raise ValueError(f"spatial_topology_{field}_must_be_timezone_aware")
    return timestamp.tz_convert("UTC")


def _directed_feature_path_sum(
    edge_records: pd.DataFrame,
    *,
    source_node_key: str,
    target_node_key: str,
    feature_name: str,
) -> float:
    required = {"source_node_key", "target_node_key", "feature_name", "value"}
    if not required <= set(edge_records.columns):
        raise ValueError("spatial_topology_path_metric_columns_missing")
    rows = edge_records.loc[
        edge_records["feature_name"].astype(str).eq(feature_name)
    ].copy()
    rows["value"] = pd.to_numeric(rows["value"], errors="raise")
    adjacency: dict[str, list[tuple[str, float]]] = {}
    for row in rows.itertuples(index=False):
        value = float(row.value)
        if not np.isfinite(value) or value <= 0.0:
            raise ValueError("spatial_topology_path_metric_invalid")
        adjacency.setdefault(str(row.source_node_key), []).append(
            (str(row.target_node_key), value)
        )
    distances = {source_node_key: 0.0}
    frontier = {source_node_key}
    while frontier:
        current = min(frontier, key=lambda node: distances[node])
        frontier.remove(current)
        if current == target_node_key:
            return distances[current]
        for neighbor, value in adjacency.get(current, ()):
            candidate = distances[current] + value
            if candidate < distances.get(neighbor, float("inf")):
                distances[neighbor] = candidate
                frontier.add(neighbor)
    raise ValueError(
        f"spatial_topology_feature_path_missing:{source_node_key}:{target_node_key}"
    )


def assess_gwm_spatial_topology_evidence(
    *,
    repo_root: Path,
    contract_path: Path,
    crosswalk_path: Path,
    candidate_path: Path,
    evidence_path: Path | None = None,
) -> dict[str, Any]:
    """Recompute a HydroControl topology certificate from frozen evidence."""

    selected = {
        "contract": contract_path,
        "crosswalk": crosswalk_path,
        "candidate": candidate_path,
    }
    missing = [name for name, path in selected.items() if not path.is_file()]
    if missing:
        raise ValueError("spatial_topology_missing_reports:" + ",".join(missing))
    snapshots = {name: _load_json_snapshot(path) for name, path in selected.items()}
    reports = {name: value[0] for name, value in snapshots.items()}
    hashes = {name: value[1] for name, value in snapshots.items()}
    contract = GWMSpatialTopologyContract.from_dict(reports["contract"])

    source_artifact_checks = []
    selected_source_paths = {
        "nwm_q_lateral_crosswalk": crosswalk_path,
    }
    for name, relative_path, expected_sha256 in contract.source_artifacts:
        path = selected_source_paths.get(name, repo_root / relative_path)
        actual_sha256 = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        )
        source_artifact_checks.append(
            {
                "name": name,
                "path": relative_path,
                "actual_path": _display_path(path, repo_root),
                "sha256": expected_sha256,
                "actual_sha256": actual_sha256,
                "passed": actual_sha256 == expected_sha256,
            }
        )

    crosswalk = reports["crosswalk"]
    candidate = reports["candidate"]
    crosswalk_checks = crosswalk["checks"]
    candidate_checks = candidate["checks"]
    node_roles_declared = bool(
        crosswalk["protocol"]["candidate_role"] == "tributary_flow_cfs"
        and all(
            row["action_comid"] != row["outcome_comid"]
            for row in crosswalk["systems"].values()
        )
    )
    direction_semantics_screened = bool(
        candidate_checks["official_nldi_direction_screening_observed"]
        and candidate_checks["negative_direction_case_preserved"]
        and crosswalk_checks["three_action_upstream_sets_nested_in_outcome_sets"]
        and crosswalk_checks[
            "all_mainstem_reaches_after_action_in_incremental_sets"
        ]
    )
    authoritative_evidence = assess_gwm_authoritative_topology_evidence(
        repo_root=repo_root,
        contract=contract,
        required_system_ids=tuple(crosswalk["systems"]),
        evidence_path=evidence_path,
    )
    authoritative_connectivity = authoritative_evidence[
        "authoritative_connectivity_verified"
    ]
    metric_feature_semantics = authoritative_evidence[
        "metric_feature_semantics_verified"
    ]
    temporal_validity = authoritative_evidence[
        "topology_effective_period_verified"
    ]
    evidence_artifact_check = authoritative_evidence["artifact_check"]
    certificate = evaluate_gwm_spatial_topology_admission(
        contract,
        checks={
            "source_identity_and_hashes": bool(
                all(row["passed"] for row in source_artifact_checks)
                and candidate_checks["frozen_source_artifacts_verified"]
                and crosswalk_checks[
                    "official_listing_matches_downloaded_sample_size"
                ]
                and crosswalk_checks["feature_ids_unique_in_sample"]
                and (
                    evidence_artifact_check is None
                    or evidence_artifact_check["passed"]
                )
            ),
            "node_role_semantics": node_roles_declared,
            "directed_relation_semantics": direction_semantics_screened,
            "authoritative_connectivity": authoritative_connectivity,
            "metric_feature_semantics": metric_feature_semantics,
            "temporal_validity": temporal_validity,
            "license_and_access": authoritative_evidence[
                "license_and_access_verified"
            ],
        },
    )
    topology_tensor_compiled = bool(
        certificate.model_input_admitted
        and authoritative_evidence["topology_tensor_structurally_compiled"]
    )
    result = certificate.as_dict()
    result["role"] = "gwm_geospatial_kernel_spatial_topology_admission"
    result["domain_binding"] = "hydrocontrol_validation_track"
    result["source_artifacts"] = {
        name: {
            "path": _display_path(path, repo_root),
            "sha256": hashes[name],
            "status": reports[name].get("status"),
        }
        for name, path in selected.items()
    }
    if evidence_artifact_check is not None and evidence_artifact_check["passed"]:
        result["source_artifacts"]["authoritative_evidence"] = {
            "path": evidence_artifact_check["actual_path"],
            "sha256": evidence_artifact_check["actual_sha256"],
            "status": "authoritative_topology_evidence_snapshot",
        }
    result["contract_source_artifact_checks"] = source_artifact_checks
    result["authoritative_evidence"] = authoritative_evidence
    result["evidence_summary"] = {
        "system_count": crosswalk["summary"]["system_count"],
        "candidate_crosswalk_count": crosswalk["summary"][
            "spatial_crosswalk_candidate_frozen_count"
        ],
        "direction_semantics_screened": direction_semantics_screened,
        "authoritative_connectivity_verified": authoritative_connectivity,
        "network_distance_verified": metric_feature_semantics,
        "topology_effective_period_verified": temporal_validity,
        "topology_tensor_compiled": topology_tensor_compiled,
    }
    result["next_required_gates"] = [
        gate
        for gate, status in certificate.gate_statuses.items()
        if status.value != "pass"
    ]
    result["claim_boundary"] = {
        "candidate_crosswalk_frozen": True,
        "topology_model_input_admitted": certificate.model_input_admitted,
        "topology_tensor_compiled": topology_tensor_compiled,
        "forcing_training_input_admitted": False,
        "general_geospatial_kernel_validated": False,
        "general_gwm_validated": False,
    }
    result["architecture_boundary"] = {
        "gwm": "cross_domain_geospatial_world_model_contract",
        "twm": "territorial_and_land_system_domain_instance",
        "uwm": "urban_system_domain_instance",
        "hydrocontrol": "gwm_kernel_validation_adapter_not_gwm_itself",
    }
    return result


def _require_unique_nonempty(values: Sequence[str], field: str) -> None:
    if not values or len(set(values)) != len(values) or any(
        not value.strip() for value in values
    ):
        raise ValueError(f"spatial_topology_{field}_must_be_unique")


def _normalize_gate_status(
    value: bool | None | SpatialTopologyGateStatus | str,
) -> SpatialTopologyGateStatus:
    if value is True:
        return SpatialTopologyGateStatus.PASS
    if value is False:
        return SpatialTopologyGateStatus.FAIL
    if value is None:
        return SpatialTopologyGateStatus.INDETERMINATE
    try:
        return SpatialTopologyGateStatus(value)
    except ValueError as exc:
        raise ValueError(f"invalid_spatial_topology_admission_status:{value}") from exc


def _certificate_from_statuses(
    contract_sha256: str,
    statuses: Mapping[str, SpatialTopologyGateStatus],
) -> GWMSpatialTopologyAdmissionCertificate:
    if set(statuses) != set(GWM_SPATIAL_TOPOLOGY_ADMISSION_GATES):
        raise ValueError("spatial_topology_admission_gate_set_mismatch")
    normalized = {
        gate: _normalize_gate_status(statuses[gate])
        for gate in GWM_SPATIAL_TOPOLOGY_ADMISSION_GATES
    }
    if any(
        status is SpatialTopologyGateStatus.FAIL for status in normalized.values()
    ):
        overall = SpatialTopologyGateStatus.FAIL
    elif any(
        status is SpatialTopologyGateStatus.INDETERMINATE
        for status in normalized.values()
    ):
        overall = SpatialTopologyGateStatus.INDETERMINATE
    else:
        overall = SpatialTopologyGateStatus.PASS
    first_nonpass = next(
        (
            gate
            for gate in GWM_SPATIAL_TOPOLOGY_ADMISSION_GATES
            if normalized[gate] is not SpatialTopologyGateStatus.PASS
        ),
        None,
    )
    return GWMSpatialTopologyAdmissionCertificate(
        schema=GWM_SPATIAL_TOPOLOGY_ADMISSION_SCHEMA,
        contract_sha256=contract_sha256,
        gate_statuses=normalized,
        certificate_status=overall,
        first_nonpass_gate=first_nonpass,
        model_input_admitted=overall is SpatialTopologyGateStatus.PASS,
    )


def _select_required_columns(
    records: pd.DataFrame,
    required: Sequence[str],
    *,
    kind: str,
) -> pd.DataFrame:
    missing = sorted(set(required) - set(records.columns))
    if missing:
        raise ValueError(
            f"spatial_topology_missing_{kind}_columns:" + ",".join(missing)
        )
    return records.loc[:, required].copy()


def _normalize_text_columns(frame: pd.DataFrame, columns: Sequence[str]) -> None:
    for column in columns:
        if frame[column].isna().any() or frame[column].astype(str).str.strip().eq("").any():
            raise ValueError(f"spatial_topology_text_value_required:{column}")
        frame[column] = frame[column].astype(str)


def _validate_metric_feature_values(edges: pd.DataFrame) -> None:
    constraints = {
        "network_distance_km": lambda values: values.gt(0.0).all(),
        "propagation_time_hours": lambda values: values.ge(0.0).all(),
        "topology_confidence": lambda values: values.between(
            0.0, 1.0, inclusive="both"
        ).all(),
    }
    for feature_name, predicate in constraints.items():
        selected = edges.loc[edges["feature_name"].eq(feature_name), "value"]
        if not selected.empty and not bool(predicate(selected)):
            raise ValueError(
                f"spatial_topology_metric_feature_out_of_range:{feature_name}"
            )


def _validate_admitted_evidence(
    frame: pd.DataFrame,
    *,
    kind: str,
    allowed_source_hashes: set[str],
) -> None:
    if not frame["admission_status"].astype(str).eq("admitted").all():
        raise ValueError(f"spatial_topology_contains_unadmitted_{kind}_record")
    if frame["source_id"].isna().any() or frame["source_id"].astype(str).str.strip().eq("").any():
        raise ValueError(f"spatial_topology_{kind}_source_id_required")
    hashes = frame["source_artifact_sha256"].astype(str)
    if not hashes.map(lambda value: bool(_SHA256.fullmatch(value))).all():
        raise ValueError(f"spatial_topology_{kind}_source_sha256_required")
    if not set(hashes).issubset(allowed_source_hashes):
        raise ValueError(f"spatial_topology_{kind}_source_not_bound_to_contract")


def _validate_required_paths(
    edge_keys: Sequence[tuple[str, str, str]],
    required_paths: Sequence[tuple[str, str]],
) -> None:
    adjacency: dict[str, set[str]] = {}
    for source, target, _ in edge_keys:
        adjacency.setdefault(source, set()).add(target)
    for source, target in required_paths:
        frontier = [source]
        visited = {source}
        while frontier:
            current = frontier.pop()
            if current == target:
                break
            for neighbor in adjacency.get(current, ()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    frontier.append(neighbor)
        if target not in visited:
            raise ValueError(f"spatial_topology_required_path_missing:{source}:{target}")


def _load_json_snapshot(path: Path) -> tuple[dict[str, Any], str]:
    body = path.read_bytes()
    return json.loads(body), hashlib.sha256(body).hexdigest()
