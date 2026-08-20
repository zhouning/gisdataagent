#!/usr/bin/env python3
"""Run aggregate-only stormwater probes through registered Makani source 13."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from data_agent.uwm.abu_dhabi_flood.makani_probe import (
    EXPECTED_SOURCE_BINDING,
    PROBE_SPECS,
    atomic_write_probe,
    build_probe_artifact,
    load_json_object,
    sha256_text,
    validate_aggregate_result,
    validate_discovery_export,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SQL_ROOT = ROOT / "scripts/sql/abu_dhabi_flood"
DEFAULT_OUTPUT = (
    ROOT
    / "benchmarks/abu_dhabi_stormwater_data_v1/derived/makani_registered"
    / "makani_relationship_probe.json"
)
DEFAULT_OPERATOR = ("uv", "run", "--no-sync", "gda-source-operator")


def _operator_json(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"source_operator_failed:{completed.returncode}")
    return load_json_object(completed.stdout, label="source_operator_output")


def run_probe(
    *,
    output: Path = DEFAULT_OUTPUT,
    sql_root: Path = DEFAULT_SQL_ROOT,
    owner: str = "abu-dhabi-site-operator",
    operator: tuple[str, ...] = DEFAULT_OPERATOR,
) -> dict[str, Any]:
    discovery_payload = _operator_json(
        [
            *operator,
            "export-discovery",
            "--source-id",
            str(EXPECTED_SOURCE_BINDING["source_id"]),
            "--owner",
            owner,
        ]
    )
    discovery = validate_discovery_export(discovery_payload)

    results: list[dict[str, Any]] = []
    query_contracts: list[dict[str, Any]] = []
    for spec in PROBE_SPECS:
        sql_path = sql_root / spec.sql_filename
        sql = sql_path.read_text(encoding="utf-8").strip()
        if not sql:
            raise ValueError(f"makani_probe_sql_empty:{spec.probe_id}")
        payload = _operator_json(
            [
                *operator,
                "query-database",
                "--source-id",
                str(EXPECTED_SOURCE_BINDING["source_id"]),
                "--owner",
                owner,
                "--sql-file",
                str(sql_path),
                "--limit",
                str(spec.maximum_rows),
                "--include-rows",
            ]
        )
        results.append(validate_aggregate_result(spec, payload))
        query_contracts.append(
            {
                "probe_id": spec.probe_id,
                "path": str(sql_path.relative_to(ROOT)),
                "sha256": sha256_text(sql),
                "read_only": True,
                "schema_qualified": True,
                "aggregate_only": True,
                "bounded_limit": spec.maximum_rows,
            }
        )

    artifact = build_probe_artifact(
        discovery,
        results,
        sql_contracts=query_contracts,
    )
    atomic_write_probe(output, artifact)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sql-root", type=Path, default=DEFAULT_SQL_ROOT)
    parser.add_argument("--owner", default="abu-dhabi-site-operator")
    args = parser.parse_args()
    try:
        artifact = run_probe(output=args.output, sql_root=args.sql_root, owner=args.owner)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=True))
        return 1
    print(
        json.dumps(
            {
                "status": "ok",
                "output": str(args.output),
                "probe_count": len(artifact["results"]),
                "source_feature_rows_persisted": False,
                "admitted": False,
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
