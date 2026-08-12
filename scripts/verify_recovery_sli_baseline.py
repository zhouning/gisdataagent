#!/usr/bin/env python3
"""Verify a recovery SLI observation against its profile and source report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from data_agent.platform_runtime.deployment_profile import load_deployment_profile
from data_agent.platform_runtime.recovery_sli_baseline import (
    VERIFICATION_SCHEMA,
    load_recovery_sli_baseline,
    verify_recovery_sli_baseline,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = "config/recovery_sli_baselines/main-compose-dev-20260731.json"
DEFAULT_PROFILE = "config/deployment_profiles/main-compose-dev.json"
DEFAULT_REPORT = (
    "config/recovery_sli_baselines/evidence/"
    "main-compose-dev-20260731-recovery-report.json"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--report", default=DEFAULT_REPORT)
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    baseline_path = _resolve(args.baseline)
    profile_path = _resolve(args.profile)
    report_path = _resolve(args.report)
    try:
        baseline = load_recovery_sli_baseline(baseline_path)
        profile = load_deployment_profile(profile_path)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        verification = verify_recovery_sli_baseline(
            baseline=baseline,
            profile=profile,
            report=report,
        )
        payload = verification.to_dict()
        exit_code = 0 if verification.technical_pass else 1
    except (OSError, ValueError, json.JSONDecodeError, ValidationError) as exc:
        payload = {
            "schema": VERIFICATION_SCHEMA,
            "technical_pass": False,
            "promotion_ready": False,
            "error_type": type(exc).__name__,
        }
        exit_code = 2

    rendered = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return exit_code


def _resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
