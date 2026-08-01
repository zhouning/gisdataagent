#!/usr/bin/env python3
"""Run and seal v2 predictions with the frozen two-ULP CFL adjudication."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import numpy as np

if __package__:
    import scripts.run_geotransport_kinematic_wave_holdout_v1_outcome_free as base
    from scripts.freeze_geotransport_kinematic_wave_holdout_v2 import (
        END,
        HOUR_COUNT,
        INPUT_SCHEMA,
        ROLLOUT_SCHEMA,
        SCHEMA as PROTOCOL_SCHEMA,
        START,
    )
else:
    import run_geotransport_kinematic_wave_holdout_v1_outcome_free as base
    from freeze_geotransport_kinematic_wave_holdout_v2 import (
        END,
        HOUR_COUNT,
        INPUT_SCHEMA,
        ROLLOUT_SCHEMA,
        SCHEMA as PROTOCOL_SCHEMA,
        START,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_protocol.json"
)
DEFAULT_INPUT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_inputs_report.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/kinematic_wave_holdout_v2/predictions"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_rollout_report.json"
)
OUTCOME_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/kinematic_wave_holdout_v2/outcomes"
)
SCHEMA = ROLLOUT_SCHEMA


class _TwoUlpNumpyProxy:
    """Delegate NumPy except for the predeclared two-ULP reporting limit."""

    def __init__(self, module: Any) -> None:
        self._module = module

    def __getattr__(self, name: str) -> Any:
        return getattr(self._module, name)

    def nextafter(self, value: Any, direction: Any) -> Any:
        first = self._module.nextafter(value, direction)
        return self._module.nextafter(first, direction)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--input-report", type=Path, default=DEFAULT_INPUT_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


@contextmanager
def _v2_context() -> Iterator[None]:
    replacements = {
        "START": START,
        "END": END,
        "HOUR_COUNT": HOUR_COUNT,
        "PROTOCOL_SCHEMA": PROTOCOL_SCHEMA,
        "INPUT_SCHEMA": INPUT_SCHEMA,
        "SCHEMA": SCHEMA,
        "OUTCOME_ROOT": OUTCOME_ROOT,
        "np": _TwoUlpNumpyProxy(np),
    }
    original = {name: getattr(base, name) for name in replacements}
    for name, value in replacements.items():
        setattr(base, name, value)
    try:
        yield
    finally:
        for name, value in original.items():
            setattr(base, name, value)


def compile_rollouts(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    input_report_path: Path = DEFAULT_INPUT_REPORT,
    output_root: Path = DEFAULT_OUTPUT,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    with _v2_context():
        predictions, report = base.compile_rollouts(
            protocol_path=protocol_path,
            input_report_path=input_report_path,
            output_root=output_root,
        )
    for system in report["systems"].values():
        invariants = system["invariants"]
        expected_limit = float(
            np.nextafter(np.nextafter(np.float64(0.8), np.inf), np.inf)
        )
        if invariants["cfl_comparison_limit_one_binary64_ulp"] != expected_limit:
            raise RuntimeError("kinematic_holdout_v2_two_ulp_adjudication_missing")
        invariants["cfl_comparison_limit_two_binary64_ulps"] = invariants.pop(
            "cfl_comparison_limit_one_binary64_ulp"
        )
        system["registered_execution"]["cfl_reporting_comparison"] = (
            "configured_CFL_plus_two_binary64_ULPs"
        )
    report["protocol_adjudication"] = {
        "v1_gate_modified": False,
        "v2_cfl_reporting_limit_binary64": expected_limit,
        "operator_flux_state_or_timestep_changed_from_v1": False,
        "prediction_value_postprocessing": False,
    }
    return predictions, report


def main() -> int:
    args = parse_args()
    prediction_paths = [
        args.output / f"{system_id}.csv" for system_id in base.SYSTEM_IDS
    ]
    if args.report.exists() or any(path.exists() for path in prediction_paths):
        raise ValueError("kinematic_holdout_v2_rollout_refuses_overwrite")
    predictions, report = compile_rollouts(
        protocol_path=args.protocol,
        input_report_path=args.input_report,
        output_root=args.output,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    for system_id, body in predictions.items():
        (args.output / f"{system_id}.csv").write_bytes(body)
    base._write_json(args.report, report)
    print(args.report)
    print(f"joint_seal_sha256={report['joint_seal']['sha256']}")
    for system_id in base.SYSTEM_IDS:
        print(
            f"{system_id}_prediction_sha256="
            f"{report['systems'][system_id]['prediction_artifact']['sha256']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
