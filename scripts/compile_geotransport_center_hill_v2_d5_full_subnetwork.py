#!/usr/bin/env python3
"""Compile the complete Center Hill incremental tributary DAG from NWM RouteLink."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import heapq
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, Iterable, Mapping

import numpy as np

from data_agent.uwm.geospatial_kernel_v2 import (
    DirectedReachNetwork,
    TributaryConfluence,
)

if __package__:
    from scripts.acquire_geotransport_center_hill_route_link_v3 import (
        ARCHIVE_URL,
        OPTIONAL_FIELDS,
        POSITIVE_PARAMETER_FIELDS,
        REQUIRED_FIELDS,
        _artifact as _route_link_artifact,
        _audit_subset,
        _route_link_reader,
        _write_subset,
    )
else:
    from acquire_geotransport_center_hill_route_link_v3 import (
        ARCHIVE_URL,
        OPTIONAL_FIELDS,
        POSITIVE_PARAMETER_FIELDS,
        REQUIRED_FIELDS,
        _artifact as _route_link_artifact,
        _audit_subset,
        _route_link_reader,
        _write_subset,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROUTE_LINK = Path("/private/tmp/RouteLink_CONUS.nc")
DEFAULT_D4_NETWORK = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_v2_d4_topology/"
    "branching_boundary_network.json"
)
DEFAULT_D4_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_v2_d4_topology_report.json"
)
DEFAULT_FEATURE_ARRAY = REPO_ROOT / (
    "data/geotransport_v0_1/metadata/nwm-feature-id-zarray.json"
)
DEFAULT_FEATURE_CHUNK = REPO_ROOT / (
    "data/geotransport_v0_1/nwm/feature_id/0.zst"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_v2_d5_full_subnetwork"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_v2_d5_full_subnetwork_report.json"
)
SCHEMA = "gwm.geotransport.center_hill_v2_d5_full_subnetwork.v1"
ROUTE_LINK_MEMBER_PATH = "v3.0_par/RouteLink_CONUS.nc"
ROUTE_LINK_MEMBER_SIZE = 269_363_375
ROUTE_LINK_MEMBER_SHA256 = (
    "e34e58c875e25b93e6692a286ef7004ff59e86ee48435c5a5e0dfa95d2ccb5f4"
)
ROUTE_LINK_ARCHIVE_SHA256 = (
    "1d8a7e1eb506ec38a2ff0de64b1b5ebc7472205e0d660ee28080a9e15b6ce38c"
)
ACTION_ENTRY_FEATURE_ID = 18_434_265
DAM_UPSTREAM_ANCHOR_FEATURE_ID = 18_434_275
OUTLET_FEATURE_ID = 18_421_703
NWM_FEATURE_CHUNK_SIZE = 30_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-link", type=Path, default=DEFAULT_ROUTE_LINK)
    parser.add_argument("--d4-network", type=Path, default=DEFAULT_D4_NETWORK)
    parser.add_argument("--d4-report", type=Path, default=DEFAULT_D4_REPORT)
    parser.add_argument("--feature-array", type=Path, default=DEFAULT_FEATURE_ARRAY)
    parser.add_argument("--feature-chunk", type=Path, default=DEFAULT_FEATURE_CHUNK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_subnetwork(
    *,
    route_link_path: Path = DEFAULT_ROUTE_LINK,
    d4_network_path: Path = DEFAULT_D4_NETWORK,
    d4_report_path: Path = DEFAULT_D4_REPORT,
    feature_array_path: Path = DEFAULT_FEATURE_ARRAY,
    feature_chunk_path: Path = DEFAULT_FEATURE_CHUNK,
    output_root: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc)
    source_size = route_link_path.stat().st_size
    if source_size != ROUTE_LINK_MEMBER_SIZE:
        raise ValueError(
            "center_hill_d5_route_link_size_mismatch:"
            f"expected={ROUTE_LINK_MEMBER_SIZE}:actual={source_size}"
        )
    source_sha256 = _sha256_path(route_link_path)
    if source_sha256 != ROUTE_LINK_MEMBER_SHA256:
        raise ValueError("center_hill_d5_route_link_sha256_mismatch")

    d4_network_body = d4_network_path.read_bytes()
    d4_payload = json.loads(d4_network_body)
    d4_report_body = d4_report_path.read_bytes()
    d4_report = json.loads(d4_report_body)
    _validate_d4_inputs(d4_payload, d4_report)
    d4_network = _network(d4_payload["network"])
    d4_confluences = tuple(
        _confluence(value) for value in d4_payload["external_tributary_confluences"]
    )
    mouth_ids = tuple(value.tributary_feature_id for value in d4_confluences)
    receiving_by_mouth = {
        value.tributary_feature_id: value.receiving_feature_id
        for value in d4_confluences
    }

    with _route_link_reader(route_link_path) as reader:
        names = set(reader.variable_names())
        missing_fields = [name for name in REQUIRED_FIELDS if name not in names]
        if missing_fields:
            raise ValueError(
                "center_hill_d5_route_link_required_fields_missing:"
                + ",".join(missing_fields)
            )
        source_links = np.asarray(reader.values("link"), dtype=np.int64).reshape(-1)
        source_to = np.asarray(reader.values("to"), dtype=np.int64).reshape(-1)
        if source_links.shape != source_to.shape:
            raise ValueError("center_hill_d5_route_link_topology_axis_mismatch")
        feature_ids, downstream_ids, branch_memberships = compile_upstream_domain(
            source_links=source_links,
            source_to=source_to,
            branch_mouth_ids=mouth_ids,
            active_mainstem_ids=d4_network.feature_ids,
            expected_receiving_by_mouth=receiving_by_mouth,
            forbidden_feature_ids=(DAM_UPSTREAM_ANCHOR_FEATURE_ID,),
            outlet_feature_id=OUTLET_FEATURE_ID,
        )
        compiled_downstream = dict(
            zip(feature_ids, downstream_ids, strict=True)
        )
        for feature, expected in zip(
            d4_network.feature_ids,
            d4_network.downstream_feature_ids,
            strict=True,
        ):
            if compiled_downstream[feature] != expected:
                raise ValueError(
                    "center_hill_d5_mainstem_downstream_target_mismatch:"
                    f"{feature}:{compiled_downstream[feature]}:{expected}"
                )
        indices = _source_indices(source_links, feature_ids)
        subset_values, variable_attributes, field_audit = _select_parameters(
            reader,
            indices=indices,
            expected_feature_ids=feature_ids,
        )
        source_global_attributes = reader.global_attributes()

    d4_full = dict(
        zip(
            d4_network.feature_ids,
            d4_network.full_lengths_m,
            strict=True,
        )
    )
    d4_effective = dict(
        zip(
            d4_network.feature_ids,
            d4_network.effective_lengths_m,
            strict=True,
        )
    )
    full_lengths = tuple(
        d4_full.get(feature_id, float(route_link_length))
        for feature_id, route_link_length in zip(
            feature_ids, subset_values["Length"], strict=True
        )
    )
    effective_lengths = tuple(
        d4_effective.get(feature_id, full_length)
        for feature_id, full_length in zip(feature_ids, full_lengths, strict=True)
    )
    network = DirectedReachNetwork(
        network_id="center-hill:dam-to-gauge:full-incremental-subnetwork-v1",
        feature_ids=feature_ids,
        downstream_feature_ids=downstream_ids,
        full_lengths_m=full_lengths,
        effective_lengths_m=effective_lengths,
        action_entry_feature_ids=(ACTION_ENTRY_FEATURE_ID,),
        provenance_id=(
            f"nwm-v3-routelink:{source_sha256}|d4-topology:"
            f"{hashlib.sha256(d4_network_body).hexdigest()}"
        ),
        evidence_level="derived",
        admitted=True,
    )
    axis_position = {feature: index for index, feature in enumerate(feature_ids)}
    if any(
        target is not None and axis_position[source] >= axis_position[target]
        for source, target in zip(feature_ids, downstream_ids, strict=True)
    ):
        raise RuntimeError("center_hill_d5_feature_axis_not_topological")

    compiled_confluences = tuple(
        TributaryConfluence(
            tributary_feature_id=value.tributary_feature_id,
            receiving_feature_id=value.receiving_feature_id,
            longitude=value.longitude,
            latitude=value.latitude,
            upstream_network_compiled=True,
            provenance_id=(
                f"{value.provenance_id}|nwm-v3-routelink:{source_sha256}"
            ),
            evidence_level="derived",
            admitted=True,
        )
        for value in d4_confluences
    )
    feature_indices, feature_axis_count = _nwm_feature_indices(
        feature_ids,
        array_path=feature_array_path,
        chunk_path=feature_chunk_path,
    )
    feature_chunks = tuple(
        sorted({value // NWM_FEATURE_CHUNK_SIZE for value in feature_indices})
    )

    output_root.mkdir(parents=True, exist_ok=True)
    route_subset_path = output_root / "RouteLink_CONUS_NWMv3_CenterHill_D5.nc"
    _write_subset(
        route_subset_path,
        subset_values=subset_values,
        variable_attributes=variable_attributes,
        source_global_attributes=source_global_attributes,
        source_member_path=ROUTE_LINK_MEMBER_PATH,
        source_member_sha256=source_sha256,
        source_archive_sha256=ROUTE_LINK_ARCHIVE_SHA256,
        generated_at=generated_at,
        history_subject="Center Hill D5 full incremental subnetwork",
        subset_semantics="selected source rows in deterministic topological order",
    )
    subset_audit = _audit_subset(
        route_subset_path,
        expected_feature_ids=feature_ids,
    )
    network_path = output_root / "full_subnetwork.json"
    network_payload = {
        "network": network.as_dict(),
        "compiled_tributary_confluences": [
            value.as_dict() for value in compiled_confluences
        ],
        "former_boundary_mode": {
            "d4_role": "modeled_tributary_boundary_flux",
            "d5_role": "internally_routed_reach",
            "ground_truth": False,
            "possible_nudging": True,
            "mouth_feature_ids": list(mouth_ids),
        },
    }
    _write_json(network_path, network_payload)
    crosswalk_path = output_root / "nwm_feature_crosswalk.csv"
    _write_crosswalk(crosswalk_path, feature_ids, feature_indices)

    branch_feature_set = set(feature_ids) - set(d4_network.feature_ids)
    branch_sizes = {
        str(mouth): len(set(members) & branch_feature_set)
        for mouth, members in branch_memberships.items()
    }
    report = {
        "schema": SCHEMA,
        "generated_at": generated_at.isoformat(),
        "status": "pass_full_incremental_subnetwork_compiled",
        "data_isolation": {
            "d3_outcome_values_loaded": False,
            "d3_outcome_artifacts_read": False,
            "topology_and_parameter_sources_only": True,
        },
        "source": {
            "publisher": "NOAA National Water Center / Office of Water Prediction",
            "parameter_release": "NWM v3.0",
            "archive_url": ARCHIVE_URL,
            "archive_sha256": ROUTE_LINK_ARCHIVE_SHA256,
            "route_link_member_path": ROUTE_LINK_MEMBER_PATH,
            "route_link_member_size_bytes": source_size,
            "route_link_member_sha256": source_sha256,
            "route_link_source_feature_count": int(source_links.size),
            "route_link_source_global_attributes": source_global_attributes,
        },
        "domain": {
            "feature_count": len(feature_ids),
            "active_mainstem_feature_count": len(d4_network.feature_ids),
            "incremental_branch_feature_count": len(branch_feature_set),
            "direct_tributary_mouth_count": len(mouth_ids),
            "source_reach_count": len(network.source_feature_ids),
            "internal_confluence_reach_count": len(network.confluence_feature_ids),
            "action_entry_feature_id": ACTION_ENTRY_FEATURE_ID,
            "outlet_feature_id": network.outlet_feature_id,
            "full_length_km": float(sum(full_lengths) / 1000.0),
            "effective_length_km": float(sum(effective_lengths) / 1000.0),
            "branch_feature_count_by_direct_mouth": branch_sizes,
        },
        "topology": {
            "method": (
                "reverse traversal of official NWM v3 RouteLink link-to topology "
                "from every D4 direct tributary mouth"
            ),
            "feature_axis_order": "deterministic_Kahn_topological_order",
            "full_upstream_tributary_subnetworks_compiled": True,
            "former_d4_mouth_boundaries_internalized": True,
            "dam_upstream_anchor_excluded": True,
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
            "d4_network": _artifact(d4_network_path, d4_network_body),
            "d4_report": _artifact(d4_report_path, d4_report_body),
            "full_subnetwork": _artifact(network_path, network_path.read_bytes()),
            "route_link_subset": {
                **_route_link_artifact(route_subset_path, route_subset_path.read_bytes()),
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
            "all_d4_mouths_match_official_downstream_targets": True,
            "all_upstream_ancestors_compiled": True,
            "forbidden_dam_upstream_anchor_absent": True,
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
            "d4_predictive_improvement_validated": False,
            "geospatial_kernel_validated": False,
            "new_frozen_evaluation_window_required": True,
            "second_system_required": True,
        },
    }
    return report


def compile_upstream_domain(
    *,
    source_links: Iterable[int],
    source_to: Iterable[int],
    branch_mouth_ids: tuple[int, ...],
    active_mainstem_ids: tuple[int, ...],
    expected_receiving_by_mouth: Mapping[int, int],
    forbidden_feature_ids: Iterable[int],
    outlet_feature_id: int,
) -> tuple[
    tuple[int, ...],
    tuple[int | None, ...],
    dict[int, tuple[int, ...]],
]:
    links = np.asarray(source_links, dtype=np.int64).reshape(-1)
    targets = np.asarray(source_to, dtype=np.int64).reshape(-1)
    if links.size == 0 or links.size != targets.size:
        raise ValueError("center_hill_d5_source_topology_axis_invalid")
    link_sort_order = np.argsort(links, kind="stable")
    sorted_links = links[link_sort_order]
    if bool((sorted_links[1:] == sorted_links[:-1]).any()):
        raise ValueError("center_hill_d5_source_feature_axis_not_unique")
    if not branch_mouth_ids or len(branch_mouth_ids) != len(set(branch_mouth_ids)):
        raise ValueError("center_hill_d5_branch_mouth_axis_invalid")
    required = set(branch_mouth_ids) | set(active_mainstem_ids)
    required_indices, missing = _lookup_source_indices(
        sorted_links,
        link_sort_order,
        tuple(sorted(required)),
    )
    if missing:
        raise ValueError(
            f"center_hill_d5_required_route_link_features_missing:{sorted(missing)}"
        )
    required_target = {
        feature: int(targets[index])
        for feature, index in zip(sorted(required), required_indices, strict=True)
    }
    for mouth in branch_mouth_ids:
        if required_target[mouth] != expected_receiving_by_mouth.get(mouth):
            raise ValueError(
                "center_hill_d5_mouth_downstream_target_mismatch:"
                f"{mouth}:{required_target[mouth]}:"
                f"{expected_receiving_by_mouth.get(mouth)}"
            )

    target_sort_order = np.argsort(targets, kind="stable")
    sorted_targets = targets[target_sort_order]
    memberships: dict[int, tuple[int, ...]] = {}
    branch_features: set[int] = set()
    branch_owner: dict[int, int] = {}
    for mouth in branch_mouth_ids:
        visited: set[int] = set()
        stack = [mouth]
        while stack:
            feature = stack.pop()
            if feature in visited:
                continue
            visited.add(feature)
            left = int(np.searchsorted(sorted_targets, feature, side="left"))
            right = int(np.searchsorted(sorted_targets, feature, side="right"))
            if right > left:
                stack.extend(
                    int(value) for value in links[target_sort_order[left:right]]
                )
        memberships[mouth] = tuple(sorted(visited))
        overlap = set(visited) & set(branch_owner)
        if overlap:
            sample = sorted(overlap)[:20]
            raise ValueError(
                "center_hill_d5_incremental_branches_overlap:"
                f"{mouth}:{len(overlap)}:{sample}"
            )
        branch_owner.update({feature: mouth for feature in visited})
        branch_features.update(visited)

    forbidden = set(forbidden_feature_ids)
    leaked_mainstem = branch_features & set(active_mainstem_ids)
    leaked_forbidden = branch_features & forbidden
    if leaked_mainstem:
        raise ValueError(
            f"center_hill_d5_branch_ancestor_entered_mainstem:{sorted(leaked_mainstem)}"
        )
    if leaked_forbidden:
        raise ValueError(
            f"center_hill_d5_forbidden_ancestor_present:{sorted(leaked_forbidden)}"
        )
    domain = branch_features | set(active_mainstem_ids)
    domain_order = tuple(sorted(domain))
    domain_indices, missing_domain = _lookup_source_indices(
        sorted_links,
        link_sort_order,
        domain_order,
    )
    if missing_domain:
        raise RuntimeError(
            f"center_hill_d5_compiled_features_missing:{sorted(missing_domain)}"
        )
    source_target = {
        feature: int(targets[index])
        for feature, index in zip(domain_order, domain_indices, strict=True)
    }
    downstream_by_feature: dict[int, int | None] = {}
    for feature in domain:
        if feature == outlet_feature_id:
            downstream_by_feature[feature] = None
            continue
        target = source_target[feature]
        if target not in domain:
            raise ValueError(
                f"center_hill_d5_downstream_target_outside_domain:{feature}:{target}"
            )
        downstream_by_feature[feature] = target
    order = _topological_order(downstream_by_feature)
    return (
        order,
        tuple(downstream_by_feature[value] for value in order),
        memberships,
    )


def _source_indices(
    source_links: np.ndarray, requested: tuple[int, ...]
) -> tuple[int, ...]:
    order = np.argsort(source_links, kind="stable")
    indices, missing = _lookup_source_indices(source_links[order], order, requested)
    if missing:
        raise RuntimeError(
            f"center_hill_d5_selected_features_missing:{sorted(missing)}"
        )
    return indices


def _lookup_source_indices(
    sorted_links: np.ndarray,
    source_order: np.ndarray,
    requested: tuple[int, ...],
) -> tuple[tuple[int, ...], set[int]]:
    if not requested:
        return (), set()
    values = np.asarray(requested, dtype=np.int64)
    positions = np.searchsorted(sorted_links, values)
    in_bounds = positions < sorted_links.size
    matched = np.zeros(values.shape, dtype=bool)
    matched[in_bounds] = sorted_links[positions[in_bounds]] == values[in_bounds]
    indices = tuple(
        int(source_order[position])
        for position, present in zip(positions, matched, strict=True)
        if present
    )
    missing = {
        int(value)
        for value, present in zip(values, matched, strict=True)
        if not present
    }
    return indices, missing


def _topological_order(
    downstream_by_feature: Mapping[int, int | None],
) -> tuple[int, ...]:
    indegree = {feature: 0 for feature in downstream_by_feature}
    for target in downstream_by_feature.values():
        if target is not None:
            indegree[target] += 1
    ready = [feature for feature, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    order: list[int] = []
    while ready:
        source = heapq.heappop(ready)
        order.append(source)
        target = downstream_by_feature[source]
        if target is None:
            continue
        indegree[target] -= 1
        if indegree[target] == 0:
            heapq.heappush(ready, target)
    if len(order) != len(downstream_by_feature):
        raise ValueError("center_hill_d5_subnetwork_cycle_detected")
    outlets = [
        feature for feature, target in downstream_by_feature.items() if target is None
    ]
    if len(outlets) != 1:
        raise ValueError("center_hill_d5_subnetwork_requires_one_outlet")
    return tuple(order)


def _select_parameters(
    reader: Any,
    *,
    indices: tuple[int, ...],
    expected_feature_ids: tuple[int, ...],
) -> tuple[
    dict[str, np.ndarray],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    names = set(reader.variable_names())
    source_count = reader.shape("link")[0]
    subset_values: dict[str, np.ndarray] = {}
    attributes: dict[str, dict[str, Any]] = {}
    audit: dict[str, dict[str, Any]] = {}
    for name in REQUIRED_FIELDS + OPTIONAL_FIELDS:
        if name not in names:
            continue
        shape = reader.shape(name)
        if shape != (source_count,):
            if name in REQUIRED_FIELDS:
                raise ValueError(
                    f"center_hill_d5_required_field_axis_mismatch:{name}:{shape}"
                )
            continue
        values = reader.selected(name, indices)
        if values.dtype.kind not in "biuf":
            if name in REQUIRED_FIELDS:
                raise ValueError(
                    f"center_hill_d5_required_field_not_numeric:{name}"
                )
            continue
        numeric = values.astype(float)
        if not np.isfinite(numeric).all():
            raise ValueError(f"center_hill_d5_parameter_nonfinite:{name}")
        if name in POSITIVE_PARAMETER_FIELDS and bool((numeric <= 0.0).any()):
            raise ValueError(f"center_hill_d5_parameter_not_positive:{name}")
        subset_values[name] = values
        attributes[name] = reader.variable_attributes(name)
        audit[name] = {
            "source_dtype": str(reader.dtype(name)),
            "subset_dtype": str(values.dtype),
            "value_count": int(values.size),
            "minimum": float(numeric.min()),
            "maximum": float(numeric.max()),
            "all_finite": True,
        }
    if tuple(int(value) for value in subset_values["link"]) != expected_feature_ids:
        raise RuntimeError("center_hill_d5_parameter_feature_axis_mismatch")
    return subset_values, attributes, audit


def _nwm_feature_indices(
    requested: tuple[int, ...], *, array_path: Path, chunk_path: Path
) -> tuple[tuple[int, ...], int]:
    schema = json.loads(array_path.read_text(encoding="utf-8"))
    if (
        schema.get("shape") != [2_776_734]
        or schema.get("chunks") != [2_776_734]
        or schema.get("dtype") != "<i8"
        or (schema.get("compressor") or {}).get("id") != "zstd"
    ):
        raise ValueError("center_hill_d5_nwm_feature_axis_schema_mismatch")
    executable = shutil.which("zstd")
    if executable is None:
        raise RuntimeError("zstd_executable_required")
    decoded = subprocess.run(
        [executable, "--decompress", "--stdout", "--quiet", str(chunk_path)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    expected_bytes = schema["shape"][0] * np.dtype(schema["dtype"]).itemsize
    if len(decoded) != expected_bytes:
        raise ValueError("center_hill_d5_nwm_feature_axis_size_mismatch")
    values = np.frombuffer(decoded, dtype=np.dtype(schema["dtype"]))
    index = {int(value): offset for offset, value in enumerate(values)}
    missing = set(requested) - set(index)
    if missing:
        sample = sorted(missing)[:20]
        raise ValueError(
            f"center_hill_d5_nwm_subnetwork_features_missing:{len(missing)}:{sample}"
        )
    return tuple(index[value] for value in requested), int(values.size)


def _validate_d4_inputs(
    network_payload: Mapping[str, Any], report: Mapping[str, Any]
) -> None:
    if (
        report.get("schema")
        != "gwm.geotransport.center_hill_v2_d4_topology_audit.v1"
        or report.get("status") != "pass_direct_confluence_boundary_ready"
        or (report.get("data_isolation") or {}).get("d3_outcome_values_loaded")
        is not False
        or (report.get("gates") or {}).get("full_subnetwork_compiled") is not False
    ):
        raise ValueError("center_hill_d5_d4_topology_report_invalid")
    if (
        "network" not in network_payload
        or not network_payload.get("external_tributary_confluences")
    ):
        raise ValueError("center_hill_d5_d4_network_payload_invalid")


def _network(payload: Mapping[str, Any]) -> DirectedReachNetwork:
    return DirectedReachNetwork(
        network_id=str(payload["network_id"]),
        feature_ids=tuple(int(value) for value in payload["feature_ids"]),
        downstream_feature_ids=tuple(
            None if value is None else int(value)
            for value in payload["downstream_feature_ids"]
        ),
        full_lengths_m=tuple(float(value) for value in payload["full_lengths_m"]),
        effective_lengths_m=tuple(
            float(value) for value in payload["effective_lengths_m"]
        ),
        action_entry_feature_ids=tuple(
            int(value) for value in payload["action_entry_feature_ids"]
        ),
        provenance_id=str(payload["provenance_id"]),
        evidence_level=str(payload["evidence_level"]),
        admitted=bool(payload["admitted"]),
    )


def _confluence(payload: Mapping[str, Any]) -> TributaryConfluence:
    coordinate = payload["coordinate"]
    return TributaryConfluence(
        tributary_feature_id=int(payload["tributary_feature_id"]),
        receiving_feature_id=int(payload["receiving_feature_id"]),
        longitude=float(coordinate[0]),
        latitude=float(coordinate[1]),
        upstream_network_compiled=bool(payload["upstream_network_compiled"]),
        provenance_id=str(payload["provenance_id"]),
        evidence_level=str(payload["evidence_level"]),
        admitted=bool(payload["admitted"]),
    )


def _write_crosswalk(
    path: Path, feature_ids: tuple[int, ...], feature_indices: tuple[int, ...]
) -> None:
    lines = ["feature_id,nwm_feature_index,nwm_feature_chunk_index"]
    lines.extend(
        f"{feature_id},{index},{index // NWM_FEATURE_CHUNK_SIZE}"
        for feature_id, index in zip(feature_ids, feature_indices, strict=True)
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
        d4_network_path=args.d4_network,
        d4_report_path=args.d4_report,
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
    print(
        "nwm_feature_chunk_indices="
        + ",".join(str(value) for value in report["nwm_crosswalk"]["feature_chunk_indices"])
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
