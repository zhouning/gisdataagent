#!/usr/bin/env python3
"""Restart DolphinScheduler and verify the governed JQDLTB run is recoverable."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from finalize_chongqing_jqdltb_dataops_run import finalize

from data_agent.dolphinscheduler_recovery import (
    ContainerSnapshot,
    DolphinSchedulerRecoveryError,
    build_recovery_report,
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DolphinSchedulerRecoveryError("input.json_object")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    os.replace(temporary, path)


def _compose_prefix(compose_file: Path, env_file: Path) -> list[str]:
    return [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "-f",
        str(compose_file),
    ]


def _run(command: list[str], stage: str) -> str:
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DolphinSchedulerRecoveryError(stage) from exc
    return completed.stdout.strip()


def _container_snapshot(
    compose_file: Path, env_file: Path, service: str
) -> ContainerSnapshot:
    container_id = _run(
        [*_compose_prefix(compose_file, env_file), "ps", "-q", service],
        f"{service}.container_lookup",
    )
    if "\n" in container_id or not container_id:
        raise DolphinSchedulerRecoveryError(f"{service}.container_identity")
    started_at = _run(
        ["docker", "inspect", "--format", "{{.State.StartedAt}}", container_id],
        f"{service}.container_inspect",
    )
    return ContainerSnapshot(
        service=service,
        container_id=container_id,
        started_at=started_at,
    )


def _wait_ready(url: str, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                value = json.load(response)
            if isinstance(value, dict) and value.get("status") == "UP":
                return
        except (OSError, ValueError, urllib.error.URLError):
            pass
        time.sleep(2)
    raise DolphinSchedulerRecoveryError("runtime.health_timeout")


def rehearse(
    *,
    profile_path: Path,
    deployment_path: Path,
    submission_path: Path,
    compose_file: Path,
    env_file: Path,
    runtime_dir: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    for path in (
        profile_path,
        deployment_path,
        submission_path,
        compose_file,
        env_file,
    ):
        if not path.resolve().is_file():
            raise DolphinSchedulerRecoveryError("input.missing")
    profile = _read_json(profile_path)
    health_url = f"{str(profile['base_url']).rstrip('/')}/actuator/health"

    before = finalize(
        profile_path=profile_path,
        deployment_path=deployment_path,
        submission_path=submission_path,
        runtime_dir=runtime_dir,
    )
    runtime_before = _container_snapshot(compose_file, env_file, "dolphinscheduler")
    metadata_before = _container_snapshot(compose_file, env_file, "metadata-db")

    started_monotonic = time.monotonic()
    restarted_at = datetime.now(UTC)
    _run(
        [
            *_compose_prefix(compose_file, env_file),
            "restart",
            "dolphinscheduler",
        ],
        "runtime.restart",
    )
    _wait_ready(health_url, timeout_seconds)
    ready_at = datetime.now(UTC)

    runtime_after = _container_snapshot(compose_file, env_file, "dolphinscheduler")
    metadata_after = _container_snapshot(compose_file, env_file, "metadata-db")
    after = finalize(
        profile_path=profile_path,
        deployment_path=deployment_path,
        submission_path=submission_path,
        runtime_dir=runtime_dir,
    )
    report = build_recovery_report(
        before_document=before,
        after_document=after,
        runtime_before=runtime_before,
        runtime_after=runtime_after,
        metadata_before=metadata_before,
        metadata_after=metadata_after,
        restarted_at=restarted_at.isoformat(),
        ready_at=ready_at.isoformat(),
        observed_seconds=time.monotonic() - started_monotonic,
    )
    _write_json(runtime_dir / "jqdltb-dolphinscheduler-restart-recovery.json", report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--deployment", required=True, type=Path)
    parser.add_argument("--submission", required=True, type=Path)
    parser.add_argument("--compose-file", required=True, type=Path)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--runtime-dir", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=240.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(
        json.dumps(
            rehearse(
                profile_path=args.profile.resolve(),
                deployment_path=args.deployment.resolve(),
                submission_path=args.submission.resolve(),
                compose_file=args.compose_file.resolve(),
                env_file=args.env_file.resolve(),
                runtime_dir=args.runtime_dir.resolve(),
                timeout_seconds=args.timeout_seconds,
            ),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
