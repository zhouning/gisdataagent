#!/usr/bin/env python3
"""Compile the J. Percy Priest dam-to-gauge full incremental reach DAG."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from data_agent.uwm.geospatial_kernel_v2 import (
    DEFAULT_REGISTRY_PATH,
    DirectedReachNetwork,
    LinearReferencedPath,
    load_public_data_registry,
)

if __package__:
    from scripts.acquire_geotransport_center_hill_route_link_v3 import (
        ARCHIVE_URL,
        OPTIONAL_FIELDS,
        REQUIRED_FIELDS,
        _artifact as _route_link_artifact,
        _audit_subset,
        _route_link_reader,
        _write_subset,
    )
    from scripts.build_geotransport_center_hill_travel_time_prior import (
        geometry_length_m,
        orient_path_lines,
        project_point_to_line,
    )
    from scripts.compile_geotransport_center_hill_v2_d5_full_subnetwork import (
        NWM_FEATURE_CHUNK_SIZE,
        ROUTE_LINK_ARCHIVE_SHA256,
        ROUTE_LINK_MEMBER_PATH,
        ROUTE_LINK_MEMBER_SHA256,
        ROUTE_LINK_MEMBER_SIZE,
        _nwm_feature_indices,
        _select_parameters,
        _source_indices,
        _write_crosswalk,
        compile_upstream_domain,
    )
else:
    from acquire_geotransport_center_hill_route_link_v3 import (
        ARCHIVE_URL,
        OPTIONAL_FIELDS,
        REQUIRED_FIELDS,
        _artifact as _route_link_artifact,
        _audit_subset,
        _route_link_reader,
        _write_subset,
    )
    from build_geotransport_center_hill_travel_time_prior import (
        geometry_length_m,
        orient_path_lines,
        project_point_to_line,
    )
    from compile_geotransport_center_hill_v2_d5_full_subnetwork import (
        NWM_FEATURE_CHUNK_SIZE,
        ROUTE_LINK_ARCHIVE_SHA256,
        ROUTE_LINK_MEMBER_PATH,
        ROUTE_LINK_MEMBER_SHA256,
        ROUTE_LINK_MEMBER_SIZE,
        _nwm_feature_indices,
        _select_parameters,
        _source_indices,
        _write_crosswalk,
        compile_upstream_domain,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROUTE_LINK = Path("/private/tmp/RouteLink_CONUS.nc")
DEFAULT_NLDI_REPORT = (
    REPO_ROOT / "benchmarks/geotransport_v0_1/nldi_path_crosswalk_report.json"
)
DEFAULT_MEMBERSHIP_REPORT = (
    REPO_ROOT / "benchmarks/geotransport_v0_1/nwm_feature_membership_report.json"
)
DEFAULT_NAVIGATION = REPO_ROOT / (
    "data/geotransport_v0_1/topology/raw/"
    "j_percy_priest-downstream-flowlines.json"
)
DEFAULT_GAUGE = (
    REPO_ROOT / "data/geotransport_v0_1/metadata/nldi-link-03430200.json"
)
DEFAULT_FEATURE_ARRAY = REPO_ROOT / (
    "data/geotransport_v0_1/metadata/nwm-feature-id-zarray.json"
)
DEFAULT_FEATURE_CHUNK = REPO_ROOT / (
    "data/geotransport_v0_1/nwm/feature_id/0.zst"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/j_percy_priest_v1_full_subnetwork"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "j_percy_priest_v1_full_subnetwork_report.json"
)
SCHEMA = "gwm.geotransport.j_percy_priest_v1_full_subnetwork.v1"
SYSTEM_ID = "j_percy_priest"
FULL_PATH_FEATURE_IDS = (
    18_401_827,
    18_401_881,
    18_401_817,
    18_401_509,
    18_401_503,
    18_401_497,
)
CONTROL_FEATURE_ID = FULL_PATH_FEATURE_IDS[0]
ACTIVE_MAINSTEM_FEATURE_IDS = FULL_PATH_FEATURE_IDS[1:]
ACTION_ENTRY_FEATURE_ID = ACTIVE_MAINSTEM_FEATURE_IDS[0]
OUTLET_FEATURE_ID = ACTIVE_MAINSTEM_FEATURE_IDS[-1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-link", type=Path, default=DEFAULT_ROUTE_LINK)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--nldi-report", type=Path, default=DEFAULT_NLDI_REPORT)
    parser.add_argument(
        "--membership-report", type=Path, default=DEFAULT_MEMBERSHIP_REPORT
    )
    parser.add_argument("--navigation", type=Path, default=DEFAULT_NAVIGATION)
    parser.add_argument("--gauge", type=Path, default=DEFAULT_GAUGE)
    parser.add_argument("--feature-array", type=Path, default=DEFAULT_FEATURE_ARRAY)
    parser.add_argument("--feature-chunk", type=Path, default=DEFAULT_FEATURE_CHUNK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_subnetwork(
    *,
    route_link_path: Path = DEFAULT_ROUTE_LINK,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    nldi_report_path: Path = DEFAULT_NLDI_REPORT,
    membership_report_path: Path = DEFAULT_MEMBERSHIP_REPORT,
    navigation_path: Path = DEFAULT_NAVIGATION,
    gauge_path: Path = DEFAULT_GAUGE,
    feature_array_path: Path = DEFAULT_FEATURE_ARRAY,
    feature_chunk_path: Path = DEFAULT_FEATURE_CHUNK,
    output_root: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc)
    if route_link_path.stat().st_size != ROUTE_LINK_MEMBER_SIZE:
        raise ValueError("j_percy_priest_route_link_size_mismatch")
    route_link_sha256 = _sha256_path(route_link_path)
    if route_link_sha256 != ROUTE_LINK_MEMBER_SHA256:
        raise ValueError("j_percy_priest_route_link_sha256_mismatch")

    registry = load_public_data_registry(registry_path)
    system = next(
        row for row in registry.payload["systems"] if row["system_id"] == SYSTEM_ID
    )
    nldi_body, nldi_report = _load_json(nldi_report_path)
    membership_body, membership_report = _load_json(membership_report_path)
    navigation_body, navigation = _load_json(navigation_path)
    gauge_body, gauge = _load_json(gauge_path)
    nldi_row = _system_row(nldi_report, SYSTEM_ID)
    membership_row = _system_row(membership_report, SYSTEM_ID)
    _validate_public_crosswalks(system, nldi_row, membership_row)
    mainstem_path, path_diagnostics = build_active_mainstem(
        nldi_row=nldi_row,
        navigation=navigation,
        gauge=gauge,
        provenance_id=f"nldi-path-report:{hashlib.sha256(nldi_body).hexdigest()}",
    )

    with _route_link_reader(route_link_path) as reader:
        missing_fields = [
            name for name in REQUIRED_FIELDS if name not in reader.variable_names()
        ]
        if missing_fields:
            raise ValueError(
                "j_percy_priest_route_link_required_fields_missing:"
                + ",".join(missing_fields)
            )
        source_links = np.asarray(reader.values("link"), dtype=np.int64).reshape(-1)
        source_to = np.asarray(reader.values("to"), dtype=np.int64).reshape(-1)
        mouths, receiving_by_mouth = derive_direct_branch_mouths(
            source_links=source_links,
            source_to=source_to,
            active_mainstem_ids=ACTIVE_MAINSTEM_FEATURE_IDS,
            excluded_control_ids=(CONTROL_FEATURE_ID,),
        )
        feature_ids, downstream_ids, branch_memberships = compile_upstream_domain(
            source_links=source_links,
            source_to=source_to,
            branch_mouth_ids=mouths,
            active_mainstem_ids=ACTIVE_MAINSTEM_FEATURE_IDS,
            expected_receiving_by_mouth=receiving_by_mouth,
            forbidden_feature_ids=(CONTROL_FEATURE_ID,),
            outlet_feature_id=OUTLET_FEATURE_ID,
        )
        indices = _source_indices(source_links, feature_ids)
        subset_values, variable_attributes, field_audit = _select_parameters(
            reader,
            indices=indices,
            expected_feature_ids=feature_ids,
        )
        source_global_attributes = reader.global_attributes()

    downstream = dict(zip(feature_ids, downstream_ids, strict=True))
    expected_mainstem_downstream = dict(
        zip(
            ACTIVE_MAINSTEM_FEATURE_IDS,
            ACTIVE_MAINSTEM_FEATURE_IDS[1:] + (None,),
            strict=True,
        )
    )
    if any(
        downstream[feature] != target
        for feature, target in expected_mainstem_downstream.items()
    ):
        raise ValueError("j_percy_priest_mainstem_downstream_mismatch")

    path_full = dict(
        zip(mainstem_path.feature_ids, mainstem_path.full_lengths_m, strict=True)
    )
    path_effective = dict(
        zip(mainstem_path.feature_ids, mainstem_path.effective_lengths_m, strict=True)
    )
    full_lengths = tuple(
        path_full.get(feature, float(length))
        for feature, length in zip(
            feature_ids, subset_values["Length"], strict=True
        )
    )
    effective_lengths = tuple(
        path_effective.get(feature, full)
        for feature, full in zip(feature_ids, full_lengths, strict=True)
    )
    network = DirectedReachNetwork(
        network_id="j-percy-priest:dam-to-gauge:full-incremental-subnetwork-v1",
        feature_ids=feature_ids,
        downstream_feature_ids=downstream_ids,
        full_lengths_m=full_lengths,
        effective_lengths_m=effective_lengths,
        action_entry_feature_ids=(ACTION_ENTRY_FEATURE_ID,),
        provenance_id=(
            f"nwm-v3-routelink:{route_link_sha256}|"
            f"nldi-path:{hashlib.sha256(nldi_body).hexdigest()}"
        ),
        evidence_level="derived",
        admitted=True,
    )
    axis_position = {feature: index for index, feature in enumerate(feature_ids)}
    if any(
        target is not None and axis_position[source] >= axis_position[target]
        for source, target in zip(feature_ids, downstream_ids, strict=True)
    ):
        raise RuntimeError("j_percy_priest_feature_axis_not_topological")

    feature_indices, feature_axis_count = _nwm_feature_indices(
        feature_ids,
        array_path=feature_array_path,
        chunk_path=feature_chunk_path,
    )
    feature_chunks = tuple(
        sorted({index // NWM_FEATURE_CHUNK_SIZE for index in feature_indices})
    )
    output_root.mkdir(parents=True, exist_ok=True)
    subset_path = output_root / "RouteLink_CONUS_NWMv3_JPercyPriest_V1.nc"
    _write_subset(
        subset_path,
        subset_values=subset_values,
        variable_attributes=variable_attributes,
        source_global_attributes=source_global_attributes,
        source_member_path=ROUTE_LINK_MEMBER_PATH,
        source_member_sha256=route_link_sha256,
        source_archive_sha256=ROUTE_LINK_ARCHIVE_SHA256,
        generated_at=generated_at,
        history_subject="J. Percy Priest v1 full incremental subnetwork",
        subset_semantics="selected source rows in deterministic topological order",
    )
    subset_audit = _audit_subset(
        subset_path, expected_feature_ids=feature_ids
    )
    network_path = output_root / "full_subnetwork.json"
    _write_json(
        network_path,
        {
            "network": network.as_dict(),
            "linear_referenced_mainstem": mainstem_path.as_dict(),
            "direct_branch_attachments": [
                {
                    "tributary_mouth_feature_id": mouth,
                    "receiving_mainstem_feature_id": receiving_by_mouth[mouth],
                    "upstream_network_compiled": True,
                }
                for mouth in mouths
            ],
            "action_boundary": {
                "control_feature_id": CONTROL_FEATURE_ID,
                "control_feature_in_state_domain": False,
                "action_entry_feature_id": ACTION_ENTRY_FEATURE_ID,
                "semantics": "release_enters_first_complete_downstream_reach",
            },
        },
    )
    crosswalk_path = output_root / "nwm_feature_crosswalk.csv"
    _write_crosswalk(crosswalk_path, feature_ids, feature_indices)

    branch_features = set(feature_ids) - set(ACTIVE_MAINSTEM_FEATURE_IDS)
    return {
        "schema": SCHEMA,
        "generated_at": generated_at.isoformat(),
        "status": "pass_full_incremental_subnetwork_compiled",
        "data_isolation": {
            "outcome_values_loaded": False,
            "outcome_artifacts_read": False,
            "topology_and_parameter_sources_only": True,
        },
        "source": {
            "publisher": "NOAA National Water Center / Office of Water Prediction",
            "parameter_release": "NWM v3.0",
            "archive_url": ARCHIVE_URL,
            "archive_sha256": ROUTE_LINK_ARCHIVE_SHA256,
            "route_link_member_path": ROUTE_LINK_MEMBER_PATH,
            "route_link_member_size_bytes": ROUTE_LINK_MEMBER_SIZE,
            "route_link_member_sha256": route_link_sha256,
            "route_link_source_feature_count": int(source_links.size),
            "route_link_source_global_attributes": source_global_attributes,
        },
        "linear_reference": {
            **path_diagnostics,
            "control_feature_excluded": True,
            "first_active_reach_is_complete": True,
            "terminal_reach_trimmed_at_gauge": True,
        },
        "domain": {
            "feature_count": len(feature_ids),
            "active_mainstem_feature_count": len(ACTIVE_MAINSTEM_FEATURE_IDS),
            "incremental_branch_feature_count": len(branch_features),
            "direct_tributary_mouth_count": len(mouths),
            "direct_tributary_mouth_feature_ids": list(mouths),
            "source_reach_count": len(network.source_feature_ids),
            "internal_confluence_reach_count": len(network.confluence_feature_ids),
            "control_feature_id": CONTROL_FEATURE_ID,
            "action_entry_feature_id": ACTION_ENTRY_FEATURE_ID,
            "outlet_feature_id": OUTLET_FEATURE_ID,
            "full_length_km": float(sum(full_lengths) / 1000.0),
            "effective_length_km": float(sum(effective_lengths) / 1000.0),
            "branch_feature_count_by_direct_mouth": {
                str(mouth): len(branch_memberships[mouth]) for mouth in mouths
            },
        },
        "topology": {
            "method": (
                "direct off-mainstem parent discovery followed by reverse traversal "
                "of official NWM v3 RouteLink link-to topology"
            ),
            "feature_axis_order": "deterministic_Kahn_topological_order",
            "full_upstream_tributary_subnetworks_compiled": True,
            "controlled_upstream_feature_excluded": True,
            "one_outlet": True,
            "acyclic": True,
            "all_downstream_targets_internal_or_outlet": True,
        },
        "nwm_crosswalk": {
            "source_feature_axis_count": feature_axis_count,
            "covered_feature_count": len(feature_indices),
            "coverage_complete": True,
            "feature_chunk_size": NWM_FEATURE_CHUNK_SIZE,
            "feature_chunk_indices": list(feature_chunks),
            "required_chunk_count_per_time_chunk_and_variable": len(feature_chunks),
        },
        "parameters": {
            "required_fields": list(REQUIRED_FIELDS),
            "optional_fields_selected": [
                name for name in OPTIONAL_FIELDS if name in subset_values
            ],
            "field_audit": field_audit,
            "no_default_parameter_substitution": True,
        },
        "artifacts": {
            "registry": _artifact(registry_path, registry_path.read_bytes()),
            "nldi_path_report": _artifact(nldi_report_path, nldi_body),
            "nwm_membership_report": _artifact(
                membership_report_path, membership_body
            ),
            "navigation": _artifact(navigation_path, navigation_body),
            "gauge": _artifact(gauge_path, gauge_body),
            "full_subnetwork": _artifact(network_path, network_path.read_bytes()),
            "route_link_subset": {
                **_route_link_artifact(subset_path, subset_path.read_bytes()),
                "audit": subset_audit,
            },
            "nwm_feature_crosswalk": _artifact(
                crosswalk_path, crosswalk_path.read_bytes()
            ),
            "nwm_feature_axis": _artifact(
                feature_chunk_path, feature_chunk_path.read_bytes()
            ),
        },
        "gates": {
            "official_route_link_identity_verified": True,
            "public_mainstem_crosswalk_verified": True,
            "all_upstream_ancestors_compiled": True,
            "controlled_upstream_feature_absent": CONTROL_FEATURE_ID not in feature_ids,
            "directed_network_contract_admitted": True,
            "route_link_parameter_coverage_complete": True,
            "nwm_retrospective_feature_coverage_complete": True,
            "initial_state_acquired": False,
            "distributed_q_lateral_acquired": False,
            "outcome_free_rollout_sealed": False,
        },
        "claim_boundary": {
            "public_data_acquired_without_user_supplied_data": True,
            "complete_incremental_topology_available": True,
            "complete_route_link_parameters_available": True,
            "full_subnetwork_routing_ready": False,
            "outcome_values_acquired": False,
            "predictive_validation_complete": False,
            "geospatial_kernel_validated": False,
        },
    }


def derive_direct_branch_mouths(
    *,
    source_links: np.ndarray,
    source_to: np.ndarray,
    active_mainstem_ids: tuple[int, ...],
    excluded_control_ids: tuple[int, ...],
) -> tuple[tuple[int, ...], dict[int, int]]:
    links = np.asarray(source_links, dtype=np.int64).reshape(-1)
    targets = np.asarray(source_to, dtype=np.int64).reshape(-1)
    if links.size == 0 or links.shape != targets.shape:
        raise ValueError("j_percy_priest_route_link_axis_invalid")
    active = set(active_mainstem_ids)
    excluded = set(excluded_control_ids)
    selected = [
        (int(source), int(target))
        for source, target in zip(links, targets, strict=True)
        if int(target) in active
        and int(source) not in active
        and int(source) not in excluded
    ]
    selected.sort()
    mouths = tuple(source for source, _ in selected)
    if not mouths or len(mouths) != len(set(mouths)):
        raise ValueError("j_percy_priest_direct_branch_mouth_axis_invalid")
    return mouths, dict(selected)


def build_active_mainstem(
    *,
    nldi_row: Mapping[str, Any],
    navigation: Mapping[str, Any],
    gauge: Mapping[str, Any],
    provenance_id: str,
) -> tuple[LinearReferencedPath, dict[str, Any]]:
    reported_ids = tuple(int(value) for value in nldi_row["path"]["feature_ids"])
    if reported_ids != FULL_PATH_FEATURE_IDS:
        raise ValueError("j_percy_priest_nldi_path_mismatch")
    by_id = {
        int(feature["properties"]["nhdplus_comid"]): feature
        for feature in navigation.get("features") or []
    }
    if not set(FULL_PATH_FEATURE_IDS) <= set(by_id):
        raise ValueError("j_percy_priest_navigation_feature_missing")
    raw_lines = [
        by_id[feature]["geometry"]["coordinates"]
        for feature in FULL_PATH_FEATURE_IDS
    ]
    lines, orientations, gaps = orient_path_lines(raw_lines)
    lengths = tuple(geometry_length_m(line) for line in lines)
    reported_length_m = float(nldi_row["path"]["full_reach_path_length_km"]) * 1000.0
    if abs(sum(lengths) - reported_length_m) > 5.0:
        raise ValueError("j_percy_priest_full_path_length_reproduction_mismatch")
    gauge_features = gauge.get("features") or []
    if len(gauge_features) != 1 or gauge_features[0]["geometry"]["type"] != "Point":
        raise ValueError("j_percy_priest_gauge_point_required")
    gauge_point = tuple(
        float(value) for value in gauge_features[0]["geometry"]["coordinates"]
    )
    gauge_snap_m, gauge_measure_m = project_point_to_line(gauge_point, lines[-1])
    if gauge_snap_m > 100.0:
        raise ValueError("j_percy_priest_gauge_snap_exceeds_100m")
    active_lengths = lengths[1:]
    exits = list(active_lengths)
    exits[-1] = min(active_lengths[-1], gauge_measure_m)
    path = LinearReferencedPath(
        path_id="j_percy_priest:JPPT1-J_PERCY_PRIEST:USGS-03430200",
        feature_ids=ACTIVE_MAINSTEM_FEATURE_IDS,
        full_lengths_m=active_lengths,
        entry_offsets_m=(0.0,) * len(ACTIVE_MAINSTEM_FEATURE_IDS),
        exit_offsets_m=tuple(exits),
        provenance_id=provenance_id,
        evidence_level="derived",
    )
    return path, {
        "reported_full_path_length_m": reported_length_m,
        "reproduced_full_path_length_m": float(sum(lengths)),
        "excluded_control_reach_full_length_m": float(lengths[0]),
        "active_mainstem_full_length_m": float(sum(active_lengths)),
        "active_mainstem_effective_length_m": path.total_effective_length_m,
        "gauge_snap_distance_m": gauge_snap_m,
        "gauge_measure_from_terminal_reach_start_m": gauge_measure_m,
        "maximum_connection_gap_m": max(gaps, default=0.0),
        "orientation_by_feature": [
            {"feature_id": feature, "coordinate_order": orientation}
            for feature, orientation in zip(
                FULL_PATH_FEATURE_IDS, orientations, strict=True
            )
        ],
    }


def _validate_public_crosswalks(
    system: Mapping[str, Any],
    nldi_row: Mapping[str, Any],
    membership_row: Mapping[str, Any],
) -> None:
    registry_ids = tuple(int(value) for value in system["forcing"]["feature_ids"])
    path_ids = tuple(int(value) for value in nldi_row["path"]["feature_ids"])
    membership_ids = tuple(int(value) for value in membership_row["feature_ids"])
    if (
        registry_ids != FULL_PATH_FEATURE_IDS
        or path_ids != FULL_PATH_FEATURE_IDS
        or membership_ids != FULL_PATH_FEATURE_IDS
        or nldi_row.get("topology_gate_status") != "pass"
        or membership_row.get("membership_gate_status") != "pass"
        or membership_row.get("missing_feature_ids") != []
    ):
        raise ValueError("j_percy_priest_public_crosswalk_invalid")


def _system_row(payload: Mapping[str, Any], system_id: str) -> Mapping[str, Any]:
    return next(row for row in payload["systems"] if row["system_id"] == system_id)


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    return body, json.loads(body)


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": _display(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    report = compile_subnetwork(
        route_link_path=args.route_link,
        registry_path=args.registry,
        nldi_report_path=args.nldi_report,
        membership_report_path=args.membership_report,
        navigation_path=args.navigation,
        gauge_path=args.gauge,
        feature_array_path=args.feature_array,
        feature_chunk_path=args.feature_chunk,
        output_root=args.output,
    )
    _write_json(args.report, report)
    print(args.report)
    print(f"feature_count={report['domain']['feature_count']}")
    print(
        "incremental_branch_feature_count="
        f"{report['domain']['incremental_branch_feature_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
