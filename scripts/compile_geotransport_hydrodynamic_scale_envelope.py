#!/usr/bin/env python3
"""Compile outcome-free gravity-wave and diffusive path-scale envelopes."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from data_agent.uwm.geospatial_kernel_v2.hydrodynamic_path_response import (
    HYDRODYNAMIC_PATH_RESPONSE_SCHEMA,
    HydrodynamicPathResponseDiagnostic,
)

if __package__:
    from scripts.acquire_geotransport_kinematic_wave_celerity_envelope import (
        HOUR_COUNT,
        SYSTEM_IDS,
        compile_plan,
    )
else:
    from acquire_geotransport_kinematic_wave_celerity_envelope import (
        HOUR_COUNT,
        SYSTEM_IDS,
        compile_plan,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
CELERITY_REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_celerity_envelope_report.json"
)
OUTPUT_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/hydrodynamic_scale_envelope"
)
REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/hydrodynamic_scale_envelope_report.json"
)
SCHEMA = "gwm.geotransport.hydrodynamic_scale_envelope.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--celerity-report", type=Path, default=CELERITY_REPORT_PATH)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    return parser.parse_args()


def compile_envelopes(
    *,
    celerity_report_path: Path = CELERITY_REPORT_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> tuple[dict[str, Any], dict[Path, bytes]]:
    celerity_body = celerity_report_path.read_bytes()
    celerity = json.loads(celerity_body)
    if (
        celerity.get("schema")
        != "gwm.geotransport.kinematic_wave_celerity_envelope.v1"
        or celerity.get("status")
        != "public_modeled_state_celerity_envelopes_compiled"
        or celerity.get("window", {}).get("hour_count") != HOUR_COUNT
        or celerity.get("claim_boundary", {}).get(
            "outcome_artifacts_read_by_acquisition"
        )
        is not False
    ):
        raise ValueError("hydrodynamic_scale_celerity_report_invalid")
    celerity_systems = celerity.get("systems") or {}
    if not isinstance(celerity_systems, Mapping):
        raise ValueError("hydrodynamic_scale_system_container_invalid")
    if set(celerity_systems) != set(SYSTEM_IDS):
        raise ValueError("hydrodynamic_scale_system_axis_invalid")

    _, contexts = compile_plan()
    contexts.pop("_shared")
    systems = []
    outputs: dict[Path, bytes] = {}
    for system_id in SYSTEM_IDS:
        source = celerity_systems[system_id]
        context = contexts[system_id]
        network = context["network"]
        geometry = context["geometry"]
        decoded = source["decoded_arrays"]
        feature_ids = _read_npy(decoded["feature_ids"])
        timestamps = _read_npy(decoded["state_timestamps_utc"])
        streamflow = _read_npy(decoded["streamflow_m3s"])
        if (
            tuple(int(value) for value in feature_ids.tolist())
            != network.feature_ids
            or timestamps.shape != (HOUR_COUNT,)
            or streamflow.shape != (HOUR_COUNT, len(network.feature_ids))
        ):
            raise ValueError(f"hydrodynamic_scale_{system_id}_decoded_axis_invalid")

        diagnostic = HydrodynamicPathResponseDiagnostic(network, geometry)
        responses = []
        for row in range(HOUR_COUNT):
            responses.append(
                diagnostic.analyze(
                    tuple(float(value) for value in streamflow[row]),
                    start_feature_id=network.action_entry_feature_ids[0],
                    end_feature_id=network.outlet_feature_id,
                    path_id=f"{system_id}:action-entry-to-outlet",
                    provenance_id=(
                        "noaa-nwm-v3-retrospective:streamflow:563|"
                        f"{network.provenance_id}"
                    ),
                    evidence_level="candidate",
                    outcome_calibrated=False,
                )
            )
        valid = [value for value in responses if value.finite_path_scales_available]
        if len(valid) != HOUR_COUNT:
            raise ValueError(f"hydrodynamic_scale_{system_id}_nonpropagating_state")

        metrics = {
            "manning_centroid_travel_time_hours_q05_q50_q95": _quantiles(
                value.manning_centroid_travel_time_seconds / 3600.0
                for value in valid
            ),
            "gravity_wave_travel_time_hours_q05_q50_q95": _quantiles(
                value.gravity_wave_travel_time_seconds / 3600.0
                for value in valid
            ),
            "gravity_to_manning_time_ratio_q05_q50_q95": _quantiles(
                value.gravity_to_manning_time_ratio for value in valid
            ),
            "diffusive_first_passage_standard_deviation_hours_q05_q50_q95": (
                _quantiles(
                    value.diffusive_first_passage_standard_deviation_seconds
                    / 3600.0
                    for value in valid
                )
            ),
            "diffusive_spread_to_manning_time_ratio_q05_q50_q95": _quantiles(
                value.diffusive_spread_to_manning_time_ratio for value in valid
            ),
            "maximum_path_froude_number_q05_q50_q95": _quantiles(
                value.maximum_froude_number for value in valid
            ),
            "minimum_reach_peclet_number_q05_q50_q95": _quantiles(
                value.minimum_reach_peclet_number for value in valid
            ),
            "supercritical_effective_length_fraction_q05_q50_q95": _quantiles(
                value.supercritical_effective_length_fraction for value in valid
            ),
            "supercritical_manning_time_fraction_q05_q50_q95": _quantiles(
                value.supercritical_manning_time_fraction for value in valid
            ),
            "supercritical_gravity_time_fraction_q05_q50_q95": _quantiles(
                value.supercritical_gravity_time_fraction for value in valid
            ),
        }
        csv_body = _response_csv(timestamps, responses)
        csv_path = output_root / f"systems/{system_id}/path_scales.csv"
        outputs[csv_path] = csv_body
        systems.append(
            {
                "system_id": system_id,
                "path_response_schema": HYDRODYNAMIC_PATH_RESPONSE_SCHEMA,
                "path_feature_ids": list(valid[0].feature_ids),
                "state_source": {
                    "feature_ids": decoded["feature_ids"],
                    "state_timestamps_utc": decoded["state_timestamps_utc"],
                    "streamflow_m3s": decoded["streamflow_m3s"],
                },
                "path_scale_values": _body_artifact(csv_path, csv_body),
                "envelopes": metrics,
                "reach_regime_envelopes": [
                    {
                        "feature_id": feature_id,
                        "effective_length_m": valid[0].reaches[index].effective_length_m,
                        "froude_number_q05_q50_q95": _quantiles(
                            value.reaches[index].froude_number for value in valid
                        ),
                        "hydraulic_diffusivity_m2s_q05_q50_q95": _quantiles(
                            value.reaches[index].hydraulic_diffusivity_m2s
                            for value in valid
                        ),
                        "reach_peclet_number_q05_q50_q95": _quantiles(
                            value.reaches[index].reach_peclet_number
                            for value in valid
                        ),
                        "diffusive_variance_fraction_q05_q50_q95": _quantiles(
                            value.reaches[index].diffusive_first_passage_variance_seconds2
                            / (
                                value.diffusive_first_passage_standard_deviation_seconds
                                ** 2
                            )
                            for value in valid
                        ),
                        "supercritical_hour_count": sum(
                            value.reaches[index].froude_number >= 1.0
                            for value in valid
                        ),
                    }
                    for index, feature_id in enumerate(valid[0].feature_ids)
                ],
                "quality": {
                    "state_hour_count": HOUR_COUNT,
                    "finite_path_scale_hour_count": len(valid),
                    "nonpropagating_path_hour_count": HOUR_COUNT - len(valid),
                    "gravity_time_shorter_than_manning_hour_count": sum(
                        value.gravity_wave_travel_time_seconds
                        < value.manning_centroid_travel_time_seconds
                        for value in valid
                    ),
                    "fully_subcritical_path_hour_count": sum(
                        value.maximum_froude_number < 1.0 for value in valid
                    ),
                },
                "semantic_contract": {
                    "gravity_wave_time_admitted_as_flood_wave_lag": False,
                    "diffusive_spread_admitted_as_flood_wave_lag": False,
                    "diffusive_centroid_changed_from_manning": False,
                    "operator_implemented": False,
                    "outcome_values_used": False,
                },
            }
        )

    report = {
        "schema": SCHEMA,
        "status": "public_state_hydrodynamic_scales_compiled_not_operator_admission",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_artifact": _artifact(celerity_report_path, celerity_body),
        "window": celerity["window"],
        "physics_contract": {
            "base_state_area": "Manning Q-to-A using RouteLink trapezoid geometry",
            "top_width": "T = b + 2 z y",
            "gravity_wave_celerity": "c_g = sqrt(g A / T)",
            "hydraulic_diffusivity": "D = Q / (2 S0 T)",
            "diffusive_centroid_celerity": "c_k = dQ/dA",
            "diffusive_first_passage_variance": "sum(2 D L / c_k^3)",
            "diffusive_variance_assumption": (
                "independent linearized reach first-passage moments"
            ),
        },
        "systems": systems,
        "claim_boundary": {
            "public_data_without_user_supplied_data": True,
            "outcome_values_used": False,
            "state_dependent_gravity_wave_scale_compiled": True,
            "state_dependent_diffusive_scale_compiled": True,
            "gravity_wave_time_admitted_as_flood_wave_lag": False,
            "diffusive_spread_admitted_as_flood_wave_lag": False,
            "candidate_operator_implemented": False,
            "candidate_operator_admitted": False,
            "geospatial_kernel_validated": False,
        },
    }
    return report, outputs


def _quantiles(values: Any) -> list[float]:
    array = np.asarray(tuple(values), dtype=float)
    if array.size == 0 or not np.isfinite(array).all():
        raise ValueError("hydrodynamic_scale_quantile_values_invalid")
    return [float(value) for value in np.quantile(array, [0.05, 0.5, 0.95])]


def _response_csv(timestamps: np.ndarray, responses: list[Any]) -> bytes:
    rows: list[list[object]] = [
        [
            "timestamp_utc",
            "manning_centroid_travel_time_hours",
            "gravity_wave_travel_time_hours",
            "gravity_to_manning_time_ratio",
            "diffusive_first_passage_standard_deviation_hours",
            "diffusive_spread_to_manning_time_ratio",
            "maximum_path_froude_number",
            "minimum_reach_peclet_number",
            "supercritical_effective_length_fraction",
            "supercritical_manning_time_fraction",
            "supercritical_gravity_time_fraction",
        ]
    ]
    for timestamp, value in zip(timestamps.tolist(), responses, strict=True):
        rows.append(
            [
                str(timestamp),
                _number(value.manning_centroid_travel_time_seconds, 3600.0),
                _number(value.gravity_wave_travel_time_seconds, 3600.0),
                _number(value.gravity_to_manning_time_ratio),
                _number(
                    value.diffusive_first_passage_standard_deviation_seconds,
                    3600.0,
                ),
                _number(value.diffusive_spread_to_manning_time_ratio),
                _number(value.maximum_froude_number),
                _number(value.minimum_reach_peclet_number),
                _number(value.supercritical_effective_length_fraction),
                _number(value.supercritical_manning_time_fraction),
                _number(value.supercritical_gravity_time_fraction),
            ]
        )
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _number(value: float | None, scale: float = 1.0) -> str:
    return "" if value is None else format(float(value) / scale, ".12g")


def _read_npy(descriptor: Mapping[str, Any]) -> np.ndarray:
    path = (REPO_ROOT / str(descriptor.get("path"))).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("hydrodynamic_scale_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("hydrodynamic_scale_decoded_artifact_identity_mismatch")
    values = np.load(path, allow_pickle=False)
    if list(values.shape) != descriptor.get("shape") or str(values.dtype) != descriptor.get(
        "dtype"
    ):
        raise ValueError("hydrodynamic_scale_decoded_artifact_schema_mismatch")
    return values


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": _display(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _body_artifact(path: Path, body: bytes) -> dict[str, Any]:
    return _artifact(path, body)


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
    report, outputs = compile_envelopes(
        celerity_report_path=args.celerity_report,
        output_root=args.output_root,
    )
    for path, body in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    _write_json(args.report, report)
    print(args.report)
    for system in report["systems"]:
        print(
            f"{system['system_id']}: gravity_hours_q05_q50_q95="
            f"{system['envelopes']['gravity_wave_travel_time_hours_q05_q50_q95']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
