"""Evaluate free-form NL2SQL against a registered governed virtual source.

Cases may be semantic-boundary candidates or bind to a frozen Gold result
contract.  Only the latter contribute to result-equivalence metrics.  Source
rows are never written to the benchmark report.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
from collections import Counter
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from dotenv import dotenv_values, load_dotenv

from .governed_virtual_nl2sql import (
    MAX_QUESTION_LENGTH,
    PROMPT_VERSION,
    SEMANTIC_IR_EXPERIMENT_PROMPT_VERSION,
    SUPPORTED_LANGUAGES,
    run_governed_virtual_nl2sql,
)

BENCHMARK_SCHEMA = "gda.free-form-nl2sql-benchmark.v1"
REPORT_SCHEMA = "gda.free-form-nl2sql-benchmark-report.v1"
CHECKPOINT_SCHEMA = "gda.free-form-nl2sql-benchmark-checkpoint.v1"
GOLD_SOURCE_COHORT_SCHEMA = "gda.nl2sql-gold-source-cohort.v1"
BENCHMARK_PROMPT_VERSION = PROMPT_VERSION
EXECUTION_PROFILES = frozenset({"baseline_sql", "semantic_ir_experimental"})
PRODUCT_EVALUATION_PROFILE = "business-language-clean-v1"
PRODUCT_TRACKS = frozenset({"warehouse", "gis", "mixed", "safety"})
PRODUCT_SPLITS = frozenset({"development", "validation", "holdout"})

_SQL_QUESTION_LEAKAGE_RE = re.compile(
    r"(?:\bselect\b|\bwhere\b|\bjoin\b|\bgroup\s+by\b|"
    r"\border\s+by\b|\bhaving\b|\blimit\b|\bunion\b|"
    r"\b(?:count|sum|avg|min|max)\s*\(|\bst_[a-z0-9_]+\s*\()",
    re.IGNORECASE,
)


class BenchmarkConfigurationError(ValueError):
    """The candidate benchmark is not safe or internally consistent."""


def _sha256_json(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkConfigurationError(f"Cannot load benchmark JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise BenchmarkConfigurationError("Benchmark JSON must be an object")
    return payload


def _load_json_artifact(
    path: Path,
    *,
    artifact_name: str,
) -> tuple[dict[str, Any], bytes, str]:
    """Load one immutable JSON input from a single byte read."""

    try:
        raw_bytes = path.read_bytes()
        payload = json.loads(raw_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BenchmarkConfigurationError(
            f"Cannot load {artifact_name} JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise BenchmarkConfigurationError(f"{artifact_name} JSON must be an object")
    return payload, raw_bytes, hashlib.sha256(raw_bytes).hexdigest()


def _assert_artifact_unchanged(
    path: Path,
    *,
    artifact_name: str,
    expected_sha256: str,
) -> None:
    """Fail the whole run when an input file changes after startup."""

    try:
        observed_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise BenchmarkConfigurationError(
            f"{artifact_name} artifact became unavailable during benchmark execution"
        ) from exc
    if observed_sha256 != expected_sha256:
        raise BenchmarkConfigurationError(
            f"{artifact_name} artifact changed during benchmark execution; "
            f"expected_sha256={expected_sha256}, observed_sha256={observed_sha256}"
        )


def _materialize_semantic_layer_snapshot(raw_bytes: bytes) -> Path:
    """Materialize the startup semantic bytes for runtime use by every case."""

    with tempfile.NamedTemporaryFile(
        mode="wb",
        prefix="gda-nl2sql-semantic-snapshot-",
        suffix=".json",
        delete=False,
    ) as handle:
        handle.write(raw_bytes)
        handle.flush()
        os.fsync(handle.fileno())
        return Path(handle.name)


def _validate_semantic_equivalence_policy(
    policy: Any,
    *,
    path: Path,
    expected_row_count: Any,
    context: str,
) -> None:
    """Validate a bounded semantic result-equivalence declaration.

    Semantic equivalence is deliberately opt-in and shape-local.  It may
    describe either a numeric tie boundary or a band summary whose labels can
    vary in presentation while counts and membership remain exact.
    """

    if policy is None:
        return
    if not isinstance(policy, dict):
        raise BenchmarkConfigurationError(
            f"{context} semantic equivalence policy is invalid: {path}"
        )
    kind = policy.get("kind")
    if kind == "all_rows_equal_numeric_boundary":
        for key in ("key_source_field", "metric_source_field"):
            value = str(policy.get(key) or "")
            if value.count(".") < 2:
                raise BenchmarkConfigurationError(
                    f"{context} semantic equivalence {key} is invalid: {path}"
                )
        boundary = policy.get("boundary_value")
        if not isinstance(boundary, (int, float)) or isinstance(boundary, bool):
            raise BenchmarkConfigurationError(
                f"{context} semantic equivalence boundary is invalid: {path}"
            )
        precision = policy.get("numeric_precision", 6)
        if not isinstance(precision, int) or not 0 <= precision <= 12:
            raise BenchmarkConfigurationError(
                f"{context} semantic equivalence precision is invalid: {path}"
            )
        if policy.get("require_unique_keys") is not True:
            raise BenchmarkConfigurationError(
                f"{context} semantic equivalence unique-key rule is required: {path}"
            )
        if not isinstance(expected_row_count, int) or expected_row_count < 1:
            raise BenchmarkConfigurationError(
                f"{context} semantic equivalence requires a non-empty result: {path}"
            )
        return
    if kind != "band_summary":
        raise BenchmarkConfigurationError(
            f"{context} semantic equivalence kind is unsupported: {path}"
        )

    band_column = str(policy.get("band_column") or "score_band").strip()
    count_column = str(policy.get("count_column") or "district_count").strip()
    if not band_column or not count_column:
        raise BenchmarkConfigurationError(
            f"{context} band summary columns are invalid: {path}"
        )
    definitions = policy.get("bands")
    if not isinstance(definitions, list) or not definitions:
        raise BenchmarkConfigurationError(
            f"{context} band summary definitions are invalid: {path}"
        )
    keys: list[str] = []
    for definition in definitions:
        if not isinstance(definition, dict):
            raise BenchmarkConfigurationError(
                f"{context} band summary definition is invalid: {path}"
            )
        key = str(definition.get("key") or "").strip().casefold()
        if not key or key in keys:
            raise BenchmarkConfigurationError(
                f"{context} band summary keys are invalid: {path}"
            )
        keys.append(key)
        aliases = definition.get("aliases") or []
        if not isinstance(aliases, list) or any(
            not str(alias).strip() for alias in aliases
        ):
            raise BenchmarkConfigurationError(
                f"{context} band summary aliases are invalid: {path}"
            )
    expected_counts = policy.get("expected_counts")
    if not isinstance(expected_counts, dict) or set(expected_counts) != set(keys):
        raise BenchmarkConfigurationError(
            f"{context} band summary expected counts are invalid: {path}"
        )
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0
        for value in expected_counts.values()
    ):
        raise BenchmarkConfigurationError(
            f"{context} band summary expected counts are invalid: {path}"
        )
    if expected_row_count != len(keys):
        raise BenchmarkConfigurationError(
            f"{context} band summary row_count must equal band count: {path}"
        )
    member_band = str(policy.get("member_band") or "").strip().casefold()
    member_column = str(policy.get("member_column") or "").strip()
    if member_band:
        if member_band not in keys or not member_column:
            raise BenchmarkConfigurationError(
                f"{context} band summary member policy is invalid: {path}"
            )
        member_hash = str(policy.get("expected_member_set_sha256") or "").strip()
        members = policy.get("expected_members")
        if member_hash:
            if not re.fullmatch(r"[0-9a-fA-F]{64}", member_hash):
                raise BenchmarkConfigurationError(
                    f"{context} band summary member fingerprint is invalid: {path}"
                )
        elif not isinstance(members, list) or any(
            not str(value).strip() for value in members
        ):
            raise BenchmarkConfigurationError(
                f"{context} band summary member contract is required: {path}"
            )
    delimiter = policy.get("delimiter", ",")
    if not isinstance(delimiter, str) or not delimiter:
        raise BenchmarkConfigurationError(
            f"{context} band summary delimiter is invalid: {path}"
        )


def _resolve_artifact_path(value: str, *, benchmark_path: Path) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    repository_candidate = Path(__file__).resolve().parents[1] / candidate
    if repository_candidate.exists():
        return repository_candidate
    return benchmark_path.parent / candidate


def _load_gold_result_contract(
    reference: dict[str, Any],
    *,
    benchmark_path: Path,
    source: dict[str, Any],
    semantic_layer: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(reference, dict):
        raise BenchmarkConfigurationError("gold_result_contract must be an object")
    path_value = str(reference.get("path") or "")
    if not path_value:
        raise BenchmarkConfigurationError("gold_result_contract.path is required")
    path = _resolve_artifact_path(path_value, benchmark_path=benchmark_path)
    try:
        payload = _load_json(path)
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise BenchmarkConfigurationError(f"Cannot read Gold result contract: {exc}") from exc
    expected_sha = str(reference.get("sha256") or "")
    actual_sha = hashlib.sha256(raw_bytes).hexdigest()
    if expected_sha and expected_sha != actual_sha:
        raise BenchmarkConfigurationError(f"Gold result contract checksum mismatch: {path}")
    if payload.get("schema") != "gda.nl2sql-gold-result-contract.v1":
        raise BenchmarkConfigurationError(f"Unsupported Gold result contract: {path}")
    contract_source = payload.get("source_contract") or {}
    if int(contract_source.get("source_id") or -1) != int(source.get("source_id") or -1):
        raise BenchmarkConfigurationError(f"Gold source_id differs from benchmark: {path}")
    if contract_source.get("database_name") != source.get("database_name"):
        raise BenchmarkConfigurationError(f"Gold database differs from benchmark: {path}")
    if str(contract_source.get("authorized_schema") or "") not in list(
        source.get("authorized_schemas") or []
    ):
        raise BenchmarkConfigurationError(f"Gold schema differs from benchmark: {path}")
    if contract_source.get("discovery_fingerprint") != source.get("discovery_fingerprint"):
        raise BenchmarkConfigurationError(f"Gold discovery fingerprint drift: {path}")
    semantic_version = str(contract_source.get("semantic_version") or "")
    compatible_semantic_versions = {
        str(semantic_layer.get("semantic_version") or ""),
        *(
            str(value)
            for value in semantic_layer.get("gold_compatible_semantic_versions") or []
        ),
    }
    if semantic_version and semantic_version not in compatible_semantic_versions:
        raise BenchmarkConfigurationError(
            f"Gold semantic version differs from semantic layer: {path}"
        )
    expected_result = payload.get("expected_result") or {}
    columns = expected_result.get("columns") or []
    fingerprint = str(expected_result.get("ordered_result_fingerprint") or "")
    row_count = expected_result.get("row_count")
    if not columns or not all(isinstance(value, str) and value for value in columns):
        raise BenchmarkConfigurationError(f"Gold result columns are missing: {path}")
    if not isinstance(row_count, int) or row_count < 0:
        raise BenchmarkConfigurationError(f"Gold result row_count is invalid: {path}")
    if len(fingerprint) != 64:
        raise BenchmarkConfigurationError(f"Gold result fingerprint is invalid: {path}")
    equivalence = payload.get("equivalence") or {}
    accepted_keys = [str(value) for value in equivalence.get("accepted_fingerprint_keys") or []]
    expected_fingerprints = {
        str(key): str(value)
        for key, value in (equivalence.get("expected_fingerprints") or {}).items()
    }
    if not accepted_keys:
        raise BenchmarkConfigurationError(f"Gold equivalence policy is missing: {path}")
    if any(
        key
        not in {
            "position_fingerprint",
            "position_numeric6_fingerprint",
            "unordered_position_fingerprint",
            "unordered_position_numeric6_fingerprint",
        }
        for key in accepted_keys
    ):
        raise BenchmarkConfigurationError(
            f"Gold equivalence policy has an unknown fingerprint: {path}"
        )
    if any(len(expected_fingerprints.get(key, "")) != 64 for key in accepted_keys):
        raise BenchmarkConfigurationError(f"Gold equivalence fingerprints are missing: {path}")
    semantic_equivalence = payload.get("semantic_equivalence")
    _validate_semantic_equivalence_policy(
        semantic_equivalence,
        path=path,
        expected_row_count=expected_result.get("row_count"),
        context="Gold",
    )
    accepted_result_variants: list[dict[str, Any]] = []
    seen_variant_ids: set[str] = set()
    raw_variants = payload.get("accepted_result_variants") or []
    if not isinstance(raw_variants, list):
        raise BenchmarkConfigurationError(
            f"Gold accepted result variants are invalid: {path}"
        )
    for index, variant in enumerate(raw_variants):
        if not isinstance(variant, dict):
            raise BenchmarkConfigurationError(
                f"Gold accepted result variant is invalid: {path}:{index}"
            )
        variant_id = str(variant.get("variant_id") or "").strip()
        rationale = str(variant.get("rationale") or "").strip()
        if not variant_id or variant_id in seen_variant_ids or not rationale:
            raise BenchmarkConfigurationError(
                f"Gold accepted result variant identity is invalid: {path}:{index}"
            )
        seen_variant_ids.add(variant_id)
        variant_expected = variant.get("expected_result") or {}
        variant_columns = variant_expected.get("columns") or []
        variant_row_count = variant_expected.get("row_count")
        variant_fingerprint = str(
            variant_expected.get("ordered_result_fingerprint") or ""
        )
        if not variant_columns or not all(
            isinstance(value, str) and value for value in variant_columns
        ):
            raise BenchmarkConfigurationError(
                f"Gold accepted result variant columns are missing: {path}:{variant_id}"
            )
        if not isinstance(variant_row_count, int) or variant_row_count < 0:
            raise BenchmarkConfigurationError(
                f"Gold accepted result variant row_count is invalid: {path}:{variant_id}"
            )
        if len(variant_fingerprint) != 64:
            raise BenchmarkConfigurationError(
                f"Gold accepted result variant fingerprint is invalid: {path}:{variant_id}"
            )
        variant_equivalence = variant.get("equivalence") or {}
        variant_keys = [
            str(value)
            for value in variant_equivalence.get("accepted_fingerprint_keys") or []
        ]
        variant_fingerprints = {
            str(key): str(value)
            for key, value in (
                variant_equivalence.get("expected_fingerprints") or {}
            ).items()
        }
        if not variant_keys or any(
            key
            not in {
                "position_fingerprint",
                "position_numeric6_fingerprint",
                "unordered_position_fingerprint",
                "unordered_position_numeric6_fingerprint",
            }
            for key in variant_keys
        ):
            raise BenchmarkConfigurationError(
                f"Gold accepted result variant equivalence is invalid: {path}:{variant_id}"
            )
        if any(
            len(variant_fingerprints.get(key, "")) != 64 for key in variant_keys
        ):
            raise BenchmarkConfigurationError(
                f"Gold accepted result variant fingerprints are missing: {path}:{variant_id}"
            )
        variant_semantic_equivalence = variant.get("semantic_equivalence")
        _validate_semantic_equivalence_policy(
            variant_semantic_equivalence,
            path=path,
            expected_row_count=variant_row_count,
            context=f"Gold accepted result variant {variant_id}",
        )
        accepted_result_variants.append(
            {
                "variant_id": variant_id,
                "rationale": rationale,
                "expected_result": {
                    "columns": [str(value) for value in variant_columns],
                    "row_count": variant_row_count,
                    "ordered_result_fingerprint": variant_fingerprint,
                },
                "equivalence": {
                    "accepted_fingerprint_keys": variant_keys,
                    "expected_fingerprints": variant_fingerprints,
                    "order_sensitive": bool(
                        variant_equivalence.get("order_sensitive", True)
                    ),
                    "column_aliases_compare_by_position": bool(
                        variant_equivalence.get(
                            "column_aliases_compare_by_position", False
                        )
                    ),
                },
                "semantic_equivalence": copy.deepcopy(variant_semantic_equivalence),
            }
        )
    result = {
        "path": str(path),
        "sha256": actual_sha,
        "contract_id": str(payload.get("contract_id") or ""),
        "expected_result": {
            "columns": [str(value) for value in columns],
            "row_count": row_count,
            "ordered_result_fingerprint": fingerprint,
        },
        "equivalence": {
            "accepted_fingerprint_keys": accepted_keys,
            "expected_fingerprints": expected_fingerprints,
            "order_sensitive": bool(equivalence.get("order_sensitive", True)),
            "column_aliases_compare_by_position": bool(
                equivalence.get("column_aliases_compare_by_position", False)
            ),
        },
        "semantic_equivalence": copy.deepcopy(semantic_equivalence),
        "accepted_result_variants": accepted_result_variants,
        "payload": payload,
    }
    return result


def _load_gold_source_cohort(
    path: Path,
    *,
    benchmark: dict[str, Any],
    semantic_layer: dict[str, Any],
    binding: dict[str, Any],
    source_id: int,
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Load independently observed Gold freshness evidence fail-closed."""

    cohort_path = path.expanduser().resolve()
    try:
        payload = json.loads(cohort_path.read_text(encoding="utf-8"))
        artifact_sha256 = hashlib.sha256(cohort_path.read_bytes()).hexdigest()
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkConfigurationError(
            f"Cannot load Gold source cohort JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict) or payload.get("schema") != GOLD_SOURCE_COHORT_SCHEMA:
        raise BenchmarkConfigurationError("Unsupported Gold source cohort schema")
    if payload.get("status") != "complete":
        raise BenchmarkConfigurationError("Gold source cohort must be complete")

    source = payload.get("source") or {}
    expected_source = {
        "source_id": source_id,
        "database_name": binding.get("database_name"),
        "authorized_schemas": list(binding.get("allowed_schemas") or []),
        "discovery_fingerprint": binding.get("discovery_fingerprint"),
        "profile_fingerprint": binding.get("profile_fingerprint"),
    }
    for key, expected in expected_source.items():
        observed = source.get(key)
        if key == "source_id":
            try:
                observed = int(observed)
            except (TypeError, ValueError):
                observed = -1
        if observed != expected:
            raise BenchmarkConfigurationError(
                f"Gold source cohort {key} differs from the selected source"
            )
    registration_fingerprint = str(source.get("source_registration_fingerprint") or "")
    if len(registration_fingerprint) != 64:
        raise BenchmarkConfigurationError(
            "Gold source cohort registration fingerprint is invalid"
        )

    inputs = payload.get("inputs") or {}
    benchmark_sha256 = _sha256_json(benchmark)
    semantic_layer_sha256 = _sha256_json(semantic_layer)
    if inputs.get("benchmark_sha256") != benchmark_sha256:
        raise BenchmarkConfigurationError(
            "Gold source cohort benchmark checksum differs"
        )
    if inputs.get("semantic_layer_sha256") != semantic_layer_sha256:
        raise BenchmarkConfigurationError(
            "Gold source cohort semantic layer checksum differs"
        )

    raw_observations = payload.get("observations")
    if not isinstance(raw_observations, list) or not raw_observations:
        raise BenchmarkConfigurationError(
            "Gold source cohort observations must be a non-empty list"
        )
    observations: dict[str, dict[str, Any]] = {}
    cohort_basis_observations: list[dict[str, Any]] = []
    for item in raw_observations:
        if not isinstance(item, dict):
            raise BenchmarkConfigurationError(
                "Gold source cohort contains an invalid observation"
            )
        contract_id = str(item.get("contract_id") or "")
        if not contract_id or contract_id in observations:
            raise BenchmarkConfigurationError(
                f"Gold source cohort has duplicate or empty contract_id: {contract_id}"
            )
        status = str(item.get("status") or "")
        if status not in {"current", "gold_stale_source_result"}:
            raise BenchmarkConfigurationError(
                f"Gold source cohort observation is not evaluable: {contract_id}"
            )
        for key in ("gold_contract_sha256", "query_sha256"):
            if len(str(item.get(key) or "")) != 64:
                raise BenchmarkConfigurationError(
                    f"Gold source cohort {key} is invalid: {contract_id}"
                )
        current = item.get("current")
        if not isinstance(current, dict):
            raise BenchmarkConfigurationError(
                f"Gold source cohort current result is missing: {contract_id}"
            )
        if not isinstance(current.get("columns"), list) or not isinstance(
            current.get("row_count"), int
        ):
            raise BenchmarkConfigurationError(
                f"Gold source cohort current result is invalid: {contract_id}"
            )
        if len(str(current.get("ordered_result_fingerprint") or "")) != 64:
            raise BenchmarkConfigurationError(
                f"Gold source cohort result fingerprint is invalid: {contract_id}"
            )
        observations[contract_id] = item
        cohort_basis_observations.append(
            {
                "contract_id": contract_id,
                "status": status,
                "gold_contract_sha256": item.get("gold_contract_sha256"),
                "query_sha256": item.get("query_sha256"),
                "current": current,
            }
        )

    expected_cohort_id = _sha256_json(
        {
            "source_registration_fingerprint": registration_fingerprint,
            "benchmark_sha256": benchmark_sha256,
            "semantic_layer_sha256": semantic_layer_sha256,
            "observations": cohort_basis_observations,
        }
    )
    if payload.get("cohort_id") != expected_cohort_id:
        raise BenchmarkConfigurationError("Gold source cohort identity is invalid")

    selected_contracts: dict[str, dict[str, Any]] = {}
    for case in cases:
        gold = (case.get("expected") or {}).get("gold_result_contract")
        if not gold:
            continue
        contract_id = str(gold.get("contract_id") or "")
        if not contract_id:
            raise BenchmarkConfigurationError(
                f"Selected Gold contract has no contract_id: {case['case_id']}"
            )
        prior = selected_contracts.setdefault(contract_id, gold)
        if prior.get("sha256") != gold.get("sha256"):
            raise BenchmarkConfigurationError(
                f"Selected cases disagree on Gold contract checksum: {contract_id}"
            )
    missing = sorted(set(selected_contracts) - set(observations))
    if missing:
        raise BenchmarkConfigurationError(
            "Gold source cohort lacks selected contract evidence: " + ", ".join(missing)
        )
    for contract_id, gold in selected_contracts.items():
        observation = observations[contract_id]
        if observation.get("gold_contract_sha256") != gold.get("sha256"):
            raise BenchmarkConfigurationError(
                f"Gold source cohort contract checksum differs: {contract_id}"
            )
        expected_query_sha256 = str(
            ((gold.get("payload") or {}).get("query") or {}).get("sha256") or ""
        )
        if len(expected_query_sha256) != 64:
            raise BenchmarkConfigurationError(
                f"Gold contract query checksum is missing: {contract_id}"
            )
        if observation.get("query_sha256") != expected_query_sha256:
            raise BenchmarkConfigurationError(
                f"Gold source cohort query checksum differs: {contract_id}"
            )
        expected_equivalence = gold.get("equivalence") or {}
        current_equivalence = (observation.get("current") or {}).get(
            "equivalence_fingerprints"
        ) or {}
        equivalent = any(
            current_equivalence.get(key)
            == (expected_equivalence.get("expected_fingerprints") or {}).get(key)
            for key in expected_equivalence.get("accepted_fingerprint_keys") or []
        )
        expected_status = "current" if equivalent else "gold_stale_source_result"
        if observation.get("status") != expected_status:
            raise BenchmarkConfigurationError(
                f"Gold source cohort status contradicts its fingerprints: {contract_id}"
            )

    selected_observations = {
        contract_id: observations[contract_id]
        for contract_id in sorted(selected_contracts)
    }
    status_counts = Counter(
        str(item["status"]) for item in selected_observations.values()
    )
    return {
        "path": str(cohort_path),
        "artifact_sha256": artifact_sha256,
        "cohort_id": expected_cohort_id,
        "generated_at": payload.get("generated_at"),
        "source_registration_fingerprint": registration_fingerprint,
        "selected_contract_count": len(selected_observations),
        "status_counts": dict(sorted(status_counts.items())),
        "observations": selected_observations,
        "source_rows_persisted": False,
    }


@lru_cache(maxsize=8192)
def _identifier_pattern(identifier: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?<![a-z0-9_$]){re.escape(identifier)}(?![a-z0-9_$])",
        re.IGNORECASE,
    )


def _contains_identifier(question: str, identifier: str) -> bool:
    """Match a physical identifier without flagging ordinary business words."""

    normalized_identifier = identifier.casefold().strip()
    if not normalized_identifier:
        return False
    return bool(_identifier_pattern(normalized_identifier).search(question.casefold()))


def _normalize_benchmark_question(value: str) -> str:
    """Normalize only presentation noise for benchmark input diagnostics."""

    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(normalized.split())


def _benchmark_input_ambiguities(
    cases: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Find identical prompts whose Gold contracts disagree.

    This is deliberately a static benchmark-quality check.  It does not infer
    whether one answer is more likely than another and never uses model output.
    """

    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for case in cases:
        key = (
            str(case.get("language") or ""),
            _normalize_benchmark_question(str(case.get("question") or "")),
        )
        groups.setdefault(key, []).append(case)

    conflicts: list[dict[str, Any]] = []
    by_case_id: dict[str, dict[str, Any]] = {}
    for (language, normalized_question), grouped in groups.items():
        signatures: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        for case in grouped:
            expected = case.get("expected") or {}
            signature = (
                str(expected.get("status") or "ok"),
                tuple(sorted(str(value) for value in expected.get("tables") or [])),
                tuple(
                    tuple(sorted(str(value) for value in values))
                    for values in expected.get("allowed_table_sets") or []
                ),
            )
            signatures.setdefault(signature, []).append(case)
        if len(signatures) <= 1:
            continue
        detail = {
            "language": language,
            "normalized_question": normalized_question,
            "case_ids": sorted(str(case["case_id"]) for case in grouped),
            "targets": [
                {
                    "status": signature[0],
                    "tables": list(signature[1]),
                    "allowed_table_sets": [list(values) for values in signature[2]],
                    "case_ids": sorted(str(case["case_id"]) for case in members),
                }
                for signature, members in sorted(
                    signatures.items(), key=lambda item: repr(item[0])
                )
            ],
        }
        conflicts.append(detail)
        for case in grouped:
            by_case_id[str(case["case_id"])] = detail
    conflicts.sort(key=lambda item: (item["language"], item["normalized_question"]))
    return conflicts, by_case_id


def _validate_product_evaluation_profile(
    benchmark: dict[str, Any],
    semantic_layer: dict[str, Any],
) -> dict[str, Any] | None:
    profile = benchmark.get("evaluation_profile")
    if profile is None:
        return None
    if not isinstance(profile, dict) or profile.get("profile_id") != PRODUCT_EVALUATION_PROFILE:
        raise BenchmarkConfigurationError("Unsupported product evaluation profile")
    if profile.get("status") != "frozen":
        raise BenchmarkConfigurationError("Product evaluation profile must be frozen")

    isolation = profile.get("isolation") or {}
    required_isolation = {
        "questions_used_in_runtime_prompts": False,
        "gold_sql_available_to_runtime": False,
        "gold_results_available_to_runtime": False,
        "benchmark_generated_from_runtime_contracts": False,
    }
    for key, expected in required_isolation.items():
        if isolation.get(key) is not expected:
            raise BenchmarkConfigurationError(
                f"Product evaluation isolation contract is invalid: {key}"
            )

    tables = {
        str(binding.get("physical_table") or "").casefold()
        for binding in semantic_layer.get("table_bindings") or []
        if binding.get("physical_table")
    }
    reviewed_business_terms = {
        re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()
        for asset in semantic_layer.get("semantic_assets") or []
        if isinstance(asset, dict)
        for value in [
            *((asset.get("labels") or {}).values()),
            *(asset.get("aliases") or []),
        ]
        if str(value or "").strip()
    }
    # A source can legitimately have a one-word physical table such as
    # ``well`` whose reviewed business label is the same ordinary word.  A
    # natural phrase like "as well" is not technical leakage.  Qualified and
    # prefixed identifiers remain forbidden; only dictionary-reviewed exact
    # business-word collisions are removed from the bare-name check.
    normalized_reviewed_terms = {
        re.sub(r"[^a-z0-9]+", " ", term).strip()
        for term in reviewed_business_terms
    }
    bare_table_identifiers = set()
    for value in tables:
        identifier = re.sub(r"[^a-z0-9]+", " ", value.split(".", 1)[-1].casefold()).strip()
        if not any(
            identifier == term or f" {identifier} " in f" {term} "
            for term in normalized_reviewed_terms
        ):
            bare_table_identifiers.add(value.split(".", 1)[-1])
    table_identifiers = tables | bare_table_identifiers
    technical_field_identifiers = {
        str(field.get("physical_field") or "").casefold()
        for binding in semantic_layer.get("table_bindings") or []
        for field in binding.get("fields") or []
        if "_" in str(field.get("physical_field") or "")
    }
    semantic_text = json.dumps(
        semantic_layer,
        ensure_ascii=False,
        sort_keys=True,
    ).casefold()

    cases = benchmark.get("cases") or []
    split_counts: Counter[str] = Counter()
    track_counts: Counter[str] = Counter()
    eligible_split_counts: Counter[str] = Counter()
    eligible_track_counts: Counter[str] = Counter()
    for case in cases:
        case_id = str(case.get("case_id") or "")
        question = str(case.get("question") or "").strip()
        track = str(case.get("track") or "")
        split = str(case.get("split") or "")
        provenance = case.get("provenance") or {}
        if track not in PRODUCT_TRACKS:
            raise BenchmarkConfigurationError(
                f"Case {case_id} has unsupported product track: {track}"
            )
        if split not in PRODUCT_SPLITS:
            raise BenchmarkConfigurationError(
                f"Case {case_id} has unsupported evaluation split: {split}"
            )
        if provenance.get("kind") not in {
            "customer_dictionary_business_scenario",
            "customer_workflow",
            "security_contract",
            "technical_catalog",
        }:
            raise BenchmarkConfigurationError(
                f"Case {case_id} has untrusted benchmark provenance"
            )
        if provenance.get("used_for_prompt_or_runtime_assets") is not False:
            raise BenchmarkConfigurationError(
                f"Case {case_id} is not isolated from runtime assets"
            )
        expected = case.get("expected") or {}
        split_counts[split] += 1
        track_counts[track] += 1
        if case.get("business_language_eligible") is False and expected.get("status") == "ok":
            # Catalog coverage cases are retained for table-resolution and
            # execution coverage, but are excluded from the clean business
            # language claim because their source dictionary has no reviewed
            # business label yet.
            continue
        eligible_split_counts[split] += 1
        eligible_track_counts[track] += 1
        if (
            expected.get("status") == "ok"
            and not (expected.get("gold_result_contract") or {}).get("path")
        ):
            raise BenchmarkConfigurationError(
                f"Product case {case_id} requires a frozen Gold result contract"
            )
        # Safety cases deliberately contain the prohibited action or SQL
        # keyword (for example ``Join``) to verify refusal behavior.  They are
        # not business-language questions and must be excluded from the
        # business wording leakage checks below.
        if expected.get("status") == "rejected":
            continue
        if re.search(r"\b[a-z_][a-z0-9_$]*\.[a-z_][a-z0-9_$]*\b", question, re.I):
            raise BenchmarkConfigurationError(
                f"Case {case_id} leaks a schema-qualified identifier"
            )
        leaked_table = next(
            (
                identifier
                for identifier in sorted(table_identifiers, key=len, reverse=True)
                if _contains_identifier(question, identifier)
            ),
            None,
        )
        if leaked_table:
            raise BenchmarkConfigurationError(
                f"Case {case_id} leaks physical table identifier: {leaked_table}"
            )
        leaked_field = next(
            (
                identifier
                for identifier in sorted(
                    technical_field_identifiers,
                    key=len,
                    reverse=True,
                )
                if _contains_identifier(question, identifier)
            ),
            None,
        )
        if leaked_field:
            raise BenchmarkConfigurationError(
                f"Case {case_id} leaks technical field identifier: {leaked_field}"
            )
        if _SQL_QUESTION_LEAKAGE_RE.search(question):
            raise BenchmarkConfigurationError(
                f"Case {case_id} leaks SQL syntax or function names"
            )
        if case_id and case_id.casefold() in semantic_text:
            raise BenchmarkConfigurationError(
                f"Case {case_id} is present in the runtime semantic layer"
            )
        if len(question) >= 24 and question.casefold() in semantic_text:
            raise BenchmarkConfigurationError(
                f"Case {case_id} question is present in the runtime semantic layer"
            )

    if not split_counts.get("holdout"):
        raise BenchmarkConfigurationError("Product benchmark must contain holdout cases")
    return {
        "profile_id": PRODUCT_EVALUATION_PROFILE,
        "status": "frozen",
        "isolation": dict(isolation),
        "split_counts": dict(sorted(split_counts.items())),
        "track_counts": dict(sorted(track_counts.items())),
        "business_language_case_count": sum(eligible_split_counts.values()),
        "business_language_split_counts": dict(sorted(eligible_split_counts.items())),
        "business_language_track_counts": dict(sorted(eligible_track_counts.items())),
        "leakage_check_passed": True,
    }


def _product_gold_coverage_complete(cases: list[dict[str, Any]]) -> bool:
    """Require Gold only for queries admitted to the product accuracy claim."""

    eligible_queries = [
        case
        for case in cases
        if (case.get("expected") or {}).get("status") == "ok"
        and case.get("business_language_eligible") is not False
    ]
    return bool(eligible_queries) and all(
        ((case.get("expected") or {}).get("gold_result_contract") or {}).get("path")
        for case in eligible_queries
    )


def _redact_error(value: Any) -> str:
    message = str(value)
    for name in (
        "OPENAI_API_KEY",
        "GDA_LLM_API_KEY",
        "GDA_VSOURCE_PASSWORD",
        "CHAINLIT_AUTH_SECRET",
        "GDA_CONTROL_PLANE_ENCRYPTION_SECRET",
    ):
        secret = os.environ.get(name, "")
        if secret:
            message = message.replace(secret, "[REDACTED]")
    message = re.sub(r"(://[^:/\s]+:)[^@/\s]+@", r"\1[REDACTED]@", message)
    return message[:500]


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write a JSON artifact without exposing a partially written checkpoint."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = handle.name
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path:
            try:
                Path(temporary_path).unlink()
            except FileNotFoundError:
                pass


def _benchmark_checkpoint_identity(
    *,
    benchmark: dict[str, Any],
    semantic_layer: dict[str, Any],
    binding: dict[str, Any],
    cases: list[dict[str, Any]],
    source_id: int,
    model_name: str,
    reasoning_effort: str,
    timeout_seconds: int,
    request_interval_seconds: float,
    max_concurrency: int,
    execution_profile: str,
    benchmark_artifact_sha256: str,
    semantic_layer_artifact_sha256: str,
    gold_source_cohort: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the immutable inputs that make a case result reproducible.

    Checkpoints intentionally bind to the normalized JSON objects loaded by
    the runner rather than file mtimes or paths.  A copied checkpoint can
    therefore be resumed on another host, but only when every semantic,
    source, model, route, and selection input is identical.
    """

    prompt_version = (
        SEMANTIC_IR_EXPERIMENT_PROMPT_VERSION
        if execution_profile == "semantic_ir_experimental"
        else BENCHMARK_PROMPT_VERSION
    )
    identity = {
        "benchmark_sha256": _sha256_json(benchmark),
        "semantic_layer_sha256": _sha256_json(semantic_layer),
        "artifact_files": {
            "benchmark_bytes_sha256": benchmark_artifact_sha256,
            "semantic_layer_bytes_sha256": semantic_layer_artifact_sha256,
        },
        "semantic_layer_version": semantic_layer.get("semantic_version"),
        "source": {
            "source_id": source_id,
            "database_name": binding.get("database_name"),
            "authorized_schemas": list(binding.get("allowed_schemas") or []),
            "discovery_fingerprint": binding.get("discovery_fingerprint"),
            "profile_fingerprint": binding.get("profile_fingerprint"),
        },
        "model": {
            "requested": model_name,
            "reasoning_effort": reasoning_effort,
        },
        "execution_profile": execution_profile,
        "prompt_version": prompt_version,
        "runtime": {
            "timeout_seconds": timeout_seconds,
            "request_interval_seconds": request_interval_seconds,
            "max_concurrency": max_concurrency,
        },
        "selection": {
            "case_ids": [str(case["case_id"]) for case in cases],
            "splits": sorted({str(case.get("split")) for case in cases}),
        },
    }
    if gold_source_cohort is not None:
        identity["gold_source_cohort"] = {
            "cohort_id": gold_source_cohort["cohort_id"],
            "artifact_sha256": gold_source_cohort["artifact_sha256"],
        }
    return identity


def _checkpoint_report_resumable(report: Any) -> bool:
    """Return whether a prior case result is safe to reuse.

    Only a passed case (or a static benchmark-input ambiguity) is reused. A
    failed business/safety case is deliberately retried so a resume cannot
    turn a transient or model-variance failure into permanent evidence. Any
    provider/source outage is also retried because it is infrastructure
    evidence, not an evaluated answer.
    """

    if not isinstance(report, dict) or report.get("status") != "passed":
        return False
    return True


def _load_benchmark_checkpoint(
    path: Path,
    *,
    identity: dict[str, Any],
    cases: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Load and strictly validate a per-case checkpoint."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkConfigurationError(f"Cannot load benchmark checkpoint: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != CHECKPOINT_SCHEMA:
        raise BenchmarkConfigurationError("Unsupported benchmark checkpoint schema")
    if payload.get("identity") != identity:
        raise BenchmarkConfigurationError(
            "Benchmark checkpoint identity mismatch; refusing mixed benchmark results"
        )
    raw_records = payload.get("cases")
    if not isinstance(raw_records, list):
        raise BenchmarkConfigurationError("Benchmark checkpoint cases must be a list")
    expected_cases = {str(case["case_id"]): case for case in cases}
    loaded: dict[str, dict[str, Any]] = {}
    for record in raw_records:
        if not isinstance(record, dict):
            raise BenchmarkConfigurationError(
                "Benchmark checkpoint contains an invalid case record"
            )
        case_id = str(record.get("case_id") or "")
        if case_id in loaded:
            raise BenchmarkConfigurationError(
                f"Benchmark checkpoint contains duplicate case: {case_id}"
            )
        case = expected_cases.get(case_id)
        if case is None:
            raise BenchmarkConfigurationError(
                f"Benchmark checkpoint contains case outside the selected benchmark: {case_id}"
            )
        if record.get("case_sha256") != _sha256_json(case):
            raise BenchmarkConfigurationError(
                f"Benchmark checkpoint case definition mismatch: {case_id}"
            )
        report = record.get("report")
        if (
            not isinstance(report, dict)
            or report.get("status") not in {"passed", "failed"}
            or not isinstance(report.get("checks"), dict)
            or not isinstance(report.get("observed"), dict)
            or not isinstance(report.get("failure_reasons"), list)
        ):
            raise BenchmarkConfigurationError(
                f"Benchmark checkpoint contains a corrupt case report: {case_id}"
            )
        if report.get("case_id") != case_id:
            raise BenchmarkConfigurationError(
                f"Benchmark checkpoint report case_id mismatch: {case_id}"
            )
        if _checkpoint_report_resumable(report):
            loaded[case_id] = report
    return loaded


def _write_benchmark_checkpoint(
    path: Path,
    *,
    identity: dict[str, Any],
    cases: list[dict[str, Any]],
    case_reports: list[dict[str, Any] | None],
    status: Literal["running", "completed", "aborted"],
    started_at: str,
    resumed: bool,
    final_report_sha256: str | None = None,
    abort_reason: str | None = None,
) -> None:
    records = [
        {
            "case_id": str(case["case_id"]),
            "case_sha256": _sha256_json(case),
            "report": report,
        }
        for case, report in zip(cases, case_reports, strict=True)
        if report is not None
    ]
    payload: dict[str, Any] = {
        "schema": CHECKPOINT_SCHEMA,
        "version": "1.0.0",
        "status": status,
        "started_at": started_at,
        "updated_at": datetime.now(UTC).isoformat(),
        "resumed": resumed,
        "identity": identity,
        "completed_case_count": len(records),
        "total_case_count": len(cases),
        "cases": records,
    }
    if final_report_sha256:
        payload["final_report_sha256"] = final_report_sha256
    if abort_reason:
        payload["abort_reason"] = abort_reason
    _atomic_write_json(path, payload)


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _semantic_plan_route(plan: dict[str, Any]) -> str:
    """Return the stable planning route for baseline and candidate reports."""

    semantic_ir = plan.get("semantic_ir") or {}
    if isinstance(semantic_ir, dict) and semantic_ir.get("route"):
        return str(semantic_ir["route"])
    if plan.get("schema_id") == "gda.compiled_ad_hoc_semantic_plan.v1":
        if plan.get("authority"):
            return str(plan["authority"])
        physical_plan = plan.get("physical_plan") or {}
        if isinstance(physical_plan, dict) and physical_plan.get("compilation_mode"):
            return str(physical_plan["compilation_mode"])
    return "unknown"


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int((percentile * len(ordered) + 99) // 100)))
    return round(ordered[rank - 1], 3)


def _failure_class(case_report: dict[str, Any]) -> str | None:
    if case_report.get("status") == "passed":
        return None
    if (case_report.get("checks") or {}).get("benchmark_input_unambiguous") is False:
        return "benchmark_input_ambiguous"
    observed = case_report.get("observed") or {}
    error = str(observed.get("error") or case_report.get("error") or "").casefold()
    if "governed_virtual_query_failed" in error and any(
        token in error
        for token in ("connection", "timeout", "temporarily unavailable", "server closed")
    ):
        return "virtual_source_unavailable"
    if any(
        token in error
        for token in (
            "apiconnectionerror",
            "clientproxyconnectionerror",
            "connection error",
            "authenticationerror",
            "api_key_invalid",
            "invalid api key",
            "api key invalid",
            "api key 无效",
            "unauthorized",
            "proxyerror",
            "api_key_limit_exceeded",
            "quota exceeded",
            "resource exhausted",
            "rate limit",
            "429",
            "401",
        )
    ):
        return "model_provider_unavailable"
    if observed.get("status") == "error":
        return "product_execution_error"
    checks = case_report.get("checks") or {}
    if checks.get("status_match") is False and observed.get("status") == "rejected":
        return "unexpected_refusal"
    if checks.get("gold_result_equivalence_match") is False:
        if case_report.get("gold_source_status") == "gold_stale_source_result":
            return "gold_stale_source_result"
        return "gold_result_mismatch"
    return "contract_check_failure"


def _evaluation_bucket(case: dict[str, Any]) -> str:
    """Classify a case by what its score is allowed to claim.

    Technical catalog cases exercise metadata/table-resolution coverage but do
    not establish business-language accuracy until their source semantics have
    been reviewed. Business clarification, data-unavailable handling, and
    security refusal are separate product properties and must not be collapsed
    into one apparently high "safety" score.
    """

    expected = case.get("expected") or {}
    if str(expected.get("status") or "ok") == "rejected":
        rejection_kind = str(expected.get("rejection_kind") or "").casefold()
        if rejection_kind == "clarification_required":
            return "business_clarification"
        if rejection_kind in {
            "data_unavailable",
            "data_unavailable_or_safe_refusal",
        }:
            return "data_unavailable"
        return "safety"
    if case.get("business_language_eligible") is False:
        return "technical_catalog_control"
    return "business_language"


def _benchmark_ambiguity_case_report(case: dict[str, Any]) -> dict[str, Any]:
    """Return a non-scored failure for a contradictory benchmark input."""

    detail = case["benchmark_input_ambiguity"]
    return {
        "case_id": case["case_id"],
        "language": case["language"],
        "question": case["question"],
        "business_language_eligible": case.get("business_language_eligible") is not False,
        "evaluation_bucket": _evaluation_bucket(case),
        "provenance_kind": (case.get("provenance") or {}).get("kind"),
        **({"track": case["track"]} if case.get("track") else {}),
        **({"split": case["split"]} if case.get("split") else {}),
        **(
            {"capabilities": list(case["capabilities"])}
            if case.get("capabilities")
            else {}
        ),
        "status": "failed",
        "checks": {"benchmark_input_unambiguous": False},
        "observed": {
            "status": "not_evaluated",
            "source_rows_persisted": False,
            "reason": "identical_benchmark_input_has_conflicting_gold_targets",
        },
        "benchmark_input_ambiguity": detail,
        "failure_reasons": ["benchmark_input_unambiguous"],
        "diagnostic_differences": [],
        "planning_differences": [],
        "failure_class": "benchmark_input_ambiguous",
    }


def _apply_gold_source_evaluation(
    report: dict[str, Any],
    case: dict[str, Any],
    gold_source_cohort: dict[str, Any] | None,
) -> dict[str, Any]:
    """Attach row-free Gold freshness evidence without changing strict checks."""

    gold = (case.get("expected") or {}).get("gold_result_contract")
    if not gold:
        report["gold_source_status"] = "not_applicable"
        report["evaluation_exclusion_reason"] = None
        return report
    if gold_source_cohort is None:
        report["gold_source_status"] = "not_audited"
        report["evaluation_exclusion_reason"] = None
        return report
    contract_id = str(gold.get("contract_id") or "")
    observation = gold_source_cohort["observations"][contract_id]
    status = str(observation["status"])
    report["gold_source_status"] = status
    report["evaluation_exclusion_reason"] = (
        "gold_stale_source_result"
        if status == "gold_stale_source_result"
        else None
    )
    if (
        status == "gold_stale_source_result"
        and report.get("failure_class") == "gold_result_mismatch"
    ):
        report["failure_class"] = "gold_stale_source_result"
    return report


def _validate_benchmark(
    benchmark: dict[str, Any],
    semantic_layer: dict[str, Any],
    *,
    source_id: int,
    benchmark_path: Path | None = None,
) -> list[dict[str, Any]]:
    if benchmark.get("schema") != BENCHMARK_SCHEMA:
        raise BenchmarkConfigurationError("Unsupported free-form benchmark schema")
    if semantic_layer.get("schema") != "gda.multilingual-virtual-semantic-layer.v1":
        raise BenchmarkConfigurationError("Unsupported semantic layer schema")
    _validate_product_evaluation_profile(benchmark, semantic_layer)

    source = benchmark.get("source") or {}
    binding = semantic_layer.get("source_binding") or {}
    if int(source.get("source_id") or -1) != source_id:
        raise BenchmarkConfigurationError("Benchmark source_id does not match the requested source")
    if int(binding.get("source_id") or -1) != source_id:
        raise BenchmarkConfigurationError(
            "Semantic layer source_id does not match the requested source"
        )
    for key in ("database_name", "discovery_fingerprint"):
        if source.get(key) != binding.get(key):
            raise BenchmarkConfigurationError(f"Benchmark and semantic layer {key} differ")
    expected_schemas = list(binding.get("allowed_schemas") or [])
    if list(source.get("authorized_schemas") or []) != expected_schemas:
        raise BenchmarkConfigurationError("Benchmark schema scope differs from the semantic layer")

    table_names = {
        str(item.get("physical_table")) for item in semantic_layer.get("table_bindings") or []
    }
    cases = benchmark.get("cases") or []
    if not cases:
        raise BenchmarkConfigurationError("Benchmark must contain at least one case")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    benchmark_source = {
        "source_id": source_id,
        "database_name": source.get("database_name"),
        "authorized_schemas": list(source.get("authorized_schemas") or []),
        "discovery_fingerprint": source.get("discovery_fingerprint"),
    }
    resolved_benchmark_path = benchmark_path or Path.cwd() / "benchmark.json"
    for case in cases:
        if not isinstance(case, dict):
            raise BenchmarkConfigurationError("Benchmark cases must be objects")
        case_id = str(case.get("case_id") or "")
        if not case_id or case_id in seen:
            raise BenchmarkConfigurationError(f"Duplicate or empty case_id: {case_id}")
        seen.add(case_id)
        language = str(case.get("language") or "")
        if language not in SUPPORTED_LANGUAGES:
            raise BenchmarkConfigurationError(f"Unsupported case language: {language}")
        question = str(case.get("question") or "").strip()
        if not question or len(question) > MAX_QUESTION_LENGTH:
            raise BenchmarkConfigurationError(
                f"Case {case_id} question must be 1-{MAX_QUESTION_LENGTH} characters"
            )
        expected = case.get("expected") or {}
        expected_status = str(expected.get("status") or "ok")
        if expected_status not in {"ok", "rejected"}:
            raise BenchmarkConfigurationError(
                f"Case {case_id} expected.status must be ok or rejected"
            )
        expected_tables = [str(value) for value in expected.get("tables") or []]
        raw_allowed_table_sets = expected.get("allowed_table_sets") or []
        if not isinstance(raw_allowed_table_sets, list) or any(
            not isinstance(values, list) or not values for values in raw_allowed_table_sets
        ):
            raise BenchmarkConfigurationError(
                f"Case {case_id} allowed_table_sets must contain non-empty lists"
            )
        allowed_table_sets = [[str(value) for value in values] for values in raw_allowed_table_sets]
        all_expected_tables = set(expected_tables)
        for values in allowed_table_sets:
            all_expected_tables.update(values)
        unknown_tables = sorted(all_expected_tables - table_names)
        if unknown_tables:
            raise BenchmarkConfigurationError(
                f"Case {case_id} references tables outside the semantic layer: "
                + ", ".join(unknown_tables)
            )
        if expected_status == "ok" and not (expected_tables or allowed_table_sets):
            raise BenchmarkConfigurationError(
                f"Case {case_id} must declare expected or allowed tables for an ok case"
            )
        gold_reference = expected.get("gold_result_contract")
        normalized_gold = None
        if gold_reference is not None:
            if expected_status != "ok":
                raise BenchmarkConfigurationError(
                    f"Case {case_id} cannot attach a Gold result to a rejected case"
                )
            normalized_gold = _load_gold_result_contract(
                gold_reference,
                benchmark_path=resolved_benchmark_path,
                source=benchmark_source,
                semantic_layer=semantic_layer,
            )
        normalized.append(
            {
                **case,
                "case_id": case_id,
                "language": language,
                "question": question,
                "track": str(case.get("track") or ""),
                "split": str(case.get("split") or ""),
                "capabilities": [
                    str(value) for value in case.get("capabilities") or []
                ],
                "expected": {
                    **expected,
                    "status": expected_status,
                    "tables": expected_tables,
                    "allowed_table_sets": allowed_table_sets,
                    "required_columns": [
                        str(value) for value in expected.get("required_columns") or []
                    ],
                    "forbidden_tables": [
                        str(value) for value in expected.get("forbidden_tables") or []
                    ],
                    "gold_result_contract": normalized_gold,
                },
            }
        )
    _ambiguities, ambiguity_by_case_id = _benchmark_input_ambiguities(normalized)
    for case in normalized:
        detail = ambiguity_by_case_id.get(case["case_id"])
        if detail is not None:
            case["benchmark_input_ambiguity"] = detail
    return normalized


def _semantic_projection_output_name(
    report: dict[str, Any],
    source_field: str,
) -> str | None:
    """Resolve a result column through the validated semantic plan."""

    table, separator, field = str(source_field or "").rpartition(".")
    if not separator or not table or not field:
        return None
    query = report.get("query") or {}
    semantic_plan = query.get("semantic_plan") or {}
    semantic_ir = semantic_plan.get("semantic_ir") or {}
    matches: list[str] = []
    for projection in semantic_ir.get("projections") or []:
        if not isinstance(projection, dict):
            continue
        refs = {
            (str(ref.get("table") or "").casefold(), str(ref.get("field") or "").casefold())
            for ref in projection.get("source_fields") or []
            if isinstance(ref, dict)
        }
        if (table.casefold(), field.casefold()) in refs:
            output_name = str(projection.get("output_name") or "")
            if output_name:
                matches.append(output_name)
    unique = list(dict.fromkeys(matches))
    if len(unique) == 1:
        return unique[0]
    result_columns = [str(value) for value in (report.get("result") or {}).get("columns") or []]
    physical_matches = [
        value for value in result_columns if value.casefold() == field.casefold()
    ]
    return physical_matches[0] if len(physical_matches) == 1 else None


def _semantic_gold_equivalence_match(
    report: dict[str, Any],
    gold: dict[str, Any],
) -> bool:
    """Evaluate a bounded semantic Gold policy without persisting source rows.

    The first supported policy handles a real ranking edge case: when more
    entities tie at the top/bottom boundary than the requested limit, any
    unique set of the requested size at that same numeric boundary is correct.
    Exact fingerprints cannot represent that equivalence class safely.
    """

    policy = gold.get("semantic_equivalence")
    if not isinstance(policy, dict):
        return False
    if policy.get("kind") != "all_rows_equal_numeric_boundary":
        return False
    result = report.get("result") or {}
    expected_row_count = int((gold.get("expected_result") or {}).get("row_count") or 0)
    if int(result.get("row_count") or 0) != expected_row_count or expected_row_count < 1:
        return False
    if result.get("truncated_for_display") is True:
        return False
    rows = result.get("data") or []
    if not isinstance(rows, list) or len(rows) != expected_row_count:
        return False
    key_output = _semantic_projection_output_name(
        report, str(policy.get("key_source_field") or "")
    )
    metric_output = _semantic_projection_output_name(
        report, str(policy.get("metric_source_field") or "")
    )
    if not key_output or not metric_output or key_output == metric_output:
        return False
    keys: list[str] = []
    metrics: list[float] = []
    for row in rows:
        if not isinstance(row, dict) or key_output not in row or metric_output not in row:
            return False
        key = row.get(key_output)
        metric = row.get(metric_output)
        if key is None or isinstance(metric, bool) or not isinstance(metric, (int, float)):
            return False
        keys.append(str(key))
        metrics.append(float(metric))
    if policy.get("require_unique_keys") is True and len(set(keys)) != len(keys):
        return False
    precision = int(policy.get("numeric_precision", 6))
    boundary = round(float(policy.get("boundary_value")), precision)
    return all(round(value, precision) == boundary for value in metrics)


def _normalized_member_set(values: list[Any]) -> list[str]:
    return sorted(
        {
            unicodedata.normalize("NFKC", str(value)).strip().casefold()
            for value in values
            if unicodedata.normalize("NFKC", str(value)).strip()
        }
    )


def _member_set_sha256(values: list[Any]) -> str:
    return _sha256_json(_normalized_member_set(values))


def _semantic_band_summary_equivalence_match(
    report: dict[str, Any],
    shape: dict[str, Any],
) -> bool:
    """Compare a reviewed band summary by band meaning, not label formatting.

    Customer-facing band labels may differ in capitalization, whitespace, or
    inclusion of the numeric boundary (for example ``High (>75%)`` versus
    ``High (> 75%)``).  A published ``band_summary`` policy makes that
    presentation equivalence explicit while still requiring exact counts and
    exact low/member sets.  It is metadata-driven and is not tied to a case
    id, question text, or answer value.
    """

    policy = shape.get("semantic_equivalence")
    if not isinstance(policy, dict) or policy.get("kind") != "band_summary":
        return False
    result = report.get("result") or {}
    rows = result.get("data") or []
    expected = shape.get("expected_result") or {}
    if not isinstance(rows, list) or not rows or int(result.get("row_count") or 0) != len(rows):
        return False
    if int(expected.get("row_count") or 0) != len(rows):
        return False
    band_column = str(policy.get("band_column") or "score_band")
    count_column = str(policy.get("count_column") or "district_count")
    member_column = str(policy.get("member_column") or "")
    # Result aliases are presentation-level.  When the accepted shape allows
    # comparison by position, bind the semantic policy columns to the actual
    # returned aliases before checking counts and membership.
    first_row = rows[0] if rows and isinstance(rows[0], dict) else {}
    if band_column not in first_row:
        expected_columns = list((shape.get("expected_result") or {}).get("columns") or [])
        observed_columns = list(result.get("columns") or [])
        if (
            shape.get("equivalence", {}).get("column_aliases_compare_by_position")
            and len(expected_columns) == len(observed_columns)
        ):
            position_map = dict(zip(expected_columns, observed_columns, strict=True))
            band_column = position_map.get(band_column, band_column)
            count_column = position_map.get(count_column, count_column)
            member_column = position_map.get(member_column, member_column)
    definitions = list(policy.get("bands") or [])
    if not definitions:
        return False
    aliases: dict[str, str] = {}
    ranks: dict[str, int] = {}
    for index, definition in enumerate(definitions, start=1):
        if not isinstance(definition, dict):
            return False
        key = str(definition.get("key") or "").strip().casefold()
        if not key:
            return False
        ranks[key] = int(definition.get("rank") or index)
        for alias in [key, *(definition.get("aliases") or [])]:
            normalized = re.sub(r"[^a-z0-9]+", "", str(alias).casefold())
            if normalized:
                aliases[normalized] = key
    observed_by_band: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            return False
        raw_label = re.sub(r"[^a-z0-9]+", "", str(row.get(band_column) or "").casefold())
        matched = aliases.get(raw_label)
        if matched is None:
            matched = next((key for alias, key in aliases.items() if alias and alias in raw_label), None)
        if matched is None or matched in observed_by_band:
            return False
        count = row.get(count_column)
        if isinstance(count, bool) or not isinstance(count, (int, float)):
            return False
        observed_by_band[matched] = row
    if set(observed_by_band) != set(ranks):
        return False
    # Gold shape metadata normally stores only fingerprints, so derive the
    # expected count/member contract from the policy when supplied.  This is
    # intentionally explicit and does not read source rows.
    expected_counts = policy.get("expected_counts") or {}
    for key, row in observed_by_band.items():
        if key not in expected_counts:
            return False
        if float(row.get(count_column)) != float(expected_counts[key]):
            return False
    member_band = str(policy.get("member_band") or "").casefold()
    expected_members = {
        str(value).strip().casefold()
        for value in policy.get("expected_members") or []
        if str(value).strip()
    }
    if member_band and member_column:
        row = observed_by_band.get(member_band)
        if row is None:
            return False
        delimiter = str(policy.get("delimiter") or ",")
        # Treat delimiter whitespace as presentation-only.  A compiler may
        # emit `", "` while the reviewed contract records `","`; the member
        # set must be compared after trimming, not rejected for that harmless
        # formatting difference.
        raw_members = re.split(
            r"\s*" + re.escape(delimiter.strip()) + r"\s*",
            str(row.get(member_column) or ""),
        )
        observed_members = _normalized_member_set(raw_members)
        if len(raw_members) != len(observed_members):
            return False
        expected_hash = str(policy.get("expected_member_set_sha256") or "").strip()
        if expected_hash:
            if _member_set_sha256(raw_members) != expected_hash.casefold():
                return False
        elif observed_members != _normalized_member_set(list(expected_members)):
            return False
    return True


def _check_case(
    case: dict[str, Any],
    report: dict[str, Any],
    *,
    source_id: int,
    database_name: str,
    authorized_schemas: list[str],
) -> dict[str, Any]:
    expected = case["expected"]
    observed_status = str(report.get("status") or "error")
    observed_language = str(report.get("language") or "")
    observed_source = report.get("source") or {}
    query = report.get("query") or {}
    observed_tables = sorted(str(value) for value in query.get("tables") or [])
    observed_columns = {str(value) for value in query.get("columns") or []}
    expected_tables = sorted(str(value) for value in expected.get("tables") or [])
    allowed_table_sets = [
        sorted(str(value) for value in values)
        for values in expected.get("allowed_table_sets") or []
    ]
    matched_result_variant_id: str | None = None
    checks = {
        "status_match": observed_status == expected["status"],
        "language_match": observed_language == case["language"],
        "source_id_match": int(observed_source.get("source_id") or -1) == source_id,
        "database_scope_match": observed_source.get("database_name") == database_name,
        "schema_scope_match": list(observed_source.get("authorized_schemas") or [])
        == authorized_schemas,
        "source_rows_not_persisted": report.get("source_rows_persisted") is False,
        "benchmark_input_unambiguous": not bool(case.get("benchmark_input_ambiguity")),
    }
    if expected["status"] == "ok":
        checks.update(
            {
                "table_set_match": (
                    observed_tables in allowed_table_sets
                    if allowed_table_sets
                    else observed_tables == expected_tables
                ),
                "required_columns_present": set(expected.get("required_columns") or [])
                <= observed_columns,
                "forbidden_tables_absent": not set(expected.get("forbidden_tables") or [])
                & set(observed_tables),
            }
        )
        row_count = int((report.get("result") or {}).get("row_count") or 0)
        if expected.get("min_row_count") is not None:
            checks["min_row_count"] = row_count >= int(expected["min_row_count"])
        if expected.get("max_row_count") is not None:
            checks["max_row_count"] = row_count <= int(expected["max_row_count"])
        gold = expected.get("gold_result_contract")
        if gold:
            observed_result = report.get("result") or {}
            expected_result = gold["expected_result"]
            expected_equivalence = gold.get("equivalence") or {}
            observed_equivalence = observed_result.get("equivalence_fingerprints") or {}
            exact_columns_match = (
                list(observed_result.get("columns") or []) == expected_result["columns"]
            )
            exact_fingerprint_match = (
                observed_result.get("result_fingerprint")
                == expected_result["ordered_result_fingerprint"]
            )
            accepted_fingerprint_keys = list(
                expected_equivalence.get("accepted_fingerprint_keys") or []
            )
            fingerprint_equivalence_match = any(
                observed_equivalence.get(key)
                == (expected_equivalence.get("expected_fingerprints") or {}).get(key)
                for key in accepted_fingerprint_keys
            )
            semantic_equivalence_match = _semantic_gold_equivalence_match(report, gold)
            result_shapes = [
                {
                    "variant_id": None,
                    "expected_result": expected_result,
                    "equivalence": expected_equivalence,
                },
                *(gold.get("accepted_result_variants") or []),
            ]
            shape_evaluations: list[dict[str, Any]] = []
            observed_result_columns = list(observed_result.get("columns") or [])
            for index, shape in enumerate(result_shapes):
                shape_expected = shape.get("expected_result") or {}
                shape_equivalence = shape.get("equivalence") or {}
                shape_columns = list(shape_expected.get("columns") or [])
                shape_columns_match = observed_result_columns == shape_columns or (
                    bool(shape_equivalence.get("column_aliases_compare_by_position"))
                    and len(observed_result_columns) == len(shape_columns)
                )
                shape_row_count_match = row_count == int(
                    shape_expected.get("row_count") or 0
                )
                shape_fingerprint_match = any(
                    observed_equivalence.get(key)
                    == (shape_equivalence.get("expected_fingerprints") or {}).get(key)
                    for key in shape_equivalence.get("accepted_fingerprint_keys") or []
                )
                shape_semantic_equivalence_match = (
                    _semantic_band_summary_equivalence_match(report, shape)
                    if shape.get("semantic_equivalence")
                    else False
                )
                shape_equivalence_match = shape_fingerprint_match or (
                    index == 0 and semantic_equivalence_match
                ) or shape_semantic_equivalence_match
                shape_evaluations.append(
                    {
                        "shape": shape,
                        "columns_match": shape_columns_match,
                        "row_count_match": shape_row_count_match,
                        "equivalence_match": shape_equivalence_match,
                        "semantic_equivalence_match": (
                            semantic_equivalence_match
                            if index == 0
                            else shape_semantic_equivalence_match
                        ),
                        "complete_match": (
                            shape_columns_match
                            and shape_row_count_match
                            and shape_equivalence_match
                        ),
                    }
                )
            complete_variant_matches = [
                value
                for value in shape_evaluations[1:]
                if value["complete_match"]
            ]
            if complete_variant_matches:
                matched_result_variant_id = str(
                    complete_variant_matches[0]["shape"].get("variant_id") or ""
                ) or None
            equivalence_match = any(
                value["complete_match"] for value in shape_evaluations
            )
            shape_semantic_equivalence_match = any(
                value["semantic_equivalence_match"] for value in shape_evaluations
            )
            columns_match = any(
                value["columns_match"] for value in shape_evaluations
            )
            row_count_match = any(
                value["row_count_match"] for value in shape_evaluations
            )
            checks.update(
                {
                    "gold_exact_columns_match": exact_columns_match,
                    "gold_exact_result_fingerprint_match": exact_fingerprint_match,
                    "gold_columns_match": columns_match,
                    "gold_row_count_match": row_count_match,
                    "gold_result_fingerprint_match": equivalence_match,
                    "gold_result_equivalence_match": equivalence_match,
                    **(
                        {
                            "gold_diagnostic_semantic_equivalence_match": shape_semantic_equivalence_match,
                            "gold_diagnostic_fingerprint_equivalence_match": fingerprint_equivalence_match,
                        }
                        if gold.get("semantic_equivalence")
                        or any(
                            shape.get("semantic_equivalence")
                            for shape in result_shapes
                        )
                        else {}
                    ),
                    **(
                        {"gold_diagnostic_accepted_result_variant_match": True}
                        if matched_result_variant_id
                        else {}
                    ),
                }
            )
    gating_checks = {
        name: value
        for name, value in checks.items()
        if not name.startswith(("gold_exact_", "gold_diagnostic_"))
    }
    if expected["status"] == "ok" and expected.get("gold_result_contract"):
        # Gold SQL is one valid implementation, not the only valid physical
        # plan. When the returned rows are result-equivalent, alternate
        # governed tables or columns remain planning diagnostics rather than
        # answer-correctness failures. Forbidden-table and source-governance
        # checks always remain gating.
        gating_checks.pop("table_set_match", None)
        gating_checks.pop("required_columns_present", None)
    passed = all(gating_checks.values())
    result = {
        "case_id": case["case_id"],
        "language": case["language"],
        "question": case["question"],
        "business_language_eligible": case.get("business_language_eligible") is not False,
        "evaluation_bucket": _evaluation_bucket(case),
        "provenance_kind": (case.get("provenance") or {}).get("kind"),
        **(
            {"benchmark_input_ambiguity": case["benchmark_input_ambiguity"]}
            if case.get("benchmark_input_ambiguity")
            else {}
        ),
        **({"track": case["track"]} if case.get("track") else {}),
        **({"split": case["split"]} if case.get("split") else {}),
        **(
            {"capabilities": list(case["capabilities"])}
            if case.get("capabilities")
            else {}
        ),
        "status": "passed" if passed else "failed",
        "checks": checks,
        "observed": {
            "status": observed_status,
            "language": observed_language,
            "tables": observed_tables,
            "columns": sorted(observed_columns),
            "row_count": int((report.get("result") or {}).get("row_count") or 0),
            "result_columns": list((report.get("result") or {}).get("columns") or []),
            "result_fingerprint": (report.get("result") or {}).get("result_fingerprint"),
            "equivalence_fingerprints": dict(
                (report.get("result") or {}).get("equivalence_fingerprints") or {}
            ),
            "sql_sha256": (query.get("sql_sha256")),
            "semantic_metric_contract": query.get("semantic_metric_contract"),
            "semantic_plan": query.get("semantic_plan"),
            "planner": report.get("planner"),
            "model": report.get("model"),
            "prompt": report.get("prompt"),
            "generation": report.get("generation"),
            "source": observed_source,
            "source_rows_persisted": report.get("source_rows_persisted"),
            "semantic_caveats": list(report.get("semantic_caveats") or []),
            "reason": report.get("reason"),
            "error": report.get("error"),
            "gold_result_contract": (
                {
                    "contract_id": expected["gold_result_contract"].get("contract_id"),
                    "path": expected["gold_result_contract"].get("path"),
                    "sha256": expected["gold_result_contract"].get("sha256"),
                    "equivalence": expected["gold_result_contract"].get("equivalence"),
                    "semantic_equivalence": expected["gold_result_contract"].get(
                        "semantic_equivalence"
                    ),
                    "accepted_result_variants": expected["gold_result_contract"].get(
                        "accepted_result_variants"
                    ),
                    "matched_result_variant_id": matched_result_variant_id,
                }
                if expected.get("gold_result_contract")
                else None
            ),
        },
        "failure_reasons": sorted(name for name, value in gating_checks.items() if not value),
        "diagnostic_differences": sorted(
            name
            for name, value in checks.items()
            if name.startswith(("gold_exact_", "gold_diagnostic_")) and not value
        ),
        "planning_differences": sorted(
            name
            for name in ("table_set_match", "required_columns_present")
            if name in checks and not checks[name]
        ),
        "failure_class": None,
    }
    return result


def _product_metrics(
    case_reports: list[dict[str, Any]],
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    by_track: dict[str, dict[str, Any]] = {}
    by_bucket: dict[str, dict[str, Any]] = {}
    stage_totals: Counter[str] = Counter()
    stage_passed: Counter[str] = Counter()
    benchmark_input_ambiguous_case_count = 0

    for report, case in zip(case_reports, cases, strict=True):
        track = str(case.get("track") or "")
        bucket = by_track.setdefault(
            track,
            {"case_count": 0, "passed_case_count": 0, "gold_case_count": 0},
        )
        bucket["case_count"] += 1
        bucket["passed_case_count"] += int(report.get("status") == "passed")
        bucket["gold_case_count"] += int(
            bool(case.get("expected", {}).get("gold_result_contract"))
        )
        bucket.setdefault("business_language_eligible_case_count", 0)
        bucket["business_language_eligible_case_count"] += int(
            case.get("business_language_eligible") is not False
        )
        evaluation_bucket = _evaluation_bucket(case)
        bucket_metrics = by_bucket.setdefault(
            evaluation_bucket,
            {
                "case_count": 0,
                "passed_case_count": 0,
                "gold_case_count": 0,
                "gold_equivalence_passed_case_count": 0,
            },
        )
        bucket_metrics["case_count"] += 1
        bucket_metrics["passed_case_count"] += int(report.get("status") == "passed")
        has_gold = bool(case.get("expected", {}).get("gold_result_contract"))
        bucket_metrics["gold_case_count"] += int(has_gold)
        bucket_metrics["gold_equivalence_passed_case_count"] += int(
            has_gold and report.get("checks", {}).get("gold_result_equivalence_match") is True
        )

        checks = report.get("checks") or {}
        benchmark_input_ambiguous_case_count += int(
            checks.get("benchmark_input_unambiguous") is False
        )
        expected_status = str(case.get("expected", {}).get("status") or "")
        stages: dict[str, bool] = {
            "question_understanding": bool(checks.get("status_match"))
            and bool(checks.get("language_match")),
            "source_governance": bool(checks.get("source_id_match"))
            and bool(checks.get("database_scope_match"))
            and bool(checks.get("schema_scope_match"))
            and bool(checks.get("source_rows_not_persisted")),
        }
        if expected_status == "ok":
            stages["asset_resolution"] = bool(checks.get("table_set_match")) and bool(
                checks.get("required_columns_present")
            )
            stages["execution_result"] = bool(
                checks.get("gold_result_equivalence_match")
            )
        else:
            rejection_stage = {
                "business_clarification": "business_clarification",
                "data_unavailable": "data_unavailable_response",
                "safety": "safety_refusal",
            }.get(evaluation_bucket, "safety_refusal")
            stages[rejection_stage] = bool(checks.get("status_match"))
        for stage, passed in stages.items():
            stage_totals[stage] += 1
            stage_passed[stage] += int(passed)

    for bucket in by_track.values():
        bucket["case_pass_rate"] = _ratio(
            int(bucket["passed_case_count"]),
            int(bucket["case_count"]),
        )
    for bucket in by_bucket.values():
        bucket["case_pass_rate"] = _ratio(
            int(bucket["passed_case_count"]),
            int(bucket["case_count"]),
        )
        bucket["gold_equivalence_pass_rate"] = _ratio(
            int(bucket["gold_equivalence_passed_case_count"]),
            int(bucket["gold_case_count"]),
        )
    business_bucket = by_bucket.get("business_language", {})
    technical_bucket = by_bucket.get("technical_catalog_control", {})
    clarification_bucket = by_bucket.get("business_clarification", {})
    unavailable_bucket = by_bucket.get("data_unavailable", {})
    safety_bucket = by_bucket.get("safety", {})
    result = {
        "by_track": dict(sorted(by_track.items())),
        "by_evaluation_bucket": dict(sorted(by_bucket.items())),
        "business_language_case_count": int(business_bucket.get("case_count", 0)),
        "business_language_passed_case_count": int(
            business_bucket.get("passed_case_count", 0)
        ),
        "business_language_pass_rate": business_bucket.get("case_pass_rate"),
        "business_language_gold_equivalence_pass_rate": business_bucket.get(
            "gold_equivalence_pass_rate"
        ),
        "technical_catalog_control_case_count": int(
            technical_bucket.get("case_count", 0)
        ),
        "technical_catalog_control_passed_case_count": int(
            technical_bucket.get("passed_case_count", 0)
        ),
        "technical_catalog_control_pass_rate": technical_bucket.get("case_pass_rate"),
        "business_clarification_case_count": int(
            clarification_bucket.get("case_count", 0)
        ),
        "business_clarification_passed_case_count": int(
            clarification_bucket.get("passed_case_count", 0)
        ),
        "business_clarification_pass_rate": clarification_bucket.get(
            "case_pass_rate"
        ),
        "data_unavailable_case_count": int(unavailable_bucket.get("case_count", 0)),
        "data_unavailable_passed_case_count": int(
            unavailable_bucket.get("passed_case_count", 0)
        ),
        "data_unavailable_pass_rate": unavailable_bucket.get("case_pass_rate"),
        "safety_case_count": int(safety_bucket.get("case_count", 0)),
        "safety_passed_case_count": int(safety_bucket.get("passed_case_count", 0)),
        "safety_pass_rate": safety_bucket.get("case_pass_rate"),
        "by_stage": {
            stage: {
                "case_count": stage_totals[stage],
                "passed_case_count": stage_passed[stage],
                "pass_rate": _ratio(stage_passed[stage], stage_totals[stage]),
            }
            for stage in sorted(stage_totals)
        },
    }
    if benchmark_input_ambiguous_case_count:
        result["benchmark_input_ambiguity_case_count"] = benchmark_input_ambiguous_case_count
    return result


async def run_free_form_benchmark(
    *,
    benchmark_path: Path,
    semantic_layer_path: Path,
    source_id: int,
    owner: str,
    model_name: str = "gpt-5.1",
    reasoning_effort: str = "medium",
    timeout_seconds: int = 180,
    case_ids: tuple[str, ...] | None = None,
    splits: tuple[str, ...] | None = None,
    request_interval_seconds: float | None = None,
    max_concurrency: int = 1,
    execution_profile: Literal["baseline_sql", "semantic_ir_experimental"] = "baseline_sql",
    checkpoint_path: Path | None = None,
    gold_source_cohort_path: Path | None = None,
    resume: bool = False,
    progress_interval_seconds: float | None = None,
) -> dict[str, Any]:
    """Run one explicit product or candidate profile against frozen cases.

    A report covers exactly one execution profile.  It is intentionally not a
    rollout decision: comparison requires a matched baseline and candidate
    run using the same frozen source, semantic layer, benchmark, model, and
    runtime settings.
    """

    from .migration_runner import verify_runtime_schema_state

    # Benchmark execution depends on the virtual-source registry and governed
    # discovery contract, not on every control-plane feature developed in the
    # same monorepo.  Requiring global migration parity here makes unrelated
    # modules block read-only business-source evaluation.
    verify_runtime_schema_state(
        required_migrations=(
            "012_virtual_sources",
            "182_governed_virtual_source_discovery",
        )
    )
    benchmark_path = Path(benchmark_path).expanduser()
    semantic_layer_path = Path(semantic_layer_path).expanduser()
    benchmark, _benchmark_raw_bytes, benchmark_artifact_sha256 = _load_json_artifact(
        benchmark_path,
        artifact_name="benchmark",
    )
    (
        semantic_layer,
        semantic_layer_raw_bytes,
        semantic_layer_artifact_sha256,
    ) = _load_json_artifact(
        semantic_layer_path,
        artifact_name="semantic layer",
    )
    cases = _validate_benchmark(
        benchmark,
        semantic_layer,
        source_id=source_id,
        benchmark_path=benchmark_path,
    )
    full_case_count = len(cases)
    benchmark_definition_ambiguities, _ = _benchmark_input_ambiguities(cases)
    benchmark_definition_ambiguity_case_count = sum(
        1 for case in cases if case.get("benchmark_input_ambiguity")
    )
    if case_ids:
        requested = set(case_ids)
        unknown = sorted(requested - {case["case_id"] for case in cases})
        if unknown:
            raise BenchmarkConfigurationError("Unknown case_id(s): " + ", ".join(unknown))
        cases = [case for case in cases if case["case_id"] in requested]
    if splits:
        allowed_splits = {"development", "validation", "holdout"}
        requested_splits = {str(value) for value in splits}
        unknown_splits = sorted(requested_splits - allowed_splits)
        if unknown_splits:
            raise BenchmarkConfigurationError(
                "Unknown split(s): " + ", ".join(unknown_splits)
            )
        cases = [case for case in cases if str(case.get("split")) in requested_splits]
    if not cases:
        raise BenchmarkConfigurationError("Case selection produced no cases")
    if request_interval_seconds is None:
        request_interval_seconds = float(
            os.environ.get("GDA_NL2SQL_BENCH_REQUEST_INTERVAL_SECONDS", "0")
        )
    if request_interval_seconds < 0 or request_interval_seconds > 60:
        raise BenchmarkConfigurationError("request_interval_seconds must be between 0 and 60")
    if max_concurrency < 1 or max_concurrency > 16:
        raise BenchmarkConfigurationError("max_concurrency must be between 1 and 16")
    if execution_profile not in EXECUTION_PROFILES:
        raise BenchmarkConfigurationError("Unsupported execution_profile")
    if resume and checkpoint_path is None:
        raise BenchmarkConfigurationError("resume requires checkpoint_path")
    if progress_interval_seconds is not None and (
        progress_interval_seconds < 0 or progress_interval_seconds > 3600
    ):
        raise BenchmarkConfigurationError(
            "progress_interval_seconds must be between 0 and 3600"
        )

    binding = semantic_layer["source_binding"]
    gold_source_cohort = (
        _load_gold_source_cohort(
            gold_source_cohort_path,
            benchmark=benchmark,
            semantic_layer=semantic_layer,
            binding=binding,
            source_id=source_id,
            cases=cases,
        )
        if gold_source_cohort_path is not None
        else None
    )
    checkpoint = Path(checkpoint_path).expanduser() if checkpoint_path else None
    if checkpoint is not None and checkpoint.exists() and not resume:
        raise BenchmarkConfigurationError(
            f"Benchmark checkpoint already exists: {checkpoint}; pass resume=True"
        )
    identity = _benchmark_checkpoint_identity(
        benchmark=benchmark,
        semantic_layer=semantic_layer,
        binding=binding,
        cases=cases,
        source_id=source_id,
        model_name=model_name,
        reasoning_effort=reasoning_effort,
        timeout_seconds=timeout_seconds,
        request_interval_seconds=request_interval_seconds,
        max_concurrency=max_concurrency,
        execution_profile=execution_profile,
        benchmark_artifact_sha256=benchmark_artifact_sha256,
        semantic_layer_artifact_sha256=semantic_layer_artifact_sha256,
        gold_source_cohort=gold_source_cohort,
    )
    resumed_case_ids: set[str] = set()
    case_reports: list[dict[str, Any] | None] = [None] * len(cases)
    if checkpoint is not None and resume:
        if not checkpoint.exists():
            raise BenchmarkConfigurationError(
                f"Benchmark checkpoint does not exist: {checkpoint}"
            )
        loaded_reports = _load_benchmark_checkpoint(
            checkpoint,
            identity=identity,
            cases=cases,
        )
        for index, case in enumerate(cases):
            report = loaded_reports.get(str(case["case_id"]))
            if report is not None:
                case_reports[index] = _apply_gold_source_evaluation(
                    report,
                    case,
                    gold_source_cohort,
                )
                resumed_case_ids.add(str(case["case_id"]))
    started_at = datetime.now(UTC).isoformat()
    checkpoint_lock = asyncio.Lock()
    progress_lock = asyncio.Lock()
    progress_started = time.monotonic()
    next_progress_at = (
        progress_started + progress_interval_seconds
        if progress_interval_seconds and progress_interval_seconds > 0
        else None
    )

    async def persist_case(index: int, report: dict[str, Any]) -> None:
        nonlocal next_progress_at
        report = _apply_gold_source_evaluation(
            report,
            cases[index],
            gold_source_cohort,
        )
        case_reports[index] = report
        if checkpoint is not None:
            async with checkpoint_lock:
                _write_benchmark_checkpoint(
                    checkpoint,
                    identity=identity,
                    cases=cases,
                    case_reports=case_reports,
                    status="running",
                    started_at=started_at,
                    resumed=bool(resumed_case_ids),
                )
        if next_progress_at is not None:
            async with progress_lock:
                now = time.monotonic()
                if now >= next_progress_at:
                    completed_count = sum(item is not None for item in case_reports)
                    elapsed = round(now - progress_started, 3)
                    print(
                        json.dumps(
                            {
                                "stage": "benchmark_progress",
                                "completed_case_count": completed_count,
                                "total_case_count": len(cases),
                                "pending_case_count": len(cases) - completed_count,
                                "elapsed_seconds": elapsed,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        file=sys.stderr,
                        flush=True,
                    )
                    next_progress_at = now + progress_interval_seconds

    if checkpoint is not None and not resume:
        _write_benchmark_checkpoint(
            checkpoint,
            identity=identity,
            cases=cases,
            case_reports=case_reports,
            status="running",
            started_at=started_at,
            resumed=False,
        )
    semaphore = asyncio.Semaphore(max_concurrency)
    # Provider/source outages are suite-level infrastructure failures.  Once
    # observed, stop issuing further requests while retaining every selected
    # case in the report denominator.
    infrastructure_stop = asyncio.Event()
    # Preserve the first observed outage class so circuit-open cases do not
    # misreport a source outage as a model-provider outage (or vice versa).
    infrastructure_failure_class: str | None = None
    request_start_lock = asyncio.Lock()
    next_request_start = 0.0
    runtime_semantic_layer_path = _materialize_semantic_layer_snapshot(
        semantic_layer_raw_bytes
    )

    def assert_input_artifacts_unchanged() -> None:
        _assert_artifact_unchanged(
            benchmark_path,
            artifact_name="benchmark",
            expected_sha256=benchmark_artifact_sha256,
        )
        _assert_artifact_unchanged(
            semantic_layer_path,
            artifact_name="semantic layer",
            expected_sha256=semantic_layer_artifact_sha256,
        )

    async def run_case(index: int, case: dict[str, Any]) -> None:
        nonlocal next_request_start, infrastructure_failure_class
        async with semaphore:
            assert_input_artifacts_unchanged()
            if case.get("benchmark_input_ambiguity"):
                await persist_case(index, _benchmark_ambiguity_case_report(case))
                return
            if infrastructure_stop.is_set():
                await persist_case(index, {
                    "case_id": case["case_id"],
                    "language": case["language"],
                    "question": case["question"],
                    "business_language_eligible": (
                        case.get("business_language_eligible") is not False
                    ),
                    "evaluation_bucket": _evaluation_bucket(case),
                    "provenance_kind": (case.get("provenance") or {}).get("kind"),
                    "status": "failed",
                    "checks": {},
                    "observed": {
                        "status": "error",
                        "error": "not_attempted_provider_or_source_unavailable",
                        "source_rows_persisted": False,
                    },
                    "failure_reasons": ["benchmark_infrastructure_circuit_open"],
                    "error": "not_attempted_provider_or_source_unavailable",
                    "failure_class": (
                        infrastructure_failure_class
                        or "model_provider_unavailable"
                    ),
                })
                return
            if request_interval_seconds:
                async with request_start_lock:
                    loop = asyncio.get_running_loop()
                    delay = max(0.0, next_request_start - loop.time())
                    if delay:
                        await asyncio.sleep(delay)
                    next_request_start = loop.time() + request_interval_seconds
            try:
                execution = await run_governed_virtual_nl2sql(
                    question=case["question"],
                    semantic_layer_path=runtime_semantic_layer_path,
                    source_id=source_id,
                    owner=owner,
                    model_name=model_name,
                    reasoning_effort=reasoning_effort,
                    timeout_seconds=timeout_seconds,
                    verify_platform_schema=False,
                    reuse_runtime_metadata=True,
                    execution_profile=execution_profile,
                )
                checked = _check_case(
                    case,
                    execution,
                    source_id=source_id,
                    database_name=str(binding["database_name"]),
                    authorized_schemas=list(binding.get("allowed_schemas") or []),
                )
                checked["failure_class"] = _failure_class(checked)
                await persist_case(index, checked)
                if checked["failure_class"] in {
                    "model_provider_unavailable",
                    "virtual_source_unavailable",
                }:
                    if infrastructure_failure_class is None:
                        infrastructure_failure_class = checked["failure_class"]
                    infrastructure_stop.set()
            except BenchmarkConfigurationError:
                raise
            except Exception as exc:
                assert_input_artifacts_unchanged()
                error_text = _redact_error(exc)
                failure_class = _failure_class(
                    {"status": "failed", "error": error_text, "observed": {"error": error_text}}
                ) or "benchmark_execution_error"
                await persist_case(index, {
                    "case_id": case["case_id"],
                    "language": case["language"],
                    "question": case["question"],
                    "business_language_eligible": (
                        case.get("business_language_eligible") is not False
                    ),
                    "evaluation_bucket": _evaluation_bucket(case),
                    "provenance_kind": (case.get("provenance") or {}).get("kind"),
                    "status": "failed",
                    "checks": {},
                    "observed": {"status": "error", "source_rows_persisted": False},
                    "failure_reasons": [failure_class],
                    "error": error_text,
                    "failure_class": failure_class,
                })
                if failure_class in {"model_provider_unavailable", "virtual_source_unavailable"}:
                    if infrastructure_failure_class is None:
                        infrastructure_failure_class = failure_class
                    infrastructure_stop.set()

    pending_indices = [
        index for index, report in enumerate(case_reports) if report is None
    ]
    tasks = [
        asyncio.create_task(run_case(index, cases[index]))
        for index in pending_indices
    ]
    try:
        await asyncio.gather(*tasks)
        assert_input_artifacts_unchanged()
    except BenchmarkConfigurationError as exc:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if checkpoint is not None:
            _write_benchmark_checkpoint(
                checkpoint,
                identity=identity,
                cases=cases,
                case_reports=case_reports,
                status="aborted",
                started_at=started_at,
                resumed=bool(resumed_case_ids),
                abort_reason=_redact_error(exc),
            )
        raise
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    finally:
        try:
            runtime_semantic_layer_path.unlink()
        except FileNotFoundError:
            pass
    completed_case_reports = [item for item in case_reports if item is not None]
    if len(completed_case_reports) != len(cases):
        raise RuntimeError("benchmark_case_result_missing")
    case_reports = completed_case_reports

    passed = [item for item in case_reports if item["status"] == "passed"]
    gold_cases = [
        item
        for item, case in zip(case_reports, cases, strict=True)
        if case["expected"].get("gold_result_contract")
    ]
    gold_passed = [item for item in gold_cases if item["status"] == "passed"]
    gold_exact_passed = [
        item
        for item in gold_cases
        if item["checks"].get("gold_exact_columns_match")
        and item["checks"].get("gold_exact_result_fingerprint_match")
    ]
    expected_ok_pairs = [
        (item, case)
        for item, case in zip(case_reports, cases, strict=True)
        if case["expected"]["status"] == "ok"
    ]
    expected_refusal_pairs = [
        (item, case)
        for item, case in zip(case_reports, cases, strict=True)
        if case["expected"]["status"] == "rejected"
    ]
    observed_refusals = [
        (item, case)
        for item, case in zip(case_reports, cases, strict=True)
        if item.get("observed", {}).get("status") == "rejected"
    ]
    refusal_true_positives = sum(
        1
        for item, _case in expected_refusal_pairs
        if item.get("observed", {}).get("status") == "rejected"
    )
    refusal_false_positives = sum(
        1
        for item, _case in expected_ok_pairs
        if item.get("observed", {}).get("status") == "rejected"
    )
    refusal_false_negatives = len(expected_refusal_pairs) - refusal_true_positives
    execution_success_count = sum(
        1 for item, _case in expected_ok_pairs if item.get("observed", {}).get("status") == "ok"
    )
    status_counts = Counter(str(item["observed"].get("status") or "error") for item in case_reports)
    language_counts = Counter(str(item["language"]) for item in case_reports)
    generations = [
        item["observed"]["generation"]
        for item in case_reports
        if isinstance(item.get("observed", {}).get("generation"), dict)
    ]
    observed_versions = sorted(
        {
            str(version)
            for generation in generations
            for version in generation.get("observed_model_versions") or []
        }
    )
    usage_totals = {
        key: sum(int((generation.get("usage") or {}).get(key) or 0) for generation in generations)
        for key in ("input_tokens", "output_tokens", "reasoning_tokens")
    }
    latency_values = [
        float(generation["latency_ms"])
        for generation in generations
        if generation.get("latency_ms") is not None
    ]
    language_metrics: dict[str, dict[str, Any]] = {}
    for language in SUPPORTED_LANGUAGES:
        language_pairs = [
            (item, case)
            for item, case in zip(case_reports, cases, strict=True)
            if case["language"] == language
        ]
        if not language_pairs:
            continue
        language_gold = [
            item for item, case in language_pairs if case["expected"].get("gold_result_contract")
        ]
        language_exact = [
            item
            for item in language_gold
            if item.get("checks", {}).get("gold_exact_columns_match")
            and item.get("checks", {}).get("gold_exact_result_fingerprint_match")
        ]
        language_refusals = [
            item for item, case in language_pairs if case["expected"]["status"] == "rejected"
        ]
        language_metrics[language] = {
            "case_count": len(language_pairs),
            "passed_case_count": sum(
                1 for item, _case in language_pairs if item["status"] == "passed"
            ),
            "case_pass_rate": _ratio(
                sum(1 for item, _case in language_pairs if item["status"] == "passed"),
                len(language_pairs),
            ),
            "gold_case_count": len(language_gold),
            "gold_result_equivalence_passed_case_count": sum(
                1 for item in language_gold if item["status"] == "passed"
            ),
            "gold_result_equivalence_pass_rate": _ratio(
                sum(1 for item in language_gold if item["status"] == "passed"),
                len(language_gold),
            ),
            "gold_exact_result_match_passed_case_count": len(language_exact),
            "gold_exact_result_match_rate": _ratio(len(language_exact), len(language_gold)),
            "refusal_case_count": len(language_refusals),
            "refusal_recall": _ratio(
                sum(
                    1
                    for item in language_refusals
                    if item.get("observed", {}).get("status") == "rejected"
                ),
                len(language_refusals),
            ),
        }
    failure_class_counts = Counter(
        str(item["failure_class"]) for item in case_reports if item.get("failure_class")
    )
    benchmark_ambiguities_by_key = {
        (
            str(detail["language"]),
            str(detail["normalized_question"]),
        ): detail
        for case in cases
        if (detail := case.get("benchmark_input_ambiguity"))
    }
    benchmark_ambiguities = [
        benchmark_ambiguities_by_key[key] for key in sorted(benchmark_ambiguities_by_key)
    ]
    benchmark_ambiguity_case_count = sum(
        1 for case in cases if case.get("benchmark_input_ambiguity")
    )
    evaluable_gold_cases = [
        (item, case)
        for item, case in zip(case_reports, cases, strict=True)
        if case["expected"].get("gold_result_contract")
        and not case.get("benchmark_input_ambiguity")
    ]
    evaluable_gold_passed = [
        item for item, _case in evaluable_gold_cases if item["status"] == "passed"
    ]
    model_evaluable_gold_cases = [
        (item, case)
        for item, case in evaluable_gold_cases
        if item.get("gold_source_status") != "gold_stale_source_result"
    ]
    model_gold_equivalence_passed = [
        item
        for item, _case in model_evaluable_gold_cases
        if item.get("checks", {}).get("gold_result_equivalence_match") is True
    ]
    gold_stale_source_result_cases = [
        item
        for item, _case in evaluable_gold_cases
        if item.get("gold_source_status") == "gold_stale_source_result"
    ]
    metric_contract_counts = Counter(
        str(contract["contract_id"])
        for item in case_reports
        if (contract := (item.get("observed") or {}).get("semantic_metric_contract"))
        and contract.get("contract_id")
    )
    semantic_plan_observations = [
        plan
        for item, _case in expected_ok_pairs
        if isinstance(
            (plan := (item.get("observed") or {}).get("semantic_plan")),
            dict,
        )
    ]
    semantic_plan_route_counts = Counter(
        _semantic_plan_route(plan)
        for plan in semantic_plan_observations
        if plan.get("status") == "planned"
    )
    semantic_plan_fallback_counts = Counter(
        str(plan.get("fallback_reason") or "unknown")
        for plan in semantic_plan_observations
        if plan.get("status") == "legacy_fallback"
    )
    semantic_plan_planned_count = sum(
        1 for plan in semantic_plan_observations if plan.get("status") == "planned"
    )
    semantic_plan_validated_count = sum(
        1
        for plan in semantic_plan_observations
        if plan.get("status") == "planned"
        and (plan.get("validation") or {}).get("valid") is True
    )
    planner_observations = [
        planner
        for item in case_reports
        if isinstance((planner := (item.get("observed") or {}).get("planner")), dict)
    ]
    planner_route_counts = Counter(
        str(planner.get("route") or "unknown") for planner in planner_observations
    )
    planner_fallback_counts = Counter(
        str(planner["fallback_reason"])
        for planner in planner_observations
        if planner.get("fallback_reason")
    )
    llm_invoked_case_count = sum(
        1 for planner in planner_observations if planner.get("llm_invoked") is True
    )
    direct_metric_reports = [
        item
        for item in case_reports
        if ((item.get("observed") or {}).get("planner") or {}).get("route")
        == "deterministic_reviewed_metric_contract"
    ]
    direct_metric_gold_reports = [item for item in direct_metric_reports if item in gold_cases]
    direct_metric_gold_passed = [
        item for item in direct_metric_gold_reports if item.get("status") == "passed"
    ]
    infrastructure_failure_count = sum(
        failure_class_counts.get(name, 0)
        for name in ("model_provider_unavailable", "virtual_source_unavailable")
    )
    infrastructure_circuit_open_case_count = sum(
        "benchmark_infrastructure_circuit_open" in (item.get("failure_reasons") or [])
        for item in case_reports
    )
    completeness = benchmark.get("completeness") or {}
    completeness_status = str(completeness.get("status") or "")
    benchmark_definition_complete = not completeness or completeness_status in {
        "complete",
        "complete_runtime_gold_freeze",
    }
    benchmark_run_complete = len(cases) == full_case_count
    product_profile = _validate_product_evaluation_profile(
        benchmark,
        semantic_layer,
    )
    product_gold_coverage_complete = _product_gold_coverage_complete(cases)
    product_metrics = (
        _product_metrics(case_reports, cases) if product_profile is not None else {}
    )
    report = {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "passed" if len(passed) == len(case_reports) else "failed",
        "scope": (
            "business_language_product_evaluation"
            if product_profile is not None
            else (
                "frozen_result_contract_evaluation"
                if gold_cases
                else "candidate_free_form_semantic_boundary_evaluation"
            )
        ),
        "benchmark_accuracy_claim": bool(
            execution_profile == "baseline_sql"
            and
            product_profile is None
            and benchmark_definition_complete
            and benchmark_run_complete
            and gold_cases
            and len(gold_passed) == len(gold_cases)
            and not gold_stale_source_result_cases
            and not benchmark_definition_ambiguities
        ),
        "product_baseline_claim_valid": bool(
            execution_profile == "baseline_sql"
            and
            product_profile is not None
            and benchmark_definition_complete
            and benchmark_run_complete
            and product_gold_coverage_complete
            and infrastructure_failure_count == 0
            and not gold_stale_source_result_cases
            and not benchmark_definition_ambiguities
        ),
        # A candidate can provide valid experimental evidence even though it
        # must never inherit the baseline's production-claim authority.
        "product_evaluation_run_valid": bool(
            product_profile is not None
            and benchmark_definition_complete
            and benchmark_run_complete
            and product_gold_coverage_complete
            and infrastructure_failure_count == 0
            and not gold_stale_source_result_cases
            and not benchmark_definition_ambiguities
        ),
        "benchmark": {
            "benchmark_id": benchmark.get("benchmark_id"),
            "version": benchmark.get("version"),
            "source_file_sha256": _sha256_json(benchmark),
            "source_file_bytes_sha256": benchmark_artifact_sha256,
            "semantic_layer_file_bytes_sha256": semantic_layer_artifact_sha256,
            "artifact_immutability": {
                "status": "passed",
                "runtime_semantic_layer_source": "startup_byte_snapshot",
                "checked_before_each_case": True,
            },
            "semantic_layer_version": semantic_layer.get("semantic_version"),
            "metric_contract_version": semantic_layer.get("metric_contract_version"),
            "prompt_version": (
                SEMANTIC_IR_EXPERIMENT_PROMPT_VERSION
                if execution_profile == "semantic_ir_experimental"
                else BENCHMARK_PROMPT_VERSION
            ),
            "execution_profile": execution_profile,
            "request_interval_seconds": request_interval_seconds,
            "max_concurrency": max_concurrency,
            "coverage": benchmark.get("coverage") or {},
            "completeness": benchmark.get("completeness") or {},
            "claim_boundary": benchmark.get("claim_boundary") or {},
            "definition_complete": benchmark_definition_complete,
            "run_complete": benchmark_run_complete,
            "input_uniqueness": {
                "status": (
                    "passed" if not benchmark_definition_ambiguities else "failed"
                ),
                "normalization": "unicode_nfkc_casefold_whitespace_v1",
                "ambiguity_group_count": len(benchmark_definition_ambiguities),
                "ambiguity_case_count": benchmark_definition_ambiguity_case_count,
                "conflicts": benchmark_definition_ambiguities,
            },
            "selected_case_ids": [case["case_id"] for case in cases],
            "selected_splits": sorted({str(case.get("split")) for case in cases}),
            **(
                {"evaluation_profile": product_profile}
                if product_profile is not None
                else {}
            ),
            **(
                {
                    "gold_source_cohort": {
                        key: value
                        for key, value in gold_source_cohort.items()
                        if key != "observations"
                    }
                }
                if gold_source_cohort is not None
                else {}
            ),
        },
        "model": {
            "requested": model_name,
            "reasoning_effort": reasoning_effort,
            "observed_versions": observed_versions,
        },
        "experiment": {
            "execution_profile": execution_profile,
            "route_role": (
                "candidate_canary"
                if execution_profile == "semantic_ir_experimental"
                else "current_production_baseline"
            ),
            "default_production_route": execution_profile == "baseline_sql",
            "reviewed_metric_contracts": "matched_control_only",
            "comparison_requires_matched_baseline_and_candidate": True,
            "release_gate": False,
        },
        "source": {
            "source_id": source_id,
            "owner": owner,
            "database_name": binding.get("database_name"),
            "authorized_schemas": list(binding.get("allowed_schemas") or []),
            "discovery_fingerprint": binding.get("discovery_fingerprint"),
            "profile_fingerprint": binding.get("profile_fingerprint"),
            "execution_mode": "registered_governed_virtual_read_only",
        },
        "metrics": {
            "case_count": len(case_reports),
            "passed_case_count": len(passed),
            "case_pass_rate": len(passed) / len(case_reports),
            "status_counts": dict(sorted(status_counts.items())),
            "language_case_counts": dict(sorted(language_counts.items())),
            "usage": usage_totals,
            "mean_generation_latency_ms": (
                round(sum(latency_values) / len(latency_values), 3) if latency_values else None
            ),
            "p95_generation_latency_ms": _percentile(latency_values, 95),
            "expected_query_case_count": len(expected_ok_pairs),
            "query_execution_success_count": execution_success_count,
            "query_execution_success_rate": _ratio(execution_success_count, len(expected_ok_pairs)),
            "gold_result_contract_case_count": len(gold_cases),
            "gold_result_equivalence_passed_case_count": len(gold_passed),
            "gold_result_equivalence_pass_rate": (
                len(gold_passed) / len(gold_cases) if gold_cases else None
            ),
            "gold_result_equivalence_supported": bool(gold_cases),
            "gold_exact_result_match_passed_case_count": len(gold_exact_passed),
            "gold_exact_result_match_rate": (
                len(gold_exact_passed) / len(gold_cases) if gold_cases else None
            ),
            **(
                {
                    "model_evaluable_gold_case_count": len(
                        model_evaluable_gold_cases
                    ),
                    "model_gold_equivalence_passed_case_count": len(
                        model_gold_equivalence_passed
                    ),
                    "model_gold_equivalence_pass_rate": _ratio(
                        len(model_gold_equivalence_passed),
                        len(model_evaluable_gold_cases),
                    ),
                    "gold_stale_source_result_case_count": len(
                        gold_stale_source_result_cases
                    ),
                }
                if gold_source_cohort is not None
                else {}
            ),
            **(
                {
                    "gold_result_equivalence_evaluable_case_count": len(
                        evaluable_gold_cases
                    ),
                    "gold_result_equivalence_passed_evaluable_case_count": len(
                        evaluable_gold_passed
                    ),
                    "gold_result_equivalence_pass_rate_excluding_benchmark_input_ambiguity": (
                        _ratio(len(evaluable_gold_passed), len(evaluable_gold_cases))
                    ),
                    "benchmark_input_ambiguity_group_count": len(
                        benchmark_ambiguities
                    ),
                    "benchmark_input_ambiguity_case_count": (
                        benchmark_ambiguity_case_count
                    ),
                    "benchmark_input_ambiguity_details": benchmark_ambiguities,
                }
                if benchmark_ambiguities
                else {}
            ),
            "infrastructure_failure_case_count": infrastructure_failure_count,
            "infrastructure_circuit_open_case_count": infrastructure_circuit_open_case_count,
            "semantic_metric_contract_application_count": sum(
                metric_contract_counts.values()
            ),
            "semantic_metric_contract_counts": dict(sorted(metric_contract_counts.items())),
            "planner": {
                "observation_count": len(planner_observations),
                "route_counts": dict(sorted(planner_route_counts.items())),
                "fallback_reason_counts": dict(sorted(planner_fallback_counts.items())),
                "direct_metric_route_count": len(direct_metric_reports),
                "direct_metric_route_rate": _ratio(
                    len(direct_metric_reports),
                    len(expected_ok_pairs),
                ),
                "llm_invoked_case_count": llm_invoked_case_count,
                "llm_avoided_case_count": len(planner_observations)
                - llm_invoked_case_count,
                "llm_invocation_case_rate": _ratio(
                    llm_invoked_case_count,
                    len(planner_observations),
                ),
                "direct_metric_gold_case_count": len(direct_metric_gold_reports),
                "direct_metric_gold_equivalence_passed_case_count": len(
                    direct_metric_gold_passed
                ),
                "direct_metric_gold_equivalence_pass_rate": _ratio(
                    len(direct_metric_gold_passed),
                    len(direct_metric_gold_reports),
                ),
            },
            "semantic_plan": {
                "mode": (
                    "authoritative_candidate_compiler"
                    if execution_profile == "semantic_ir_experimental"
                    else "shadow_non_authoritative"
                ),
                "expected_query_case_count": len(expected_ok_pairs),
                "observation_count": len(semantic_plan_observations),
                "planned_count": semantic_plan_planned_count,
                "validated_count": semantic_plan_validated_count,
                "shadow_coverage_rate": _ratio(
                    semantic_plan_planned_count,
                    len(expected_ok_pairs),
                ),
                "route_counts": dict(sorted(semantic_plan_route_counts.items())),
                "fallback_reason_counts": dict(
                    sorted(semantic_plan_fallback_counts.items())
                ),
                "release_gate": False,
            },
            "refusal": {
                "expected_refusal_case_count": len(expected_refusal_pairs),
                "observed_refusal_count": len(observed_refusals),
                "true_positive_count": refusal_true_positives,
                "false_positive_count": refusal_false_positives,
                "false_negative_count": refusal_false_negatives,
                "precision": _ratio(
                    refusal_true_positives,
                    refusal_true_positives + refusal_false_positives,
                ),
                "recall": _ratio(
                    refusal_true_positives,
                    refusal_true_positives + refusal_false_negatives,
                ),
            },
            "by_language": language_metrics,
            "failure_class_counts": dict(sorted(failure_class_counts.items())),
            **product_metrics,
        },
        "source_rows_persisted": False,
        "limitations": [
            *(
                [
                    "This is a single-run product baseline. Release reliability requires "
                    "the separately configured repeated-run stability evaluation.",
                    "Gold SQL and Gold results are evaluation-only artifacts and are not "
                    "available to runtime prompts, retrieval, or semantic assets.",
                ]
                if product_profile is not None
                else []
            ),
            *(
                []
                if benchmark_definition_complete
                else [
                    "Benchmark definition is incomplete; planned extension Gold contracts "
                    "must be frozen before reporting full benchmark accuracy."
                ]
            ),
            *(
                []
                if benchmark_run_complete
                else [
                    "This report covers a selected case subset; it cannot support a full "
                    "benchmark accuracy claim."
                ]
            ),
            *(
                []
                if gold_cases
                else [
                    "Cases check semantic scope, SQL admission, execution status, and language; "
                    "they do not establish Gold result equivalence.",
                    "Add a frozen expected result contract before reporting accuracy.",
                ]
            ),
            "Arabic labels and source categorical values remain subject to customer review.",
        ],
        "cases": case_reports,
    }
    if checkpoint is not None:
        report["benchmark"]["checkpoint"] = {
            "path": str(checkpoint),
            "schema": CHECKPOINT_SCHEMA,
            "resumed": bool(resumed_case_ids),
            "reused_case_count": len(resumed_case_ids),
            "persisted_case_count": len(case_reports),
        }
        _write_benchmark_checkpoint(
            checkpoint,
            identity=identity,
            cases=cases,
            case_reports=case_reports,
            status="completed",
            started_at=started_at,
            resumed=bool(resumed_case_ids),
            final_report_sha256=_sha256_json(report),
        )
    return report


def _load_environment() -> None:
    configured = os.environ.get("GDA_OPERATOR_ENV_FILE")
    env_path = Path(configured) if configured else Path(__file__).with_name(".env")
    if env_path.exists():
        configured_values = dotenv_values(env_path)
        load_dotenv(env_path, override=False)
        # A direct Gemini deployment must not inherit a proxy credential from
        # the interactive shell. Keep this override narrow so other provider
        # deployments retain their normal process-environment precedence.
        if str(configured_values.get("GDA_GEMINI_TRANSPORT") or "").strip().casefold() in {
            "native",
            "direct",
        }:
            for name in (
                "GDA_LLM_PROVIDER",
                "GDA_LLM_MODEL",
                "GDA_GEMINI_TRANSPORT",
                "GEMINI_API_KEY",
                "GOOGLE_API_KEY",
            ):
                value = configured_values.get(name)
                if value is not None and str(value).strip():
                    os.environ[name] = str(value).strip()
    secret_path = Path(
        os.environ.get("GDA_VSOURCE_SECRET_FILE")
        or Path(__file__).with_name(".vsource-secret.env")
    ).expanduser()
    if secret_path.exists():
        os.environ.setdefault("GDA_VSOURCE_SECRET_FILE", str(secret_path))
        load_dotenv(secret_path, override=False)
    if os.environ.get("GDA_DISABLE_LLM_PROXY", "").casefold() in {"1", "true", "yes"}:
        for name in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        ):
            os.environ.pop(name, None)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gda-free-form-nl2sql-eval",
        description="Evaluate free-form NL2SQL against a governed virtual source.",
    )
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--semantic-layer", type=Path, required=True)
    parser.add_argument("--source-id", type=int, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--model", default="gpt-5.1")
    parser.add_argument(
        "--reasoning-effort",
        choices=("none", "low", "medium", "high", "xhigh", "max"),
        default="medium",
    )
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument(
        "--split",
        action="append",
        choices=("development", "validation", "holdout"),
        default=[],
        help="Restrict execution to one or more frozen benchmark splits.",
    )
    parser.add_argument("--request-interval-seconds", type=float)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument(
        "--execution-profile",
        choices=tuple(sorted(EXECUTION_PROFILES)),
        default="baseline_sql",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        help="Persist one atomic per-case checkpoint for interruption recovery.",
    )
    parser.add_argument(
        "--gold-source-cohort",
        type=Path,
        help=(
            "Use an independently executed Gold source cohort to separate "
            "stale Gold from model accuracy."
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume only from the checkpoint supplied with --checkpoint.",
    )
    parser.add_argument(
        "--progress-interval-seconds",
        type=float,
        help="Emit periodic progress JSON to stderr while cases complete.",
    )
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    _load_environment()
    args = _parser().parse_args(argv)
    if args.timeout_seconds < 1:
        raise SystemExit("--timeout-seconds must be positive")
    try:
        report = asyncio.run(
            run_free_form_benchmark(
                benchmark_path=args.benchmark,
                semantic_layer_path=args.semantic_layer,
                source_id=args.source_id,
                owner=args.owner,
                model_name=args.model,
                reasoning_effort=args.reasoning_effort,
                timeout_seconds=args.timeout_seconds,
                case_ids=tuple(args.case_id),
                splits=tuple(args.split),
                request_interval_seconds=args.request_interval_seconds,
                max_concurrency=args.max_concurrency,
                execution_profile=args.execution_profile,
                checkpoint_path=args.checkpoint,
                gold_source_cohort_path=args.gold_source_cohort,
                resume=args.resume,
                progress_interval_seconds=args.progress_interval_seconds,
            )
        )
    except Exception as exc:
        report = {
            "schema": REPORT_SCHEMA,
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "error",
            "stage": "benchmark_preflight",
            "message": _redact_error(exc),
        }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        output = {
            "status": report.get("status"),
            "output": str(args.output),
            "metrics": report.get("metrics"),
        }
    else:
        output = report
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "passed" else 1


__all__ = [
    "BENCHMARK_SCHEMA",
    "REPORT_SCHEMA",
    "CHECKPOINT_SCHEMA",
    "GOLD_SOURCE_COHORT_SCHEMA",
    "BenchmarkConfigurationError",
    "PRODUCT_EVALUATION_PROFILE",
    "run_free_form_benchmark",
]


if __name__ == "__main__":
    raise SystemExit(main())
