#!/usr/bin/env python3
"""Seal one real-time uncertainty-shadow issue before any target outcome matures."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.action_innovation_shadow_request import (
    action_innovation_shadow_request_from_dict,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_shadow_runtime import REPO_ROOT
from data_agent.uwm.geospatial_kernel_v2.action_innovation_transition import (
    ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_uncertainty_shadow_runtime import (
    DEFAULT_UNCERTAINTY_FREEZE_PATH,
)

if __package__:
    from scripts.run_geospatial_kernel_action_innovation_uncertainty_shadow import (
        compile_uncertainty_shadow_receipt,
    )
else:
    from run_geospatial_kernel_action_innovation_uncertainty_shadow import (
        compile_uncertainty_shadow_receipt,
    )

MAXIMUM_ISSUE_LATENCY = timedelta(minutes=15)


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
        "--enable-prospective-shadow",
        action="store_true",
        help="Acknowledge real-time shadow sealing; production admission remains false.",
    )
    return parser.parse_args()


def compile_prospective_issue_receipt(
    request_body: bytes,
    *,
    uncertainty_freeze_path: Path = DEFAULT_UNCERTAINTY_FREEZE_PATH,
    repository_root: Path = REPO_ROOT,
    enable_prospective_shadow: bool = False,
) -> dict[str, Any]:
    if enable_prospective_shadow is not True:
        raise RuntimeError("action_innovation_prospective_issue_sealing_disabled")
    request_payload = _json_mapping(
        request_body,
        "action_innovation_prospective_issue_request_json_invalid",
    )
    request = action_innovation_shadow_request_from_dict(request_payload)
    freeze = _json_mapping(
        uncertainty_freeze_path.read_bytes(),
        "action_innovation_prospective_issue_freeze_json_invalid",
    )
    frozen_at = _time(freeze.get("frozen_at"), "freeze")
    started_at = _now()
    expected_targets = tuple(
        request.issue_time + timedelta(hours=horizon)
        for horizon in ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS
    )
    if request.target_valid_times != expected_targets:
        raise ValueError("action_innovation_prospective_issue_horizons_invalid")
    if (
        request.issue_time < frozen_at
        or started_at < request.issue_time
        or started_at > request.issue_time + MAXIMUM_ISSUE_LATENCY
        or min(request.target_valid_times) <= started_at
    ):
        raise ValueError("action_innovation_prospective_issue_ordering_invalid")

    receipt = compile_uncertainty_shadow_receipt(
        request_body,
        uncertainty_freeze_path=uncertainty_freeze_path,
        repository_root=repository_root,
        enable_shadow=True,
    )
    generated_at = _time(receipt.get("generated_at"), "receipt_generated")
    if (
        generated_at < started_at
        or generated_at < request.issue_time
        or generated_at > request.issue_time + MAXIMUM_ISSUE_LATENCY
        or generated_at >= min(request.target_valid_times)
        or receipt.get("request_identity", {}).get("network_id") != request.network_id
        or receipt.get("claim_boundary", {}).get("admitted") is not False
    ):
        raise ValueError("action_innovation_prospective_issue_receipt_invalid")
    return receipt


def _json_mapping(body: bytes, error: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(error) from exc
    if not isinstance(payload, Mapping):
        raise ValueError(error)
    return payload


def _time(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"action_innovation_prospective_issue_{name}_time_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"action_innovation_prospective_issue_{name}_time_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"action_innovation_prospective_issue_{name}_time_invalid")
    return parsed


def _now() -> datetime:
    return datetime.now(UTC)


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise ValueError("action_innovation_prospective_issue_receipt_refuses_overwrite")
    receipt = compile_prospective_issue_receipt(
        args.request.read_bytes(),
        uncertainty_freeze_path=args.uncertainty_freeze,
        enable_prospective_shadow=args.enable_prospective_shadow,
    )
    _write(args.output, receipt)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
