"""Registry validation and bounded request planning for GeoTransport v0.1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import quote, urlencode


PUBLIC_DATA_REGISTRY_SCHEMA = "gwm.geotransport.public_data_registry.v1"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY_PATH = (
    REPO_ROOT / "benchmarks/geotransport_v0_1/public_data_registry.json"
)
NWM_Q_LATERAL_FEATURE_CHUNK_WIDTH = 30_000
ADMITTED_NWM_CROSSWALK_STATUS = "admitted_nldi_path_and_nwm_v3_membership"


@dataclass(frozen=True)
class PublicDataRegistry:
    payload: dict[str, Any]
    sha256: str

    def systems(self, cohort: str = "minimal") -> tuple[dict[str, Any], ...]:
        cohort_ids = self.payload["cohorts"].get(cohort)
        if cohort_ids is None:
            raise ValueError("unknown_registry_cohort")
        by_id = {system["system_id"]: system for system in self.payload["systems"]}
        return tuple(by_id[system_id] for system_id in cohort_ids)


@dataclass(frozen=True)
class AcquisitionRequest:
    request_id: str
    source: str
    kind: str
    url: str
    system_id: str | None
    variable_role: str
    expected_media_type: str
    paginated: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "source": self.source,
            "kind": self.kind,
            "url": self.url,
            "system_id": self.system_id,
            "variable_role": self.variable_role,
            "expected_media_type": self.expected_media_type,
            "paginated": self.paginated,
        }


def load_public_data_registry(
    path: Path = DEFAULT_REGISTRY_PATH,
    *,
    evidence_root: Path = REPO_ROOT,
) -> PublicDataRegistry:
    body = path.read_bytes()
    payload = json.loads(body)
    validate_public_data_registry(payload)
    _validate_crosswalk_evidence(payload, evidence_root=evidence_root)
    _validate_nwm_smoke_evidence(payload, evidence_root=evidence_root)
    _validate_travel_time_prior_evidence(payload, evidence_root=evidence_root)
    _validate_smoke_panel_evidence(payload, evidence_root=evidence_root)
    return PublicDataRegistry(payload=payload, sha256=hashlib.sha256(body).hexdigest())


def validate_public_data_registry(payload: Mapping[str, Any]) -> None:
    if payload.get("schema") != PUBLIC_DATA_REGISTRY_SCHEMA:
        raise ValueError("public_data_registry_schema_mismatch")
    sources = payload.get("source_contracts")
    systems = payload.get("systems")
    cohorts = payload.get("cohorts")
    if not isinstance(sources, Mapping) or not sources:
        raise ValueError("source_contracts_required")
    if not isinstance(systems, list) or not systems:
        raise ValueError("registry_systems_required")
    if not isinstance(cohorts, Mapping) or "minimal" not in cohorts:
        raise ValueError("minimal_cohort_required")
    system_ids = [system.get("system_id") for system in systems]
    if any(not isinstance(system_id, str) or not system_id for system_id in system_ids):
        raise ValueError("registry_system_id_required")
    if len(system_ids) != len(set(system_ids)):
        raise ValueError("registry_system_ids_must_be_unique")
    minimal = cohorts["minimal"]
    if len(minimal) != len(set(minimal)) or not set(minimal) <= set(system_ids):
        raise ValueError("minimal_cohort_membership_invalid")
    track_counts = {"GeoTransport-H": 0, "GeoTransport-D": 0, "GeoConservation-D": 0}
    by_id = {system["system_id"]: system for system in systems}
    for system_id in minimal:
        system = by_id[system_id]
        track = system.get("track")
        if track not in track_counts:
            raise ValueError("unsupported_registry_track")
        track_counts[track] += 1
        _validate_system(system, sources)
    if track_counts != {"GeoTransport-H": 3, "GeoTransport-D": 4, "GeoConservation-D": 2}:
        raise ValueError("minimal_cohort_track_counts_mismatch")


def _validate_system(system: Mapping[str, Any], sources: Mapping[str, Any]) -> None:
    action = system.get("action")
    state_context = system.get("state_context")
    if not isinstance(action, Mapping) or action.get("role") != "boundary_action":
        raise ValueError("system_boundary_action_required")
    if action.get("source") == "usace_cwms" and not action.get("location_id"):
        raise ValueError("cwms_action_location_id_required")
    if not isinstance(state_context, list) or not state_context:
        raise ValueError("system_state_context_required")
    referenced_sources = [action.get("source")]
    referenced_sources.extend(field.get("source") for field in state_context)
    forcing = system.get("forcing")
    outcome = system.get("outcome")
    if system["track"].startswith("GeoTransport"):
        if action.get("operator_sign") != 1:
            raise ValueError("transport_boundary_action_must_enter_downstream_domain")
        if not isinstance(forcing, Mapping):
            raise ValueError("transport_forcing_required")
        if forcing.get("role") != "modeled_forcing" or forcing.get("ground_truth") is not False:
            raise ValueError("transport_forcing_semantics_invalid")
        if forcing.get("variable") != "q_lateral":
            raise ValueError("transport_q_lateral_required")
        _validate_nwm_crosswalk_fields(forcing, system_id=system["system_id"])
        if not isinstance(outcome, Mapping) or outcome.get("role") != "independent_observation":
            raise ValueError("transport_independent_outcome_required")
        if action.get("source") == outcome.get("source"):
            raise ValueError("transport_action_outcome_source_must_be_independent")
        referenced_sources.extend((forcing.get("source"), outcome.get("source")))
    else:
        if forcing is not None or outcome is not None:
            raise ValueError("conservation_track_must_not_claim_transport_outcome")
        if action.get("operator_sign") != -1:
            raise ValueError("conservation_release_must_leave_reservoir_stock")
        for field in state_context:
            if field.get("role") == "source" and field.get("operator_sign") != 1:
                raise ValueError("conservation_source_sign_invalid")
            if field.get("role") == "sink" and field.get("operator_sign") != -1:
                raise ValueError("conservation_sink_sign_invalid")
    referenced_sources.append(system.get("topology", {}).get("source"))
    if any(source not in sources for source in referenced_sources):
        raise ValueError("system_references_unknown_source")
    window = system.get("study_window")
    if not isinstance(window, list) or len(window) != 2:
        raise ValueError("system_study_window_required")
    if _parse_utc(window[0]) >= _parse_utc(window[1]):
        raise ValueError("system_study_window_invalid")


def _validate_nwm_crosswalk_fields(
    forcing: Mapping[str, Any], *, system_id: str
) -> None:
    feature_ids = forcing.get("feature_ids")
    feature_indices = forcing.get("feature_indices")
    chunk_indices = forcing.get("q_lateral_feature_chunk_indices")
    status = forcing.get("crosswalk_status")
    if not feature_ids:
        if feature_indices or chunk_indices or status == ADMITTED_NWM_CROSSWALK_STATUS:
            raise ValueError(f"nwm_feature_crosswalk_partially_populated:{system_id}")
        return
    if not isinstance(feature_ids, list) or any(
        not isinstance(value, int) or isinstance(value, bool) or value <= 0
        for value in feature_ids
    ):
        raise ValueError(f"nwm_feature_ids_invalid:{system_id}")
    if len(feature_ids) != len(set(feature_ids)):
        raise ValueError(f"nwm_feature_ids_must_be_unique:{system_id}")
    if not isinstance(feature_indices, list) or len(feature_indices) != len(feature_ids):
        raise ValueError(f"nwm_feature_index_count_mismatch:{system_id}")
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in feature_indices
    ):
        raise ValueError(f"nwm_feature_indices_invalid:{system_id}")
    if len(feature_indices) != len(set(feature_indices)):
        raise ValueError(f"nwm_feature_indices_must_be_unique:{system_id}")
    expected_chunks = sorted(
        {value // NWM_Q_LATERAL_FEATURE_CHUNK_WIDTH for value in feature_indices}
    )
    if chunk_indices != expected_chunks:
        raise ValueError(f"nwm_feature_chunk_indices_mismatch:{system_id}")
    if status != ADMITTED_NWM_CROSSWALK_STATUS:
        raise ValueError(f"nwm_feature_crosswalk_not_admitted:{system_id}")


def _validate_crosswalk_evidence(
    payload: Mapping[str, Any], *, evidence_root: Path
) -> None:
    transport_systems = {
        system["system_id"]: system
        for system in payload["systems"]
        if system["track"].startswith("GeoTransport")
    }
    if not any(system["forcing"].get("feature_ids") for system in transport_systems.values()):
        return
    evidence = payload.get("crosswalk_evidence")
    if not isinstance(evidence, Mapping):
        raise ValueError("crosswalk_evidence_required")
    parent_hash = evidence.get("parent_registry_sha256")
    if parent_hash is None:
        parent_hash = payload.get("parent_registry_sha256")
    if not isinstance(parent_hash, str) or len(parent_hash) != 64:
        raise ValueError("crosswalk_parent_registry_sha256_required")
    nldi, nldi_hash = _load_hashed_evidence(
        evidence.get("nldi_path_report"), evidence_root=evidence_root
    )
    nwm, nwm_hash = _load_hashed_evidence(
        evidence.get("nwm_feature_membership_report"), evidence_root=evidence_root
    )
    if nldi.get("registry_sha256") != parent_hash or nwm.get("registry_sha256") != parent_hash:
        raise ValueError("crosswalk_parent_registry_hash_mismatch")
    if nldi.get("topology_gate_status") != "pass":
        raise ValueError("nldi_topology_gate_must_pass")
    if nwm.get("membership_gate_status") != "pass":
        raise ValueError("nwm_membership_gate_must_pass")
    if nwm.get("path_report_sha256") != nldi_hash:
        raise ValueError("nwm_membership_path_report_hash_mismatch")
    for row in nldi.get("systems", []):
        _verify_hashed_artifact(
            (row.get("action_point") or {}).get("evidence"),
            evidence_root=evidence_root,
        )
        _verify_hashed_artifact(
            row.get("gauge_evidence"), evidence_root=evidence_root
        )
        for descriptor in (row.get("source_requests") or {}).values():
            _verify_hashed_artifact(descriptor, evidence_root=evidence_root)
    for key in (
        "feature_coordinate_metadata",
        "q_lateral_metadata",
        "feature_coordinate_chunk",
    ):
        _verify_hashed_artifact(nwm.get(key), evidence_root=evidence_root)
    nldi_by_id = {row.get("system_id"): row for row in nldi.get("systems", [])}
    nwm_by_id = {row.get("system_id"): row for row in nwm.get("systems", [])}
    if set(nldi_by_id) != set(transport_systems) or set(nwm_by_id) != set(
        transport_systems
    ):
        raise ValueError("crosswalk_evidence_system_membership_mismatch")
    chunk_width = int(nwm.get("q_lateral_metadata", {}).get("chunks", [0, 0])[1])
    if chunk_width != NWM_Q_LATERAL_FEATURE_CHUNK_WIDTH:
        raise ValueError("nwm_evidence_feature_chunk_width_mismatch")
    for system_id, system in transport_systems.items():
        forcing = system["forcing"]
        nldi_ids = (nldi_by_id[system_id].get("path") or {}).get("feature_ids")
        nwm_row = nwm_by_id[system_id]
        if forcing["feature_ids"] != nldi_ids or forcing["feature_ids"] != nwm_row.get(
            "feature_ids"
        ):
            raise ValueError(f"crosswalk_feature_ids_evidence_mismatch:{system_id}")
        if forcing["feature_indices"] != nwm_row.get("feature_indices"):
            raise ValueError(f"crosswalk_feature_indices_evidence_mismatch:{system_id}")
        if forcing["q_lateral_feature_chunk_indices"] != nwm_row.get(
            "q_lateral_feature_chunk_indices"
        ):
            raise ValueError(f"crosswalk_chunk_indices_evidence_mismatch:{system_id}")
        if nwm_row.get("membership_gate_status") != "pass":
            raise ValueError(f"nwm_system_membership_gate_must_pass:{system_id}")
    if evidence["nwm_feature_membership_report"].get("sha256") != nwm_hash:
        raise ValueError("nwm_membership_evidence_hash_mismatch")


def _validate_nwm_smoke_evidence(
    payload: Mapping[str, Any], *, evidence_root: Path
) -> None:
    claim = payload.get("claim_boundary") or {}
    smoke_verified = claim.get("bounded_nwm_q_lateral_smoke_verified") is True
    evidence = payload.get("nwm_q_lateral_smoke_evidence")
    if not smoke_verified and evidence is None:
        return
    if not smoke_verified or not isinstance(evidence, Mapping):
        raise ValueError("nwm_smoke_claim_and_evidence_must_agree")
    parent_hash = evidence.get("parent_registry_sha256")
    if not isinstance(parent_hash, str) or len(parent_hash) != 64:
        raise ValueError("nwm_smoke_parent_registry_required")
    report, _ = _load_hashed_evidence(
        evidence.get("report"), evidence_root=evidence_root
    )
    if report.get("schema") != "gwm.geotransport.nwm_q_lateral_smoke_audit.v1":
        raise ValueError("nwm_smoke_report_schema_mismatch")
    if report.get("status") != "pass" or report.get("input_registry_sha256") != parent_hash:
        raise ValueError("nwm_smoke_report_parent_or_status_mismatch")
    report_claim = report.get("claim_boundary") or {}
    if (
        report_claim.get("bounded_nwm_q_lateral_value_smoke_verified") is not True
        or report_claim.get("training_or_evaluation_panel_ready") is not False
        or report_claim.get("benchmark_validated") is not False
        or report_claim.get("geospatial_kernel_validated") is not False
    ):
        raise ValueError("nwm_smoke_report_claim_boundary_invalid")
    _verify_hashed_artifact(
        report.get("extraction_manifest"), evidence_root=evidence_root
    )
    for descriptor in (report.get("artifacts") or {}).values():
        _verify_hashed_artifact(descriptor, evidence_root=evidence_root)
    spatial = report.get("spatial_selection") or {}
    system_id = spatial.get("system_id")
    by_id = {system["system_id"]: system for system in payload["systems"]}
    if system_id not in by_id:
        raise ValueError("nwm_smoke_system_missing_from_registry")
    forcing = by_id[system_id].get("forcing") or {}
    if forcing.get("feature_ids") != spatial.get("feature_ids"):
        raise ValueError("nwm_smoke_feature_ids_registry_mismatch")
    if forcing.get("q_lateral_feature_chunk_indices") != spatial.get(
        "feature_chunk_indices"
    ):
        raise ValueError("nwm_smoke_feature_chunks_registry_mismatch")


def _validate_smoke_panel_evidence(
    payload: Mapping[str, Any], *, evidence_root: Path
) -> None:
    claim = payload.get("claim_boundary") or {}
    panel_compiled = claim.get("bounded_multisource_smoke_panel_compiled") is True
    evidence = payload.get("center_hill_smoke_panel_evidence")
    if not panel_compiled and evidence is None:
        return
    if not panel_compiled or not isinstance(evidence, Mapping):
        raise ValueError("smoke_panel_claim_and_evidence_must_agree")
    parent_hash = evidence.get("parent_registry_sha256")
    if parent_hash != payload.get("parent_registry_sha256"):
        raise ValueError("smoke_panel_immediate_parent_registry_mismatch")
    report, _ = _load_hashed_evidence(
        evidence.get("report"), evidence_root=evidence_root
    )
    if report.get("schema") != "gwm.geotransport.center_hill_smoke_panel.v2":
        raise ValueError("smoke_panel_report_schema_mismatch")
    if (
        report.get("status") != "compiled_not_admitted"
        or report.get("registry_sha256") != parent_hash
    ):
        raise ValueError("smoke_panel_report_parent_or_status_mismatch")
    report_claim = report.get("claim_boundary") or {}
    if (
        report_claim.get("bounded_multisource_smoke_panel_compiled") is not True
        or report_claim.get("cwms_interval_timestamp_semantics_admitted") is not True
        or report_claim.get("linear_referenced_path_compiled") is not True
        or report_claim.get("bounded_nwm_velocity_prior_compiled") is not True
        or report_claim.get("nwm_q_lateral_partial_gauge_reach_resolved") is not False
        or report_claim.get("flood_wave_travel_time_admitted") is not False
        or report_claim.get("travel_time_or_lag_calibrated") is not False
        or report_claim.get("training_or_evaluation_panel_ready") is not False
        or report_claim.get("benchmark_validated") is not False
        or report_claim.get("geospatial_kernel_validated") is not False
    ):
        raise ValueError("smoke_panel_report_claim_boundary_invalid")
    if (
        (report.get("window") or {}).get("row_count") != 24
        or (report.get("quality_summary") or {}).get("missing_panel_value_count") != 0
        or (report.get("quality_summary") or {}).get("usgs_all_samples_approved")
        is not True
    ):
        raise ValueError("smoke_panel_report_coverage_or_quality_invalid")
    window = report.get("window") or {}
    if (
        window.get("row_support") != "[support_start_utc,support_end_utc]"
        or window.get("row_label") != "support_end_utc"
        or window.get("time_step") != "PT1H"
    ):
        raise ValueError("smoke_panel_temporal_axis_contract_invalid")
    temporal = report.get("temporal_supports") or {}
    for key in ("action_release_m3s", "inflow_context_m3s"):
        support = temporal.get(key) or {}
        if (
            support.get("schema") != "gwm.geospatial_kernel.temporal_support.v1"
            or support.get("kind") != "interval_mean"
            or support.get("duration_seconds") != 3600.0
            or support.get("timestamp_position") != "end"
            or support.get("evidence_level") != "authoritative"
        ):
            raise ValueError(f"smoke_panel_cwms_temporal_support_invalid:{key}")
    nwm_support = temporal.get("nwm_q_lateral_full_reach_overlap_sum_m3s") or {}
    if (
        nwm_support.get("schema") != "gwm.geospatial_kernel.temporal_support.v1"
        or nwm_support.get("kind") != "instantaneous"
        or nwm_support.get("duration_seconds") != 0.0
        or nwm_support.get("timestamp_position") != "instant"
    ):
        raise ValueError("smoke_panel_nwm_temporal_support_invalid")
    spatial = report.get("spatial_support") or {}
    if (
        spatial.get("full_reach_feature_count") != 27
        or spatial.get("nonzero_overlap_feature_count") != 26
        or spatial.get("zero_overlap_action_reach_excluded") is not True
        or spatial.get("partial_gauge_reach_included_as_full_reach_for_q_lateral")
        is not True
    ):
        raise ValueError("smoke_panel_spatial_support_invalid")
    for descriptor in (report.get("source_manifests") or {}).values():
        _verify_hashed_artifact(descriptor, evidence_root=evidence_root)
    for descriptor in (report.get("source_artifacts") or {}).values():
        _verify_hashed_artifact(descriptor, evidence_root=evidence_root)
    _verify_hashed_artifact(report.get("panel_artifact"), evidence_root=evidence_root)
    source_manifests = report.get("source_manifests") or {}
    companion, _ = _load_hashed_evidence(
        source_manifests.get("companion_values"), evidence_root=evidence_root
    )
    acquisition_registry_hash = evidence.get("acquisition_registry_sha256")
    if (
        not isinstance(acquisition_registry_hash, str)
        or len(acquisition_registry_hash) != 64
        or companion.get("registry_sha256") != acquisition_registry_hash
    ):
        raise ValueError("smoke_panel_acquisition_registry_lineage_mismatch")
    travel_descriptor = source_manifests.get("travel_time_prior") or {}
    registry_travel_descriptor = (
        payload.get("center_hill_travel_time_prior_evidence") or {}
    ).get("report") or {}
    if (
        travel_descriptor.get("path") != registry_travel_descriptor.get("path")
        or travel_descriptor.get("sha256") != registry_travel_descriptor.get("sha256")
    ):
        raise ValueError("smoke_panel_travel_prior_evidence_mismatch")


def _validate_travel_time_prior_evidence(
    payload: Mapping[str, Any], *, evidence_root: Path
) -> None:
    claim = payload.get("claim_boundary") or {}
    prior_compiled = claim.get("bounded_nwm_velocity_prior_compiled") is True
    evidence = payload.get("center_hill_travel_time_prior_evidence")
    if not prior_compiled and evidence is None:
        return
    if not prior_compiled or not isinstance(evidence, Mapping):
        raise ValueError("travel_time_prior_claim_and_evidence_must_agree")
    parent_hash = evidence.get("parent_registry_sha256")
    if parent_hash != payload.get("parent_registry_sha256"):
        raise ValueError("travel_time_prior_immediate_parent_registry_mismatch")
    report, _ = _load_hashed_evidence(
        evidence.get("report"), evidence_root=evidence_root
    )
    if (
        report.get("schema")
        != "gwm.geotransport.center_hill_travel_time_prior.v1"
        or report.get("status")
        != "candidate_advective_prior_not_flood_wave_lag"
        or report.get("input_registry_sha256") != parent_hash
    ):
        raise ValueError("travel_time_prior_report_parent_or_status_mismatch")
    report_claim = report.get("claim_boundary") or {}
    if (
        report_claim.get("cwms_interval_timestamp_semantics_admitted") is not True
        or report_claim.get("linear_referenced_path_compiled") is not True
        or report_claim.get("bounded_nwm_velocity_prior_compiled") is not True
        or report_claim.get("advective_residence_time_is_flood_wave_travel_time")
        is not False
        or report_claim.get("flood_wave_travel_time_admitted") is not False
        or report_claim.get("travel_time_or_lag_calibrated") is not False
        or report_claim.get("training_or_evaluation_panel_ready") is not False
        or report_claim.get("benchmark_validated") is not False
        or report_claim.get("geospatial_kernel_validated") is not False
    ):
        raise ValueError("travel_time_prior_report_claim_boundary_invalid")
    linear_path = report.get("linear_referenced_path") or {}
    effective_lengths = linear_path.get("effective_lengths_m") or []
    if (
        linear_path.get("schema")
        != "gwm.geospatial_kernel.linear_referenced_path.v1"
        or len(linear_path.get("feature_ids") or []) != 27
        or len(effective_lengths) != 27
        or effective_lengths[0] != 0.0
        or not 938.0 < float(effective_lengths[-1]) < 939.0
        or not 25_172.0 < float(linear_path.get("total_effective_length_m", 0.0)) < 25_173.0
    ):
        raise ValueError("travel_time_prior_linear_reference_invalid")
    prior = report.get("advective_travel_time_prior") or {}
    if (
        prior.get("schema") != "gwm.geospatial_kernel.travel_time_prior.v1"
        or prior.get("quantity") != "advective_residence_time"
        or prior.get("state_dependent") is not True
        or prior.get("outcome_calibrated") is not False
        or prior.get("admitted_as_flood_wave_lag") is not False
        or not 0.0 < float(prior.get("lower_seconds", 0.0))
        <= float(prior.get("central_seconds", 0.0))
        <= float(prior.get("upper_seconds", 0.0))
    ):
        raise ValueError("travel_time_prior_quantity_contract_invalid")
    velocity_window = report.get("velocity_window") or {}
    if (
        velocity_window.get("time_count") != 672
        or velocity_window.get("feature_count") != 27
        or velocity_window.get("fill_value_count") != 0
        or velocity_window.get("invalid_travel_time_hour_count") != 0
    ):
        raise ValueError("travel_time_prior_velocity_coverage_invalid")
    for descriptor in (report.get("source_artifacts") or {}).values():
        _verify_hashed_artifact(descriptor, evidence_root=evidence_root)


def _load_hashed_evidence(
    descriptor: Any, *, evidence_root: Path
) -> tuple[dict[str, Any], str]:
    body, actual_hash, relative_path = _read_hashed_artifact(
        descriptor, evidence_root=evidence_root
    )
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError(f"crosswalk_evidence_object_required:{relative_path}")
    return payload, actual_hash


def _verify_hashed_artifact(descriptor: Any, *, evidence_root: Path) -> None:
    _read_hashed_artifact(descriptor, evidence_root=evidence_root)


def _read_hashed_artifact(
    descriptor: Any, *, evidence_root: Path
) -> tuple[bytes, str, str]:
    if not isinstance(descriptor, Mapping):
        raise ValueError("crosswalk_evidence_descriptor_required")
    relative_path = descriptor.get("path")
    expected_hash = descriptor.get("sha256")
    if not isinstance(relative_path, str) or not isinstance(expected_hash, str):
        raise ValueError("crosswalk_evidence_path_and_hash_required")
    root = evidence_root.resolve()
    path = (root / relative_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("crosswalk_evidence_path_outside_root") from exc
    body = path.read_bytes()
    actual_hash = hashlib.sha256(body).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError(f"crosswalk_evidence_hash_mismatch:{relative_path}")
    return body, actual_hash, relative_path


def build_metadata_requests(
    registry: PublicDataRegistry,
    *,
    cohort: str = "minimal",
) -> tuple[AcquisitionRequest, ...]:
    requests: dict[str, AcquisitionRequest] = {}
    for system in registry.systems(cohort):
        system_id = system["system_id"]
        for field in _system_fields(system):
            source = field["source"]
            if source == "usace_cwms":
                series_id = field["series_id"]
                url = _url(
                    "https://cwms-data.usace.army.mil/cwms-data/catalog/TIMESERIES",
                    {"office": field["office"], "page-size": 10, "like": series_id},
                )
                request = AcquisitionRequest(
                    request_id=f"cwms-catalog-{_safe_id(series_id)}",
                    source=source,
                    kind="metadata",
                    url=url,
                    system_id=system_id,
                    variable_role=field["role"],
                    expected_media_type="application/json",
                )
            elif source == "usbr_rise":
                item_id = int(field["item_id"])
                request = AcquisitionRequest(
                    request_id=f"rise-catalog-item-{item_id}",
                    source=source,
                    kind="metadata",
                    url=f"https://data.usbr.gov/rise/api/catalog-item/{item_id}",
                    system_id=system_id,
                    variable_role=field["role"],
                    expected_media_type="application/ld+json",
                )
            else:
                continue
            requests.setdefault(request.request_id, request)

        action = system["action"]
        if action["source"] == "usace_cwms":
            location_id = action.get("location_id")
            if not location_id:
                raise ValueError("cwms_action_location_id_required")
            location_request = AcquisitionRequest(
                request_id=f"cwms-location-{_safe_id(location_id)}",
                source="usace_cwms",
                kind="metadata",
                url=(
                    "https://cwms-data.usace.army.mil/cwms-data/locations/"
                    f"{quote(location_id, safe='')}?{urlencode({'office': action['office']})}"
                ),
                system_id=system_id,
                variable_role="boundary_action_location",
                expected_media_type="application/json",
            )
            requests.setdefault(location_request.request_id, location_request)

        outcome = system.get("outcome")
        if outcome is not None:
            site_id = outcome["site_id"]
            site_request = AcquisitionRequest(
                request_id=f"usgs-site-{site_id}",
                source="usgs_water_data",
                kind="metadata",
                url=_url(
                    "https://waterservices.usgs.gov/nwis/site/",
                    {"format": "rdb", "sites": site_id, "siteOutput": "expanded"},
                ),
                system_id=system_id,
                variable_role="independent_observation_site",
                expected_media_type="text/tab-separated-values",
            )
            nldi_request = AcquisitionRequest(
                request_id=f"nldi-link-{site_id}",
                source="usgs_nldi",
                kind="metadata",
                url=f"https://api.water.usgs.gov/nldi/linked-data/nwissite/USGS-{site_id}",
                system_id=system_id,
                variable_role="topology_evidence",
                expected_media_type="application/geo+json",
            )
            requests.setdefault(site_request.request_id, site_request)
            requests.setdefault(nldi_request.request_id, nldi_request)

        if system.get("forcing") is not None:
            for suffix in (".zarray", ".zattrs"):
                request_id = f"nwm-q-lateral-{suffix[1:]}"
                requests.setdefault(
                    request_id,
                    AcquisitionRequest(
                        request_id=request_id,
                        source="noaa_nwm_v3_retrospective",
                        kind="metadata",
                        url=(
                            "https://noaa-nwm-retrospective-3-0-pds.s3.amazonaws.com/"
                            f"CONUS/zarr/chrtout.zarr/q_lateral/{suffix}"
                        ),
                        system_id=None,
                        variable_role="modeled_forcing_schema",
                        expected_media_type="application/json",
                    ),
                )
            for coordinate in ("feature_id", "time"):
                for suffix in (".zarray", ".zattrs"):
                    request_id = f"nwm-{coordinate.replace('_', '-')}-{suffix[1:]}"
                    requests.setdefault(
                        request_id,
                        AcquisitionRequest(
                            request_id=request_id,
                            source="noaa_nwm_v3_retrospective",
                            kind="metadata",
                            url=(
                                "https://noaa-nwm-retrospective-3-0-pds.s3.amazonaws.com/"
                                f"CONUS/zarr/chrtout.zarr/{coordinate}/{suffix}"
                            ),
                            system_id=None,
                            variable_role=f"modeled_forcing_{coordinate}_schema",
                            expected_media_type="application/json",
                        ),
                    )
    return tuple(requests.values())


def build_value_requests(
    registry: PublicDataRegistry,
    *,
    start: str,
    end: str,
    cohort: str = "minimal",
    system_ids: Iterable[str] | None = None,
    nwm_extraction_manifest: Mapping[str, Any] | None = None,
) -> tuple[AcquisitionRequest, ...]:
    """Build bounded requests; never emits an unbounded RISE query.

    NWM Zarr values require a verified reach-path ``feature_id`` crosswalk and
    a separate chunk extractor.  With the default fail-closed setting,
    transport requests are rejected until those IDs exist.
    """

    start_at = _parse_utc(start)
    end_at = _parse_utc(end)
    if start_at >= end_at:
        raise ValueError("acquisition_interval_invalid")
    selected_ids = None if system_ids is None else set(system_ids)
    selected = tuple(
        system
        for system in registry.systems(cohort)
        if selected_ids is None or system["system_id"] in selected_ids
    )
    if selected_ids is not None and {system["system_id"] for system in selected} != selected_ids:
        raise ValueError("unknown_selected_system")

    requests: list[AcquisitionRequest] = []
    for system in selected:
        window_start, window_end = map(_parse_utc, system["study_window"])
        if start_at < window_start or end_at > window_end:
            raise ValueError("acquisition_outside_frozen_study_window")
        forcing = system.get("forcing")
        if forcing is not None and not forcing.get("feature_ids"):
            raise ValueError(
                f"nwm_feature_crosswalk_required:{system['system_id']}"
            )
        if forcing is not None:
            if nwm_extraction_manifest is None:
                raise ValueError(
                    f"nwm_values_require_dedicated_extractor:{system['system_id']}"
                )
            _validate_nwm_extraction_coverage(
                registry,
                system,
                start=start_at,
                end=end_at,
                manifest=nwm_extraction_manifest,
            )
        chunk_days = 31 if system["track"] == "GeoTransport-H" else 366
        for chunk_start, chunk_end in _chunks(start_at, end_at, chunk_days):
            requests.extend(_system_value_requests(system, chunk_start, chunk_end))
    return tuple(requests)


def _validate_nwm_extraction_coverage(
    registry: PublicDataRegistry,
    system: Mapping[str, Any],
    *,
    start: datetime,
    end: datetime,
    manifest: Mapping[str, Any],
) -> None:
    if (
        manifest.get("schema")
        == "gwm.geotransport.center_hill_evaluation_nwm.v1"
    ):
        _validate_center_hill_evaluation_nwm_coverage(
            registry,
            system,
            start=start,
            end=end,
            manifest=manifest,
        )
        return
    if (
        manifest.get("schema") != "gwm.geotransport.nwm_q_lateral_extract.v1"
        or manifest.get("mode") != "values"
    ):
        raise ValueError("nwm_values_manifest_required")
    smoke_evidence = registry.payload.get("nwm_q_lateral_smoke_evidence") or {}
    admitted_hashes = {
        registry.sha256,
        smoke_evidence.get("parent_registry_sha256"),
    }
    if manifest.get("registry_sha256") not in admitted_hashes:
        raise ValueError("nwm_values_manifest_registry_lineage_mismatch")
    semantics = manifest.get("source_semantics") or {}
    if (
        semantics.get("source") != "noaa_nwm_v3_retrospective"
        or semantics.get("variable") != "q_lateral"
        or semantics.get("role") != "modeled_forcing"
        or semantics.get("modeled") is not True
        or semantics.get("ground_truth") is not False
        or semantics.get("streamflow_used") is not False
    ):
        raise ValueError("nwm_values_manifest_semantics_invalid")
    claim = manifest.get("claim_boundary") or {}
    if claim.get("modeled_forcing_values_acquired") is not True:
        raise ValueError("nwm_modeled_forcing_values_not_acquired")
    manifest_start = _parse_utc(str(manifest.get("start_inclusive")))
    manifest_end = _parse_utc(str(manifest.get("end_exclusive")))
    if manifest_start > start or manifest_end < end:
        raise ValueError(f"nwm_values_manifest_window_mismatch:{system['system_id']}")
    by_id = {
        row.get("system_id"): row for row in manifest.get("systems", [])
    }
    row = by_id.get(system["system_id"])
    if row is None:
        raise ValueError(f"nwm_values_manifest_system_missing:{system['system_id']}")
    forcing = system["forcing"]
    if row.get("feature_ids") != forcing.get("feature_ids"):
        raise ValueError(f"nwm_values_manifest_feature_ids_mismatch:{system['system_id']}")
    if row.get("feature_indices") != forcing.get("feature_indices"):
        raise ValueError(
            f"nwm_values_manifest_feature_indices_mismatch:{system['system_id']}"
        )
    if row.get("feature_chunk_indices") != forcing.get(
        "q_lateral_feature_chunk_indices"
    ):
        raise ValueError(f"nwm_values_manifest_chunks_mismatch:{system['system_id']}")


def _validate_center_hill_evaluation_nwm_coverage(
    registry: PublicDataRegistry,
    system: Mapping[str, Any],
    *,
    start: datetime,
    end: datetime,
    manifest: Mapping[str, Any],
) -> None:
    window = manifest.get("window") or {}
    result = manifest.get("result") or {}
    claims = manifest.get("claim_boundary") or {}
    protocol = manifest.get("evaluation_protocol") or {}
    registry_artifact = manifest.get("registry") or {}
    semantics = manifest.get("source_semantics") or {}
    requests = manifest.get("requests") or []
    if (
        system.get("system_id") != "center_hill"
        or manifest.get("mode") != "values"
        or manifest.get("system_id") != "center_hill"
        or registry_artifact.get("sha256") != registry.sha256
        or protocol.get("path")
        != "benchmarks/geotransport_v0_1/center_hill_temporal_holdout_protocol_v1.json"
        or not isinstance(protocol.get("sha256"), str)
        or len(protocol["sha256"]) != 64
        or protocol.get("size_bytes", 0) <= 0
    ):
        raise ValueError("evaluation_nwm_values_manifest_lineage_invalid")
    if (
        _parse_utc(str(window.get("start_inclusive"))) != start
        or _parse_utc(str(window.get("end_exclusive"))) != end
        or window.get("time_count") != 672
    ):
        raise ValueError("evaluation_nwm_values_manifest_window_mismatch")
    forcing = system.get("forcing") or {}
    if (
        manifest.get("feature_ids") != forcing.get("feature_ids")
        or manifest.get("feature_indices") != forcing.get("feature_indices")
    ):
        raise ValueError("evaluation_nwm_values_manifest_feature_axis_mismatch")
    nwm_root = (
        "https://noaa-nwm-retrospective-3-0-pds.s3.amazonaws.com/"
        "CONUS/zarr/chrtout.zarr"
    )
    expected_urls = {
        f"{nwm_root}/time/560",
        f"{nwm_root}/q_lateral/560.63",
        f"{nwm_root}/velocity/560.63",
    }
    if (
        len(requests) != 3
        or {row.get("url") for row in requests} != expected_urls
        or {row.get("variable") for row in requests}
        != {"time", "q_lateral", "velocity"}
    ):
        raise ValueError("evaluation_nwm_values_manifest_request_scope_invalid")
    q_semantics = semantics.get("q_lateral") or {}
    velocity_semantics = semantics.get("velocity") or {}
    if (
        q_semantics.get("role") != "modeled_forcing"
        or q_semantics.get("ground_truth") is not False
        or q_semantics.get("units") != "m3 s-1"
        or velocity_semantics.get("role") != "modeled_state_context"
        or velocity_semantics.get("ground_truth") is not False
        or velocity_semantics.get("units") != "m s-1"
        or velocity_semantics.get("admitted_as_flood_wave_celerity") is not False
    ):
        raise ValueError("evaluation_nwm_values_manifest_semantics_invalid")
    if (
        result.get("time_count") != 672
        or result.get("feature_count") != len(forcing.get("feature_ids") or [])
        or result.get("q_lateral_value_count") != 18_144
        or result.get("velocity_value_count") != 18_144
        or result.get("q_lateral_fill_value_count") != 0
        or result.get("velocity_fill_value_count") != 0
        or claims.get("modeled_inputs_acquired") is not True
        or claims.get("evaluation_outcome_acquired") is not False
        or claims.get("evaluation_scored") is not False
    ):
        raise ValueError("evaluation_nwm_values_manifest_result_invalid")


def _system_fields(system: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    return (system["action"], *system["state_context"])


def _system_value_requests(
    system: Mapping[str, Any],
    start: datetime,
    end: datetime,
) -> list[AcquisitionRequest]:
    system_id = system["system_id"]
    stamp = f"{start:%Y%m%dT%H%M%SZ}-{end:%Y%m%dT%H%M%SZ}"
    result: list[AcquisitionRequest] = []
    for field in _system_fields(system):
        source = field["source"]
        if source == "usace_cwms":
            result.append(
                AcquisitionRequest(
                    request_id=f"{system_id}-{_safe_id(field['series_id'])}-{stamp}",
                    source=source,
                    kind="values",
                    url=_url(
                        "https://cwms-data.usace.army.mil/cwms-data/timeseries",
                        {
                            "name": field["series_id"],
                            "office": field["office"],
                            "begin": _iso(start),
                            "end": _iso(end),
                            "unit": field["native_unit"],
                            "page-size": 50000,
                        },
                    ),
                    system_id=system_id,
                    variable_role=field["role"],
                    expected_media_type="application/json",
                )
            )
        elif source == "usbr_rise":
            result.append(
                AcquisitionRequest(
                    request_id=f"{system_id}-rise-{field['item_id']}-{stamp}",
                    source=source,
                    kind="values",
                    url=_url(
                        "https://data.usbr.gov/rise/api/result",
                        {
                            "itemId": field["item_id"],
                            "dateTime[after]": _iso(start),
                            "dateTime[before]": _iso(end),
                        },
                    ),
                    system_id=system_id,
                    variable_role=field["role"],
                    expected_media_type="application/json",
                    paginated=True,
                )
            )
    outcome = system.get("outcome")
    if outcome is not None:
        service = outcome["service"]
        outcome_start = start - timedelta(hours=1) if service == "iv" else start
        outcome_end = end + timedelta(hours=1) if service == "iv" else end
        result.append(
            AcquisitionRequest(
                request_id=f"{system_id}-usgs-{service}-{stamp}",
                source="usgs_water_data",
                kind="values",
                url=_url(
                    f"https://waterservices.usgs.gov/nwis/{service}/",
                    {
                        "format": "json",
                        "sites": outcome["site_id"],
                        "parameterCd": outcome["parameter_code"],
                        "startDT": _iso(outcome_start),
                        "endDT": _iso(outcome_end),
                        "siteStatus": "all",
                    },
                ),
                system_id=system_id,
                variable_role="independent_observation",
                expected_media_type="application/json",
            )
        )
    return result


def _chunks(start: datetime, end: datetime, days: int) -> Iterable[tuple[datetime, datetime]]:
    cursor = start
    delta = timedelta(days=days)
    while cursor < end:
        boundary = min(cursor + delta, end)
        yield cursor, boundary
        cursor = boundary


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone_aware_timestamp_required")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _url(root: str, params: Mapping[str, object]) -> str:
    return f"{root}?{urlencode(params)}"


def _safe_id(value: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in value).strip("-")
