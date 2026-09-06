"""Audit frozen NL2SQL Gold results against a governed source cohort.

The audit executes evaluation-only Gold SQL independently from model output.
It persists result fingerprints and row counts, never source rows.  A benchmark
can therefore distinguish a model mismatch from a Gold contract that no longer
describes the currently registered source result.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .free_form_nl2sql_benchmark import (
    BenchmarkConfigurationError,
    _load_json,
    _sha256_json,
    _validate_benchmark,
)
from .query_result_contract import tabular_result_contract
from .virtual_source_operator import _load_environment
from .virtual_sources import get_virtual_source, query_virtual_source

GOLD_SOURCE_COHORT_SCHEMA = "gda.nl2sql-gold-source-cohort.v1"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _source_registration_fingerprint(source: dict[str, Any]) -> str:
    snapshot = source.get("discovery_snapshot") or {}
    return _sha256_json(
        {
            "source_id": source.get("id"),
            "source_name": source.get("source_name"),
            "source_type": source.get("source_type"),
            "endpoint_url_sha256": _sha256_bytes(
                str(source.get("endpoint_url") or "").encode("utf-8")
            ),
            "database_name": snapshot.get("database_name"),
            "authorized_schemas": list(snapshot.get("authorized_schemas") or []),
            "discovery_fingerprint": source.get("discovery_fingerprint"),
            "profile_fingerprint": source.get("profile_fingerprint"),
        }
    )


def _query_path(gold: dict[str, Any], *, benchmark_path: Path) -> Path:
    value = str((gold.get("query") or {}).get("path") or "")
    if not value:
        raise BenchmarkConfigurationError("Gold query path is missing")
    path = Path(value)
    if not path.is_absolute():
        repository_root = Path(__file__).resolve().parents[1]
        repository_path = repository_root / path
        path = repository_path if repository_path.exists() else benchmark_path.parent / path
    path = path.resolve()
    if not path.is_file():
        raise BenchmarkConfigurationError(f"Gold query does not exist: {path}")
    return path


def _equivalence_match(
    observed: dict[str, Any],
    gold_contract: dict[str, Any],
) -> bool:
    equivalence = gold_contract.get("equivalence") or {}
    observed_fingerprints = observed.get("equivalence_fingerprints") or {}
    expected_fingerprints = equivalence.get("expected_fingerprints") or {}
    return any(
        observed_fingerprints.get(key) == expected_fingerprints.get(key)
        for key in equivalence.get("accepted_fingerprint_keys") or []
    )


async def audit_gold_source_cohort(
    *,
    benchmark_path: Path,
    semantic_layer_path: Path,
    source_id: int,
    owner: str,
    contract_ids: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Execute each unique Gold SQL and return row-free cohort evidence."""

    from .migration_runner import verify_runtime_schema_state

    verify_runtime_schema_state(
        required_migrations=(
            "012_virtual_sources",
            "182_governed_virtual_source_discovery",
        )
    )
    benchmark = _load_json(benchmark_path)
    semantic_layer = _load_json(semantic_layer_path)
    cases = _validate_benchmark(
        benchmark,
        semantic_layer,
        source_id=source_id,
        benchmark_path=benchmark_path,
    )
    source = get_virtual_source(source_id, owner)
    if source is None:
        raise RuntimeError("registered_source_unavailable")
    if source.get("credential_status") == "unavailable":
        raise RuntimeError("virtual_source_credentials_unavailable")

    binding = semantic_layer.get("source_binding") or {}
    snapshot = source.get("discovery_snapshot") or {}
    if snapshot.get("database_name") != binding.get("database_name"):
        raise BenchmarkConfigurationError("Registered source database differs from semantic layer")
    if source.get("discovery_fingerprint") != binding.get("discovery_fingerprint"):
        raise BenchmarkConfigurationError("Registered source discovery fingerprint differs")
    if source.get("profile_fingerprint") != binding.get("profile_fingerprint"):
        raise BenchmarkConfigurationError("Registered source profile fingerprint differs")

    requested = {str(value) for value in contract_ids or () if str(value)}
    contracts: dict[str, dict[str, Any]] = {}
    for case in cases:
        gold = (case.get("expected") or {}).get("gold_result_contract")
        if not gold:
            continue
        contract_id = str(gold.get("contract_id") or "")
        if requested and contract_id not in requested:
            continue
        contracts.setdefault(contract_id, gold)
    unknown = sorted(requested - set(contracts))
    if unknown:
        raise BenchmarkConfigurationError(
            "Unknown Gold contract_id(s): " + ", ".join(unknown)
        )
    if not contracts:
        raise BenchmarkConfigurationError("No Gold result contracts selected")

    observations: list[dict[str, Any]] = []
    for contract_id in sorted(contracts):
        gold = contracts[contract_id]
        payload = gold.get("payload") or {}
        query = payload.get("query") or {}
        query_path = _query_path(payload, benchmark_path=benchmark_path)
        sql = query_path.read_text(encoding="utf-8")
        raw_sql_sha256 = _sha256_bytes(sql.encode("utf-8"))
        normalized_sql_sha256 = _sha256_bytes(
            sql.rstrip("\r\n").encode("utf-8")
        )
        expected_sql_sha256 = str(query.get("sha256") or "")
        if not bool(query.get("read_only")):
            raise BenchmarkConfigurationError(f"Gold SQL is not read-only: {contract_id}")
        if expected_sql_sha256 and expected_sql_sha256 not in {
            raw_sql_sha256,
            normalized_sql_sha256,
        }:
            raise BenchmarkConfigurationError(f"Gold SQL checksum mismatch: {contract_id}")
        sql_sha256 = expected_sql_sha256 or raw_sql_sha256

        result = await query_virtual_source(
            source,
            limit=int(query.get("bounded_limit") or 1000),
            extra_params={"sql": sql, "geom_column": ""},
            register_result=False,
        )
        if isinstance(result, dict):
            observations.append(
                {
                    "contract_id": contract_id,
                    "status": "query_error",
                    "gold_contract_sha256": gold.get("sha256"),
                    "query_sha256": sql_sha256,
                    "error": str(result.get("message") or result.get("status") or "query_failed"),
                    "source_rows_persisted": False,
                }
            )
            continue

        current = tabular_result_contract(result)
        expected = gold.get("expected_result") or {}
        equivalent = _equivalence_match(current, gold)
        observations.append(
            {
                "contract_id": contract_id,
                "status": "current" if equivalent else "gold_stale_source_result",
                "gold_contract_sha256": gold.get("sha256"),
                "query_sha256": sql_sha256,
                "expected": {
                    "row_count": expected.get("row_count"),
                    "ordered_result_fingerprint": expected.get(
                        "ordered_result_fingerprint"
                    ),
                    "equivalence_fingerprints": dict(
                        (gold.get("equivalence") or {}).get("expected_fingerprints")
                        or {}
                    ),
                },
                "current": {
                    "columns": list(current.get("columns") or []),
                    "row_count": current.get("row_count"),
                    "ordered_result_fingerprint": current.get("result_fingerprint"),
                    "equivalence_fingerprints": dict(
                        current.get("equivalence_fingerprints") or {}
                    ),
                },
                "source_rows_persisted": False,
            }
        )

    cohort_basis = {
        "source_registration_fingerprint": _source_registration_fingerprint(source),
        "benchmark_sha256": _sha256_json(benchmark),
        "semantic_layer_sha256": _sha256_json(semantic_layer),
        "observations": [
            {
                "contract_id": item.get("contract_id"),
                "status": item.get("status"),
                "gold_contract_sha256": item.get("gold_contract_sha256"),
                "query_sha256": item.get("query_sha256"),
                "current": item.get("current"),
            }
            for item in observations
        ],
    }
    status_counts: dict[str, int] = {}
    for item in observations:
        status = str(item.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    complete = not status_counts.get("query_error")
    return {
        "schema": GOLD_SOURCE_COHORT_SCHEMA,
        "version": "1.0.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "complete" if complete else "incomplete",
        "cohort_id": _sha256_json(cohort_basis),
        "source": {
            "source_id": source_id,
            "source_name": source.get("source_name"),
            "database_name": snapshot.get("database_name"),
            "authorized_schemas": list(snapshot.get("authorized_schemas") or []),
            "discovery_fingerprint": source.get("discovery_fingerprint"),
            "profile_fingerprint": source.get("profile_fingerprint"),
            "last_discovery_at": source.get("last_discovery_at"),
            "source_registration_fingerprint": cohort_basis[
                "source_registration_fingerprint"
            ],
        },
        "inputs": {
            "benchmark": str(benchmark_path),
            "benchmark_sha256": cohort_basis["benchmark_sha256"],
            "semantic_layer": str(semantic_layer_path),
            "semantic_layer_sha256": cohort_basis["semantic_layer_sha256"],
        },
        "metrics": {
            "contract_count": len(observations),
            "current_contract_count": status_counts.get("current", 0),
            "gold_stale_source_result_contract_count": status_counts.get(
                "gold_stale_source_result", 0
            ),
            "query_error_contract_count": status_counts.get("query_error", 0),
            "status_counts": dict(sorted(status_counts.items())),
        },
        "claim_boundary": {
            "source_rows_persisted": False,
            "gold_sql_available_to_runtime": False,
            "model_output_used_for_classification": False,
            "cohort_scope_limited_to_selected_gold_queries": True,
        },
        "observations": observations,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit frozen NL2SQL Gold results against the registered source."
    )
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--semantic-layer", type=Path, required=True)
    parser.add_argument("--source-id", type=int, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--contract-id", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    _load_environment()
    args = _parser().parse_args(argv)
    try:
        result = asyncio.run(
            audit_gold_source_cohort(
                benchmark_path=args.benchmark.resolve(),
                semantic_layer_path=args.semantic_layer.resolve(),
                source_id=args.source_id,
                owner=args.owner,
                contract_ids=tuple(args.contract_id),
            )
        )
    except Exception as exc:
        result = {
            "schema": GOLD_SOURCE_COHORT_SCHEMA,
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "error",
            "message": str(exc),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": result.get("status"),
                "output": str(args.output),
                "cohort_id": result.get("cohort_id"),
                "metrics": result.get("metrics"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result.get("status") == "complete" else 1


__all__ = [
    "GOLD_SOURCE_COHORT_SCHEMA",
    "audit_gold_source_cohort",
]


if __name__ == "__main__":
    raise SystemExit(main())
