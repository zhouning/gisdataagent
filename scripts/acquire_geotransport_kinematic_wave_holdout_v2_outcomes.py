#!/usr/bin/env python3
"""Acquire both v2 USGS outcomes only after the joint prediction seal."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from data_agent.uwm.geospatial_kernel_v2 import DEFAULT_REGISTRY_PATH

if __package__:
    import scripts.acquire_geotransport_kinematic_wave_holdout_v1_outcomes as base
    from scripts.freeze_geotransport_kinematic_wave_holdout_v2 import (
        END,
        HOUR_COUNT,
        OUTCOME_SCHEMA,
        ROLLOUT_SCHEMA,
        SCHEMA as PROTOCOL_SCHEMA,
        START,
    )
else:
    import acquire_geotransport_kinematic_wave_holdout_v1_outcomes as base
    from freeze_geotransport_kinematic_wave_holdout_v2 import (
        END,
        HOUR_COUNT,
        OUTCOME_SCHEMA,
        ROLLOUT_SCHEMA,
        SCHEMA as PROTOCOL_SCHEMA,
        START,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_protocol.json"
)
DEFAULT_ROLLOUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_rollout_report.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/kinematic_wave_holdout_v2/outcomes"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_outcomes_report.json"
)
SCHEMA = OUTCOME_SCHEMA


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--rollout", type=Path, default=DEFAULT_ROLLOUT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=4)
    return parser.parse_args()


@contextmanager
def _v2_context() -> Iterator[None]:
    replacements = {
        "START": START,
        "END": END,
        "HOUR_COUNT": HOUR_COUNT,
        "PROTOCOL_SCHEMA": PROTOCOL_SCHEMA,
        "ROLLOUT_SCHEMA": ROLLOUT_SCHEMA,
        "SCHEMA": SCHEMA,
    }
    original = {name: getattr(base, name) for name in replacements}
    for name, value in replacements.items():
        setattr(base, name, value)
    try:
        yield
    finally:
        for name, value in original.items():
            setattr(base, name, value)


def acquire(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    rollout_path: Path = DEFAULT_ROLLOUT,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    output_root: Path = DEFAULT_OUTPUT,
    proxy: str = "http://127.0.0.1:7897",
    timeout_seconds: float = 180.0,
    retries: int = 4,
) -> tuple[dict[str, bytes], dict[str, bytes], dict[str, Any]]:
    with _v2_context():
        return base.acquire(
            protocol_path=protocol_path,
            rollout_path=rollout_path,
            registry_path=registry_path,
            output_root=output_root,
            proxy=proxy,
            timeout_seconds=timeout_seconds,
            retries=retries,
        )


def main() -> int:
    args = parse_args()
    if args.output.exists() or args.report.exists():
        raise ValueError("kinematic_holdout_v2_outcomes_refuse_overwrite")
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("kinematic_holdout_v2_positive_outcome_request_limits_required")
    raw, values, report = acquire(
        protocol_path=args.protocol,
        rollout_path=args.rollout,
        registry_path=args.registry,
        output_root=args.output,
        proxy=args.proxy,
        timeout_seconds=args.timeout_seconds,
        retries=args.retries,
    )
    for system_id in base.SYSTEM_IDS:
        raw_path = args.output / f"raw/{system_id}.json"
        value_path = args.output / f"values/{system_id}.csv"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        value_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(raw[system_id])
        value_path.write_bytes(values[system_id])
    base._write_json(args.report, report)
    print(args.report)
    for system_id in base.SYSTEM_IDS:
        quality = report["systems"][system_id]["quality"]
        print(
            f"{system_id}_complete_target_hours="
            f"{quality['target_complete_hour_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
