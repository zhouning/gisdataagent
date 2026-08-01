#!/usr/bin/env python3
"""Execute one frozen point-plus-uncertainty shadow request."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.action_innovation_shadow_request import (
    SHADOW_REQUEST_ADAPTER_PATH,
    action_innovation_shadow_request_from_dict,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_shadow_runtime import REPO_ROOT
from data_agent.uwm.geospatial_kernel_v2.action_innovation_uncertainty_shadow_runtime import (
    DEFAULT_UNCERTAINTY_FREEZE_PATH,
    load_frozen_action_innovation_uncertainty_shadow_runtime,
)

SCHEMA = "gwm.geospatial_kernel.action_innovation_uncertainty_shadow_run_receipt.v1"
RUNNER_PATH = Path(__file__).resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--uncertainty-freeze",
        type=Path,
        default=DEFAULT_UNCERTAINTY_FREEZE_PATH,
    )
    parser.add_argument(
        "--enable-shadow",
        action="store_true",
        help="Explicitly enable shadow execution; production admission remains false.",
    )
    return parser.parse_args()


def compile_uncertainty_shadow_receipt(
    request_body: bytes,
    *,
    uncertainty_freeze_path: Path = DEFAULT_UNCERTAINTY_FREEZE_PATH,
    repository_root: Path = REPO_ROOT,
    enable_shadow: bool = False,
) -> dict[str, Any]:
    try:
        payload = json.loads(request_body)
    except json.JSONDecodeError as exc:
        raise ValueError("action_innovation_uncertainty_shadow_request_json_invalid") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("action_innovation_uncertainty_shadow_request_document_mapping_required")
    request = action_innovation_shadow_request_from_dict(payload)
    runtime = load_frozen_action_innovation_uncertainty_shadow_runtime(
        uncertainty_freeze_path=uncertainty_freeze_path,
        repository_root=repository_root,
        enabled=enable_shadow,
    )
    result = runtime.forecast(
        request.outlet_state,
        request.hourly_inputs,
        network_id=request.network_id,
        issue_time=request.issue_time,
        target_valid_times=request.target_valid_times,
        input_attestation=request.input_attestation,
    )
    return {
        "schema": SCHEMA,
        "status": "uncertainty_shadow_forecast_complete_not_admitted",
        "generated_at": _now().isoformat(),
        "request_identity": {
            "request_id": request.request_id,
            "network_id": request.network_id,
            "source_document_sha256": hashlib.sha256(request_body).hexdigest(),
            "source_document_size_bytes": len(request_body),
            "normalized_request_sha256": request.normalized_sha256(),
        },
        "execution_identity": {
            "point_freeze_sha256": result.point_shadow_forecast.freeze_sha256,
            "point_parameter_sha256": result.point_shadow_forecast.parameter_sha256,
            "point_runtime_sha256": result.point_shadow_forecast.runtime_sha256,
            "uncertainty_freeze_sha256": result.uncertainty_freeze_sha256,
            "uncertainty_parameter_sha256": result.uncertainty_parameter_sha256,
            "uncertainty_runtime_sha256": result.uncertainty_runtime_sha256,
            "request_adapter_sha256": hashlib.sha256(
                SHADOW_REQUEST_ADAPTER_PATH.read_bytes()
            ).hexdigest(),
            "runner_sha256": hashlib.sha256(RUNNER_PATH.read_bytes()).hexdigest(),
        },
        "result": result.as_dict(),
        "claim_boundary": {
            "shadow_only": True,
            "calibration_outcomes_used": True,
            "finite_sample_coverage_guarantee_claimed": False,
            "conditional_coverage_guarantee_claimed": False,
            "production_eligible": False,
            "runtime_default_enabled": False,
            "admitted": False,
        },
    }


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _now() -> datetime:
    return datetime.now(UTC)


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise ValueError("action_innovation_uncertainty_shadow_receipt_refuses_overwrite")
    receipt = compile_uncertainty_shadow_receipt(
        args.request.read_bytes(),
        uncertainty_freeze_path=args.uncertainty_freeze,
        enable_shadow=args.enable_shadow,
    )
    _write(args.output, receipt)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
