#!/usr/bin/env python3
"""Compile Center Hill direct tributary confluences for post-D3 D4."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

import numpy as np

from data_agent.uwm.geospatial_kernel_v2 import (
    DirectedReachNetwork,
    TributaryConfluence,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/nldi_path_crosswalk_report.json"
)
DEFAULT_TRAVEL_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_travel_time_prior_report.json"
)
DEFAULT_FEATURE_ARRAY = REPO_ROOT / (
    "data/geotransport_v0_1/metadata/nwm-feature-id-zarray.json"
)
DEFAULT_FEATURE_CHUNK = REPO_ROOT / (
    "data/geotransport_v0_1/nwm/feature_id/0.zst"
)
DEFAULT_RAW = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_v2_d4_topology/raw/"
    "gauge_upstream_tributaries_30km.json"
)
DEFAULT_NETWORK = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_v2_d4_topology/"
    "branching_boundary_network.json"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_v2_d4_topology_report.json"
)
SCHEMA = "gwm.geotransport.center_hill_v2_d4_topology_audit.v1"
NLDI_DISTANCE_KM = 30.0
NLDI_URL = (
    "https://api.water.usgs.gov/nldi/linked-data/nwissite/"
    "USGS-03424860/navigation/UT/flowlines?distance=30.0"
)
USER_AGENT = "gisdataagent-center-hill-d4-topology/0.1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acquire", action="store_true")
    parser.add_argument("--proxy", default="")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--path-report", type=Path, default=DEFAULT_PATH_REPORT)
    parser.add_argument("--travel-report", type=Path, default=DEFAULT_TRAVEL_REPORT)
    parser.add_argument("--feature-array", type=Path, default=DEFAULT_FEATURE_ARRAY)
    parser.add_argument("--feature-chunk", type=Path, default=DEFAULT_FEATURE_CHUNK)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--network", type=Path, default=DEFAULT_NETWORK)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_report(
    *,
    acquire: bool = False,
    proxy: str = "",
    timeout_seconds: float = 120.0,
    retries: int = 4,
    path_report_path: Path = DEFAULT_PATH_REPORT,
    travel_report_path: Path = DEFAULT_TRAVEL_REPORT,
    feature_array_path: Path = DEFAULT_FEATURE_ARRAY,
    feature_chunk_path: Path = DEFAULT_FEATURE_CHUNK,
    raw_path: Path = DEFAULT_RAW,
    network_path: Path = DEFAULT_NETWORK,
) -> dict[str, Any]:
    retrieval: dict[str, Any] | None = None
    if acquire:
        body, retrieval = _fetch(
            NLDI_URL,
            proxy=proxy,
            timeout_seconds=timeout_seconds,
            retries=retries,
        )
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(body)
    raw_body = raw_path.read_bytes()
    upstream = json.loads(raw_body)
    if upstream.get("type") != "FeatureCollection":
        raise ValueError("center_hill_d4_nldi_feature_collection_required")

    path_body = path_report_path.read_bytes()
    path_report = json.loads(path_body)
    system = next(
        row for row in path_report["systems"] if row["system_id"] == "center_hill"
    )
    mainstem_path = tuple(int(value) for value in system["path"]["feature_ids"])
    if (
        system["action_comid"] != mainstem_path[0]
        or system["gauge_comid"] != mainstem_path[-1]
        or system["path"]["gauge_reachable"] is not True
    ):
        raise ValueError("center_hill_d4_path_anchor_mismatch")
    active_mainstem = mainstem_path[1:]

    features = {_comid(feature): feature for feature in upstream["features"]}
    if len(features) != len(upstream["features"]):
        raise ValueError("center_hill_d4_nldi_duplicate_feature_id")
    missing_mainstem = set(mainstem_path) - set(features)
    if missing_mainstem:
        raise ValueError(
            f"center_hill_d4_mainstem_missing_from_ut:{sorted(missing_mainstem)}"
        )
    if not all(
        _coordinate(_downstream_coordinate(features[source]))
        == _coordinate(_upstream_coordinate(features[target]))
        for source, target in zip(
            mainstem_path[:-1], mainstem_path[1:], strict=True
        )
    ):
        raise ValueError("center_hill_d4_mainstem_geometry_not_continuous")

    by_downstream_coordinate: dict[tuple[float, float], list[int]] = {}
    for feature_id, feature in features.items():
        by_downstream_coordinate.setdefault(
            _coordinate(_downstream_coordinate(feature)), []
        ).append(feature_id)
    mainstem_set = set(mainstem_path)
    confluence_rows: list[dict[str, Any]] = []
    contracts: list[TributaryConfluence] = []
    for receiving_id in active_mainstem:
        coordinate = _coordinate(_upstream_coordinate(features[receiving_id]))
        tributaries = sorted(
            feature_id
            for feature_id in by_downstream_coordinate.get(coordinate, [])
            if feature_id not in mainstem_set
        )
        for tributary_id in tributaries:
            contract = TributaryConfluence(
                tributary_feature_id=tributary_id,
                receiving_feature_id=receiving_id,
                longitude=coordinate[0],
                latitude=coordinate[1],
                upstream_network_compiled=False,
                provenance_id=f"usgs-nldi:UT-30km:{_sha256(raw_body)}",
                evidence_level="derived",
                admitted=True,
            )
            contracts.append(contract)
            confluence_rows.append(contract.as_dict())
    if not contracts:
        raise ValueError("center_hill_d4_direct_tributary_confluences_required")
    tributary_ids = tuple(value.tributary_feature_id for value in contracts)
    if len(tributary_ids) != len(set(tributary_ids)):
        raise ValueError("center_hill_d4_duplicate_direct_tributary")

    travel_body = travel_report_path.read_bytes()
    travel = json.loads(travel_body)["linear_referenced_path"]
    if tuple(travel["feature_ids"]) != mainstem_path:
        raise ValueError("center_hill_d4_travel_path_axis_mismatch")
    effective_length_km = float(sum(travel["effective_lengths_m"])) / 1000.0
    network = DirectedReachNetwork(
        network_id="center_hill:dam-to-gauge:mouth-boundary-v1",
        feature_ids=active_mainstem,
        downstream_feature_ids=active_mainstem[1:] + (None,),
        full_lengths_m=tuple(float(value) for value in travel["full_lengths_m"][1:]),
        effective_lengths_m=tuple(
            float(value) for value in travel["effective_lengths_m"][1:]
        ),
        action_entry_feature_ids=(active_mainstem[0],),
        provenance_id=(
            f"nldi-path:{_sha256(path_body)}|nldi-ut:{_sha256(raw_body)}|"
            f"linear-reference:{_sha256(travel_body)}"
        ),
        evidence_level="derived",
        admitted=True,
    )
    feature_indices, feature_axis = _nwm_feature_indices(
        tributary_ids,
        array_path=feature_array_path,
        chunk_path=feature_chunk_path,
    )
    chunk_width = 30_000
    chunk_indices = tuple(sorted({value // chunk_width for value in feature_indices}))
    crosswalk = [
        {
            "tributary_feature_id": feature_id,
            "nwm_feature_index": feature_index,
            "nwm_feature_chunk_index": feature_index // chunk_width,
        }
        for feature_id, feature_index in zip(
            tributary_ids, feature_indices, strict=True
        )
    ]
    network_payload = {
        "network": network.as_dict(),
        "external_tributary_confluences": confluence_rows,
        "boundary_mode": {
            "variable_role": "modeled_tributary_boundary_flux",
            "ground_truth": False,
            "possible_nudging": True,
            "receiving_feature_ids": [
                value.receiving_feature_id for value in contracts
            ],
        },
    }
    network_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(network_path, network_payload)
    network_body = network_path.read_bytes()

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass_direct_confluence_boundary_ready",
        "data_isolation": {
            "d3_outcome_values_loaded": False,
            "d3_outcome_artifacts_read": False,
            "topology_sources_only": True,
        },
        "domain": {
            "action_comid": system["action_comid"],
            "action_entry_feature_id": active_mainstem[0],
            "gauge_comid": system["gauge_comid"],
            "nldi_full_reach_navigation_length_km": system["path"][
                "full_reach_path_length_km"
            ],
            "linear_referenced_effective_length_km": effective_length_km,
            "active_mainstem_feature_count": len(active_mainstem),
            "active_mainstem_feature_ids": list(active_mainstem),
            "direct_off_path_tributary_count": len(contracts),
            "direct_off_path_tributary_feature_ids": list(tributary_ids),
            "receiving_mainstem_feature_count": len(
                {value.receiving_feature_id for value in contracts}
            ),
        },
        "topology_method": {
            "navigation": "USGS NLDI upstream tributaries from USGS-03424860",
            "maximum_navigation_distance_km": NLDI_DISTANCE_KM,
            "nldi_full_reach_navigation_length_km": system["path"][
                "full_reach_path_length_km"
            ],
            "linear_referenced_effective_length_km": effective_length_km,
            "attachment_rule": (
                "tributary downstream endpoint equals receiving mainstem "
                "upstream endpoint"
            ),
            "coordinate_normalization": "longitude_latitude_rounded_9_decimals",
            "full_upstream_tributary_subnetworks_compiled": False,
        },
        "confluences": confluence_rows,
        "nwm_boundary_crosswalk": {
            "source": "NOAA NWM v3 retrospective chrtout.zarr/feature_id",
            "all_direct_tributaries_present": True,
            "feature_axis_artifact": _artifact(feature_chunk_path),
            "feature_axis_count": feature_axis,
            "streamflow_feature_chunk_indices": list(chunk_indices),
            "rows": crosswalk,
            "variable_role": "modeled_tributary_boundary_flux",
            "ground_truth": False,
            "possible_nudging": True,
        },
        "artifacts": {
            "nldi_path_report": _artifact(path_report_path),
            "linear_reference_report": _artifact(travel_report_path),
            "nldi_upstream_tributaries_30km": _artifact(raw_path),
            "branching_boundary_network": {
                "path": _display(network_path),
                "sha256": _sha256(network_body),
                "size_bytes": len(network_body),
            },
        },
        "source_request": {
            "url": NLDI_URL,
            "retrieval": retrieval,
        },
        "adjudication": {
            "selected_first_executable_mode": "modeled_tributary_boundary_flux",
            "scientific_endpoint": "full_subnetwork_distributed_q_lateral_routing",
            "selection_reason": (
                "Direct confluence attachments and NWM mouth feature membership "
                "are complete; full upstream branch topology, branch geometry, "
                "initial state, and forcing support are not yet complete."
            ),
            "d3_window_use": (
                "public_post_failure_flux_accounting_diagnostic_only_not_model_"
                "selection_or_validation"
            ),
            "future_validation_requires_new_frozen_window": True,
            "future_validation_requires_second_system": True,
        },
        "gates": {
            "mainstem_interval_present_in_upstream_navigation": True,
            "mainstem_geometry_continuous": True,
            "direct_off_path_confluences_present": True,
            "direct_tributary_feature_ids_unique": True,
            "direct_tributaries_present_on_nwm_feature_axis": True,
            "mouth_boundary_semantics_fail_closed": True,
            "full_subnetwork_compiled": False,
        },
        "claim_boundary": {
            "d3_mainstem_only_omission_structurally_verified": True,
            "direct_off_path_tributary_count": len(contracts),
            "branching_kernel_contract_ready": True,
            "modeled_tributary_boundary_acquisition_ready": True,
            "full_subnetwork_routing_ready": False,
            "d4_predictive_improvement_validated": False,
            "geospatial_kernel_validated": False,
        },
    }


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
        raise ValueError("center_hill_d4_nwm_feature_axis_schema_mismatch")
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
        raise ValueError("center_hill_d4_nwm_feature_axis_size_mismatch")
    values = np.frombuffer(decoded, dtype=np.dtype(schema["dtype"]))
    index = {int(value): offset for offset, value in enumerate(values)}
    missing = set(requested) - set(index)
    if missing:
        raise ValueError(f"center_hill_d4_nwm_tributaries_missing:{sorted(missing)}")
    return tuple(index[value] for value in requested), int(values.size)


def _fetch(
    url: str, *, proxy: str, timeout_seconds: float, retries: int
) -> tuple[bytes, dict[str, Any]]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "api.water.usgs.gov":
        raise ValueError("center_hill_d4_url_outside_allowlist")
    handlers: list[urllib.request.BaseHandler] = []
    if proxy:
        handlers.append(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    opener = urllib.request.build_opener(*handlers)
    error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/geo+json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                final = urllib.parse.urlparse(response.geturl())
                if final.scheme != "https" or final.hostname != "api.water.usgs.gov":
                    raise ValueError("center_hill_d4_redirect_outside_allowlist")
                body = response.read(2_000_001)
                if len(body) > 2_000_000:
                    raise ValueError("center_hill_d4_response_size_limit_exceeded")
                json.loads(body)
                return body, {
                    "http_status": response.status,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "attempt_count": attempt,
                    "content_type": response.headers.get("Content-Type"),
                }
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
        ) as exc:
            error = exc
            if attempt < retries:
                time.sleep(float(attempt))
    raise RuntimeError(f"center_hill_d4_nldi_request_failed:{error}")


def _comid(feature: dict[str, Any]) -> int:
    properties = feature.get("properties") or {}
    value = properties.get("nhdplus_comid", properties.get("comid"))
    if value is None:
        raise ValueError("center_hill_d4_feature_comid_missing")
    return int(value)


def _coordinates(feature: dict[str, Any]) -> list[list[float]]:
    geometry = feature.get("geometry") or {}
    coordinates = geometry.get("coordinates") or []
    if geometry.get("type") != "LineString" or len(coordinates) < 2:
        raise ValueError("center_hill_d4_linestring_required")
    return coordinates


def _upstream_coordinate(feature: dict[str, Any]) -> list[float]:
    return _coordinates(feature)[0]


def _downstream_coordinate(feature: dict[str, Any]) -> list[float]:
    return _coordinates(feature)[-1]


def _coordinate(values: list[float]) -> tuple[float, float]:
    if len(values) != 2 or not all(math.isfinite(float(value)) for value in values):
        raise ValueError("center_hill_d4_coordinate_invalid")
    return round(float(values[0]), 9), round(float(values[1]), 9)


def _artifact(path: Path) -> dict[str, Any]:
    body = path.read_bytes()
    return {
        "path": _display(path),
        "sha256": _sha256(body),
        "size_bytes": len(body),
    }


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    report = compile_report(
        acquire=args.acquire,
        proxy=args.proxy,
        timeout_seconds=args.timeout_seconds,
        retries=args.retries,
        path_report_path=args.path_report,
        travel_report_path=args.travel_report,
        feature_array_path=args.feature_array,
        feature_chunk_path=args.feature_chunk,
        raw_path=args.raw,
        network_path=args.network,
    )
    _write_json(args.output, report)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
