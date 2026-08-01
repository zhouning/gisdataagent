#!/usr/bin/env python3
"""Acquire v2 kinematic-wave holdout inputs without accessing outcomes."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from data_agent.uwm.geospatial_kernel_v2 import DEFAULT_REGISTRY_PATH

if __package__:
    import scripts.acquire_geotransport_kinematic_wave_holdout_v1_inputs as base
    from scripts.freeze_geotransport_kinematic_wave_holdout_v2 import (
        END,
        HOUR_COUNT,
        INITIAL_STATE_AT,
        INITIAL_TIME_CHUNK,
        INPUT_SCHEMA,
        ROLLOUT_TIME_CHUNK,
        SCHEMA as PROTOCOL_SCHEMA,
        START,
    )
else:
    import acquire_geotransport_kinematic_wave_holdout_v1_inputs as base
    from freeze_geotransport_kinematic_wave_holdout_v2 import (
        END,
        HOUR_COUNT,
        INITIAL_STATE_AT,
        INITIAL_TIME_CHUNK,
        INPUT_SCHEMA,
        ROLLOUT_TIME_CHUNK,
        SCHEMA as PROTOCOL_SCHEMA,
        START,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_protocol.json"
)
DEFAULT_METADATA_ROOT = REPO_ROOT / "data/geotransport_v0_1/metadata"
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/kinematic_wave_holdout_v2/inputs"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_inputs_report.json"
)
OUTCOME_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/kinematic_wave_holdout_v2/outcomes"
)
SCHEMA = INPUT_SCHEMA


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--metadata-root", type=Path, default=DEFAULT_METADATA_ROOT)
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
        "INITIAL_STATE_AT": INITIAL_STATE_AT,
        "INITIAL_TIME_CHUNK": INITIAL_TIME_CHUNK,
        "ROLLOUT_TIME_CHUNK": ROLLOUT_TIME_CHUNK,
        "PROTOCOL_SCHEMA": PROTOCOL_SCHEMA,
        "SCHEMA": SCHEMA,
        "OUTCOME_ROOT": OUTCOME_ROOT,
    }
    original = {name: getattr(base, name) for name in replacements}
    for name, value in replacements.items():
        setattr(base, name, value)
    try:
        yield
    finally:
        for name, value in original.items():
            setattr(base, name, value)


def compile_plan(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    metadata_root: Path = DEFAULT_METADATA_ROOT,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    with _v2_context():
        return base.compile_plan(
            protocol_path=protocol_path,
            registry_path=registry_path,
            metadata_root=metadata_root,
        )


def acquire(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    metadata_root: Path = DEFAULT_METADATA_ROOT,
    output_root: Path = DEFAULT_OUTPUT,
    proxy: str = "http://127.0.0.1:7897",
    timeout_seconds: float = 180.0,
    retries: int = 4,
) -> dict[str, Any]:
    with _v2_context():
        return base.acquire(
            protocol_path=protocol_path,
            registry_path=registry_path,
            metadata_root=metadata_root,
            output_root=output_root,
            proxy=proxy,
            timeout_seconds=timeout_seconds,
            retries=retries,
        )


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("kinematic_holdout_v2_positive_request_limits_required")
    if args.report.exists():
        raise ValueError("kinematic_holdout_v2_input_report_refuses_overwrite")
    if args.plan_only:
        report, _, _ = compile_plan(
            protocol_path=args.protocol,
            registry_path=args.registry,
            metadata_root=args.metadata_root,
        )
    else:
        report = acquire(
            protocol_path=args.protocol,
            registry_path=args.registry,
            metadata_root=args.metadata_root,
            output_root=args.output,
            proxy=args.proxy,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
        )
    base._write_json(args.report, report)
    print(args.report)
    print(f"mode={report['mode']}")
    print(f"nwm_unique_object_count={report['nwm_unique_object_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
