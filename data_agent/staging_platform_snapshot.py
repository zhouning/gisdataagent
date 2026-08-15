"""Emit the minimal strict platform snapshot allowed in staging evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .platform_truth import build_platform_snapshot


def project_staging_platform_snapshot(
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Project a platform snapshot to the non-secret deployment allowlist."""
    config = snapshot.get("config")
    environment_access = snapshot.get("environment_access")
    runtime = snapshot.get("runtime")
    config = config if isinstance(config, Mapping) else {}
    environment_access = (
        environment_access
        if isinstance(environment_access, Mapping)
        else {}
    )
    runtime = runtime if isinstance(runtime, Mapping) else {}
    return {
        "schema": snapshot.get("schema"),
        "generated_at": snapshot.get("generated_at"),
        "platform_fingerprint": snapshot.get("platform_fingerprint"),
        "config": {
            "schema": config.get("schema"),
            "generated_at": config.get("generated_at"),
            "profile": config.get("profile"),
            "strict": config.get("strict"),
            "valid": config.get("valid"),
            "startup_allowed": config.get("startup_allowed"),
            "config_fingerprint": config.get("config_fingerprint"),
        },
        "environment_access": {
            "fingerprint": environment_access.get("fingerprint"),
            "matches_baseline": environment_access.get("matches_baseline"),
            "parse_errors": environment_access.get("parse_errors"),
        },
        "runtime": {
            "status": runtime.get("status"),
            "matches_primitive_baseline": runtime.get(
                "matches_primitive_baseline"
            ),
            "inventory_fingerprint": runtime.get("inventory_fingerprint"),
            "errors": runtime.get("errors"),
        },
    }


def staging_platform_snapshot_valid(snapshot: Mapping[str, Any]) -> bool:
    """Return whether the compact snapshot satisfies the staging preflight."""
    config = snapshot.get("config")
    environment_access = snapshot.get("environment_access")
    runtime = snapshot.get("runtime")
    config = config if isinstance(config, Mapping) else {}
    environment_access = (
        environment_access
        if isinstance(environment_access, Mapping)
        else {}
    )
    runtime = runtime if isinstance(runtime, Mapping) else {}
    return all(
        (
            config.get("profile") == "staging",
            config.get("strict") is True,
            config.get("valid") is True,
            config.get("startup_allowed") is True,
            environment_access.get("matches_baseline") is True,
            environment_access.get("parse_errors") == [],
            runtime.get("status") == "valid",
            runtime.get("matches_primitive_baseline") is True,
            runtime.get("errors") == [],
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("staging",))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    snapshot = project_staging_platform_snapshot(
        build_platform_snapshot(profile=args.profile)
    )
    rendered = json.dumps(snapshot, ensure_ascii=True, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if staging_platform_snapshot_valid(snapshot) else 1


if __name__ == "__main__":
    raise SystemExit(main())
