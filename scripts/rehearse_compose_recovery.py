#!/usr/bin/env python3
"""Run an isolated PostGIS and MinIO recovery rehearsal for one Compose profile."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from data_agent.platform_runtime.deployment_profile import load_deployment_profile
from data_agent.platform_runtime.recovery_rehearsal import (
    ComposeRecoveryRehearsal,
    RecoveryRehearsalError,
    failure_report,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = "config/deployment_profiles/main-compose-dev.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    profile_path = Path(args.profile)
    if not profile_path.is_absolute():
        profile_path = REPO_ROOT / profile_path
    profile_id = None
    try:
        profile = load_deployment_profile(profile_path)
        profile_id = profile.profile_id
        payload = ComposeRecoveryRehearsal(
            profile=profile,
            profile_path=profile_path,
            repo_root=REPO_ROOT,
        ).run()
        exit_code = 0
    except RecoveryRehearsalError as exc:
        payload = failure_report(
            profile_id=profile_id,
            stage=exc.stage,
            error_type=type(exc).__name__,
        )
        exit_code = 1
    except (OSError, ValueError, json.JSONDecodeError, ValidationError) as exc:
        payload = failure_report(
            profile_id=profile_id,
            stage="profile",
            error_type=type(exc).__name__,
        )
        exit_code = 2

    rendered = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
