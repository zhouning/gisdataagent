#!/usr/bin/env python3
"""Execute one explicitly acknowledged frozen-candidate shadow request."""

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
from data_agent.uwm.geospatial_kernel_v2.action_innovation_shadow_runtime import (
    DEFAULT_FREEZE_PATH,
    REPO_ROOT,
    load_frozen_action_innovation_shadow_runtime,
)

SCHEMA = "gwm.geospatial_kernel.action_innovation_shadow_run_receipt.v1"
RUNNER_PATH = Path(__file__).resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE_PATH)
    parser.add_argument(
        "--enable-shadow",
        action="store_true",
        help="Explicitly enable shadow execution; production admission remains false.",
    )
    return parser.parse_args()


def compile_shadow_receipt(
    request_body: bytes,
    *,
    freeze_path: Path = DEFAULT_FREEZE_PATH,
    repository_root: Path = REPO_ROOT,
    enable_shadow: bool = False,
) -> dict[str, Any]:
    try:
        payload = json.loads(request_body)
    except json.JSONDecodeError as exc:
        raise ValueError("action_innovation_shadow_request_json_invalid") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("action_innovation_shadow_request_document_mapping_required")
    request = action_innovation_shadow_request_from_dict(payload)
    runtime = load_frozen_action_innovation_shadow_runtime(
        freeze_path=freeze_path,
        repository_root=repository_root,
        enabled=enable_shadow,
    )
    result = request.execute(runtime)
    result_document = result.as_dict()
    return {
        "schema": SCHEMA,
        "status": "shadow_forecast_complete_not_admitted",
        "generated_at": datetime.now(UTC).isoformat(),
        "request_identity": {
            "request_id": request.request_id,
            "network_id": request.network_id,
            "source_document_sha256": hashlib.sha256(request_body).hexdigest(),
            "source_document_size_bytes": len(request_body),
            "normalized_request_sha256": request.normalized_sha256(),
        },
        "execution_identity": {
            "freeze_sha256": result.freeze_sha256,
            "parameter_sha256": result.parameter_sha256,
            "runtime_sha256": result.runtime_sha256,
            "request_adapter_sha256": hashlib.sha256(
                SHADOW_REQUEST_ADAPTER_PATH.read_bytes()
            ).hexdigest(),
            "runner_sha256": hashlib.sha256(RUNNER_PATH.read_bytes()).hexdigest(),
        },
        "result": result_document,
        "claim_boundary": {
            "shadow_only": True,
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


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise ValueError("action_innovation_shadow_receipt_refuses_overwrite")
    receipt = compile_shadow_receipt(
        args.request.read_bytes(),
        freeze_path=args.freeze,
        enable_shadow=args.enable_shadow,
    )
    _write(args.output, receipt)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
