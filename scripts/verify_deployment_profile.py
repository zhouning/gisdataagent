#!/usr/bin/env python3
"""Verify a versioned deployment profile against Compose and runtime facts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from data_agent.platform_runtime import (
    DeploymentProfileVerifier,
    load_deployment_profile,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = "config/deployment_profiles/main-compose-dev.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--static-only", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    profile_path = Path(args.profile)
    if not profile_path.is_absolute():
        profile_path = REPO_ROOT / profile_path
    try:
        profile = load_deployment_profile(profile_path)
        verifier = DeploymentProfileVerifier(
            profile=profile,
            profile_path=profile_path,
            repo_root=REPO_ROOT,
        )
        report = verifier.verify(include_runtime=not args.static_only)
        payload = report.to_dict()
        exit_code = 0 if report.technical_pass else 1
    except (OSError, ValueError, json.JSONDecodeError, ValidationError) as exc:
        payload = {
            "schema": "gis-data-agent.deployment-profile-verification.v1",
            "technical_pass": False,
            "error_type": type(exc).__name__,
        }
        exit_code = 2

    rendered = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
