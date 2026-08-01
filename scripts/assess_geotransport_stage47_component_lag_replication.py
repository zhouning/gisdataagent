#!/usr/bin/env python3
"""Execute the frozen offline Stage 47 component-lag assessment."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_agent.uwm.geospatial_kernel_v2 import (  # noqa: E402
    public_component_lag_replication_evidence as evidence,
)

DEFAULT_OUTPUT = REPO_ROOT / evidence.STAGE47_ROOT
LEDGER_NAME = "component_lag_replication_evidence_ledger.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--execute-frozen-assessment",
        action="store_true",
        help="Required after the Stage 45 acquisition checkpoint exists.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _require_execution_flag(args.execute_frozen_assessment)
    output = _validate_output(args.output)
    ledger = evidence.compile_public_component_lag_replication_evidence()
    path = output / LEDGER_NAME
    _write_json(path, ledger.as_dict())
    print(path)
    print(f"status={ledger.status}")
    print("network_requests=0")
    print(f"sha256={hashlib.sha256(path.read_bytes()).hexdigest()}")
    return 0


def _require_execution_flag(approved: bool) -> None:
    if not approved:
        raise ValueError("stage47_explicit_frozen_assessment_flag_required")


def _validate_output(path: Path) -> Path:
    output = path.resolve()
    if output != DEFAULT_OUTPUT.resolve():
        raise ValueError("stage47_output_must_match_frozen_root")
    return output


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(body)
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
