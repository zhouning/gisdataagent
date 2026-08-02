"""Deterministic real-data acceptance for standard mapping proposals."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from numbers import Real
from pathlib import Path
from typing import Any

from .contracts import (
    SourceFieldProfile,
    StandardDataElement,
    propose_standard_mapping,
)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHAPEFILE_MEMBER_SUFFIXES = (
    ".shp",
    ".shx",
    ".dbf",
    ".prj",
    ".cpg",
    ".sbn",
    ".sbx",
    ".qix",
    ".fix",
    ".shp.xml",
)

_PUBLIC_CASE_LABELS = {
    "bizhu-jqdltb-parcel-current-golden": "璧山 JQDLTB 标准落标",
    "chongqing-osm-roads-negative-holdout": "重庆 OSM 道路负向集",
    "central-building-negative-holdout": "中心城区建筑负向集",
}


def acceptance_public_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    """Return a UI-safe real-data result without paths, hashes or samples."""
    cases = []
    for raw in report.get("cases") or []:
        case_id = str(raw.get("case_id") or "")
        profile = raw.get("profile") or {}
        metrics = raw.get("metrics") or {}
        gates = raw.get("acceptance_gates") or {}
        cases.append({
            "case_id": case_id,
            "label": _PUBLIC_CASE_LABELS.get(case_id, case_id),
            "split": raw.get("split"),
            "target_table": raw.get("target_table"),
            "feature_count": profile.get("feature_count"),
            "geometry_type": profile.get("geometry_type"),
            "precision": metrics.get("precision"),
            "recall": metrics.get("recall"),
            "unexpected_recommendations": raw.get(
                "unexpected_recommendations", 0,
            ),
            "passed": bool(gates) and all(
                bool(gate.get("passed"))
                for gate in gates.values()
                if isinstance(gate, Mapping)
            ),
        })
    standard = report.get("standard") or {}
    governance = report.get("governance") or {}
    return {
        "schema": "gis-data-agent.standard-mapping-acceptance-summary.v1",
        "benchmark_id": report.get("benchmark_id"),
        "standard": {
            "doc_code": standard.get("doc_code"),
            "version_label": standard.get("version_label"),
        },
        "technical_status": (
            "passed" if report.get("technical_pass") is True else "blocked"
        ),
        "promotion_ready": report.get("promotion_ready") is True,
        "metrics": dict(report.get("metrics") or {}),
        "cases": cases,
        "governance_blockers": list(
            governance.get("promotion_blockers") or []
        ),
    }


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def dataset_members(path: Path) -> tuple[Path, ...]:
    """Return every byte-bearing member of one logical source dataset."""
    if path.suffix.casefold() != ".shp":
        return (path,)
    members = tuple(
        candidate
        for suffix in SHAPEFILE_MEMBER_SUFFIXES
        if (candidate := path.parent / f"{path.stem}{suffix}").is_file()
    )
    if path not in members:
        raise FileNotFoundError(path)
    return members


def bundle_identity(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    members = [
        {
            "name": member.name,
            "size_bytes": member.stat().st_size,
            "sha256": sha256_file(member),
        }
        for member in dataset_members(path)
    ]
    bundle_sha256 = (
        members[0]["sha256"] if len(members) == 1 else _canonical_sha256(members)
    )
    return {
        "bundle_sha256": bundle_sha256,
        "size_bytes": sum(member["size_bytes"] for member in members),
        "members": members,
    }


def profile_vector_dataset(
    path: Path,
) -> tuple[dict[str, Any], tuple[SourceFieldProfile, ...]]:
    """Profile vector schema without persisting source values."""
    import fiona

    with fiona.open(path) as source:
        properties = source.schema.get("properties") or {}
        fields = tuple(
            SourceFieldProfile(name=str(name), dtype=str(dtype))
            for name, dtype in properties.items()
        )
        bounds = tuple(round(float(value), 8) for value in source.bounds)
        crs = source.crs.to_string() if source.crs else None
        profile = {
            "driver": source.driver,
            "layer_name": source.name,
            "feature_count": len(source),
            "geometry_type": source.schema.get("geometry"),
            "bounds": list(bounds),
            "crs": crs,
            "fields": [
                {"name": field.name, "dtype": field.dtype}
                for field in fields
            ],
            "samples_persisted": False,
        }
    profile["schema_sha256"] = _canonical_sha256(
        {
            "geometry_type": profile["geometry_type"],
            "crs": profile["crs"],
            "fields": profile["fields"],
        }
    )
    return profile, fields


def run_acceptance_protocol(
    *,
    protocol: Mapping[str, Any],
    dataset_root: Path,
    archive_path: Path,
    standard_version_id: str,
    standard_elements: Sequence[StandardDataElement],
    allow_unsealed: bool = False,
) -> dict[str, Any]:
    """Run a no-LLM golden/holdout protocol against immutable source bytes."""
    _validate_protocol(protocol)
    root = dataset_root.resolve(strict=True)
    archive = bundle_identity(archive_path.resolve(strict=True))
    expected_archive = protocol["source"]["archive_sha256"]
    archive_match = _identity_matches(
        expected_archive,
        archive["bundle_sha256"],
        allow_unsealed=allow_unsealed,
    )
    standard_fingerprint = _standard_fingerprint(standard_elements)
    expected_standard = protocol["standard"]["elements_sha256"]
    standard_match = _identity_matches(
        expected_standard,
        standard_fingerprint,
        allow_unsealed=allow_unsealed,
    )

    case_reports = [
        _evaluate_case(
            case=case,
            dataset_root=root,
            standard_version_id=standard_version_id,
            standard_elements=standard_elements,
            allow_unsealed=allow_unsealed,
        )
        for case in protocol["cases"]
    ]
    expected_count = sum(case["metrics"]["expected"] for case in case_reports)
    predicted_count = sum(case["metrics"]["predicted"] for case in case_reports)
    correct_count = sum(case["metrics"]["correct"] for case in case_reports)
    source_identities_sealed = bool(
        expected_archive
        and expected_standard
        and all(case["bundle_sha256"] for case in protocol["cases"])
    )
    technical_pass = (
        archive_match
        and standard_match
        and source_identities_sealed
        and all(case["passed"] for case in case_reports)
    )
    if allow_unsealed and not source_identities_sealed:
        status = "observed_unsealed"
    else:
        status = "passed" if technical_pass else "failed"
    governance = dict(protocol["governance"])
    governance_blockers = [
        key
        for key in ("business_steward", "license_status")
        if str(governance.get(key, "")).startswith("pending")
    ]
    return {
        "schema": "gis-data-agent.standard-mapping-acceptance-report.v1",
        "benchmark_id": protocol["benchmark_id"],
        "status": status,
        "technical_pass": technical_pass,
        "promotion_ready": technical_pass and not governance_blockers,
        "generated_at": datetime.now(UTC).isoformat(),
        "execution_policy": {
            "llm_mode": "disabled",
            "embedding_provider": None,
            "authoritative_write": False,
        },
        "standard": {
            "doc_code": protocol["standard"]["doc_code"],
            "version_label": protocol["standard"]["version_label"],
            "version_id": standard_version_id,
            "elements_sha256": standard_fingerprint,
            "expected_elements_sha256": expected_standard,
            "identity_match": standard_match,
        },
        "source": {
            "archive_name": archive_path.name,
            "archive_sha256": archive["bundle_sha256"],
            "expected_archive_sha256": expected_archive,
            "archive_identity_match": archive_match,
            "archive_size_bytes": archive["size_bytes"],
            "absolute_paths_persisted": False,
        },
        "governance": {
            **governance,
            "promotion_blockers": governance_blockers,
        },
        "cases": case_reports,
        "metrics": {
            "cases": len(case_reports),
            "cases_passed": sum(case["passed"] for case in case_reports),
            "expected_mappings": expected_count,
            "predicted_mappings": predicted_count,
            "correct_mappings": correct_count,
            "micro_precision": _ratio(correct_count, predicted_count),
            "micro_recall": _ratio(correct_count, expected_count),
            "unexpected_recommendations": sum(
                len(case["unexpected_recommendations"])
                for case in case_reports
            ),
        },
        "observed_seal": {
            "archive_sha256": archive["bundle_sha256"],
            "elements_sha256": standard_fingerprint,
            "case_bundle_sha256": {
                case["case_id"]: case["bundle"]["bundle_sha256"]
                for case in case_reports
            },
        },
    }


def _evaluate_case(
    *,
    case: Mapping[str, Any],
    dataset_root: Path,
    standard_version_id: str,
    standard_elements: Sequence[StandardDataElement],
    allow_unsealed: bool,
) -> dict[str, Any]:
    relative_path = Path(case["relative_path"])
    if relative_path.is_absolute():
        raise ValueError("acceptance case paths must be relative")
    source_path = (dataset_root / relative_path).resolve(strict=True)
    if not source_path.is_relative_to(dataset_root):
        raise ValueError("acceptance case path escapes dataset root")
    bundle = bundle_identity(source_path)
    expected_bundle = case["bundle_sha256"]
    bundle_match = _identity_matches(
        expected_bundle,
        bundle["bundle_sha256"],
        allow_unsealed=allow_unsealed,
    )
    profile, source_fields = profile_vector_dataset(source_path)
    proposal = propose_standard_mapping(
        source_fields=source_fields,
        standard_version_id=standard_version_id,
        elements=standard_elements,
        target_table=case["target_table"],
        embedding_provider=None,
    )
    expected_mapping = dict(case["expected_mapping"])
    actual_mapping = dict(proposal["mapping"])
    correct = {
        source: target
        for source, target in actual_mapping.items()
        if expected_mapping.get(source) == target
    }
    missing = {
        source: target
        for source, target in expected_mapping.items()
        if actual_mapping.get(source) != target
    }
    unexpected = {
        source: target
        for source, target in actual_mapping.items()
        if source not in expected_mapping
    }
    wrong = {
        source: {"expected": expected_mapping[source], "actual": target}
        for source, target in actual_mapping.items()
        if source in expected_mapping and expected_mapping[source] != target
    }
    metrics = {
        "expected": len(expected_mapping),
        "predicted": len(actual_mapping),
        "correct": len(correct),
        "precision": _ratio(len(correct), len(actual_mapping)),
        "recall": _ratio(len(correct), len(expected_mapping)),
    }
    gate_spec = case["gates"]
    gate_results = {
        "bundle_identity": {
            "required": True,
            "observed": bundle_match,
            "passed": bundle_match,
        },
        "min_precision": {
            "required": gate_spec["min_precision"],
            "observed": metrics["precision"],
            "passed": metrics["precision"] >= gate_spec["min_precision"],
        },
        "min_recall": {
            "required": gate_spec["min_recall"],
            "observed": metrics["recall"],
            "passed": metrics["recall"] >= gate_spec["min_recall"],
        },
        "max_unexpected_recommendations": {
            "required": gate_spec["max_unexpected_recommendations"],
            "observed": len(unexpected),
            "passed": (
                len(unexpected) <= gate_spec["max_unexpected_recommendations"]
            ),
        },
    }
    passed = all(result["passed"] for result in gate_results.values())
    return {
        "case_id": case["case_id"],
        "split": case["split"],
        "relative_path": relative_path.as_posix(),
        "target_table": case["target_table"],
        "passed": passed,
        "bundle": bundle,
        "expected_bundle_sha256": expected_bundle,
        "bundle_identity_match": bundle_match,
        "profile": profile,
        "source_profile_hash": proposal["source_profile_hash"],
        "expected_mapping": expected_mapping,
        "actual_mapping": actual_mapping,
        "missing_or_incorrect": missing,
        "wrong_target": wrong,
        "unexpected_recommendations": unexpected,
        "proposal_summary": proposal["summary"],
        "proposal_target_scope": proposal["target_scope"],
        "proposal_thresholds": proposal["thresholds"],
        "proposal_evidence": [
            _proposal_evidence(item) for item in proposal["proposals"]
        ],
        "acceptance_gates": gate_results,
        "metrics": metrics,
    }


def _identity_matches(
    expected: str | None,
    observed: str,
    *,
    allow_unsealed: bool,
) -> bool:
    if expected is None:
        return allow_unsealed
    return expected == observed


def _validate_protocol(protocol: Mapping[str, Any]) -> None:
    if protocol.get("schema") != "gis-data-agent.standard-mapping-acceptance.v1":
        raise ValueError("unsupported acceptance protocol schema")
    if not protocol.get("benchmark_id"):
        raise ValueError("benchmark_id is required")
    for section in ("source", "standard", "governance"):
        if not isinstance(protocol.get(section), Mapping):
            raise ValueError(f"protocol section {section!r} is required")
    cases = protocol.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("at least one acceptance case is required")
    case_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, Mapping):
            raise ValueError("each acceptance case must be an object")
        case_id = str(case.get("case_id") or "")
        if not case_id or case_id in case_ids:
            raise ValueError("acceptance case IDs must be non-empty and unique")
        case_ids.add(case_id)
        if case.get("split") not in {"golden", "holdout"}:
            raise ValueError(f"invalid split for case {case_id!r}")
        if not case.get("relative_path") or not case.get("target_table"):
            raise ValueError(f"case {case_id!r} is missing path or target_table")
        if not isinstance(case.get("expected_mapping"), Mapping):
            raise ValueError(f"case {case_id!r} expected_mapping must be an object")
        gates = case.get("gates")
        if not isinstance(gates, Mapping):
            raise ValueError(f"case {case_id!r} gates must be an object")
        _validate_ratio_gate(gates, "min_precision", case_id)
        _validate_ratio_gate(gates, "min_recall", case_id)
        max_unexpected = gates.get("max_unexpected_recommendations")
        if (
            isinstance(max_unexpected, bool)
            or not isinstance(max_unexpected, int)
            or max_unexpected < 0
        ):
            raise ValueError(
                f"case {case_id!r} max_unexpected_recommendations "
                "must be a non-negative integer"
            )
        _validate_optional_sha256(case.get("bundle_sha256"), "bundle_sha256")
    _validate_optional_sha256(
        protocol["source"].get("archive_sha256"), "archive_sha256"
    )
    _validate_optional_sha256(
        protocol["standard"].get("elements_sha256"), "elements_sha256"
    )


def _validate_optional_sha256(value: Any, field_name: str) -> None:
    if value is not None and (
        not isinstance(value, str) or not SHA256_RE.fullmatch(value)
    ):
        raise ValueError(f"{field_name} must be null or a lowercase SHA-256")


def _validate_ratio_gate(
    gates: Mapping[str, Any],
    gate_name: str,
    case_id: str,
) -> None:
    value = gates.get(gate_name)
    if (
        isinstance(value, bool)
        or not isinstance(value, Real)
        or not 0 <= value <= 1
    ):
        raise ValueError(f"case {case_id!r} {gate_name} must be between 0 and 1")


def _proposal_evidence(proposal: Mapping[str, Any]) -> dict[str, Any]:
    """Retain explainability while excluding source sample values by construction."""
    candidates = []
    for candidate in proposal.get("candidates", []):
        evidence = candidate.get("evidence") or {}
        candidates.append({
            "target_data_element_id": candidate.get("target_data_element_id"),
            "target_field": candidate.get("target_field"),
            "code": candidate.get("code"),
            "name_zh": candidate.get("name_zh"),
            "confidence": candidate.get("confidence"),
            "lexical_score": evidence.get("lexical_score"),
            "semantic_score": evidence.get("semantic_score"),
            "type_score": evidence.get("type_score"),
            "matched_on": evidence.get("matched_on"),
            "match_method": candidate.get("match_method"),
        })
    conflict = proposal.get("conflict") or {}
    return {
        "source_field": proposal.get("source_field"),
        "source_dtype": proposal.get("source_dtype"),
        "disposition": proposal.get("disposition"),
        "confidence_margin": proposal.get("confidence_margin"),
        "conflict_reason": conflict.get("reason"),
        "candidates": candidates,
    }


def standard_elements_fingerprint(elements: Sequence[StandardDataElement]) -> str:
    """Return the canonical identity of a version-bound standard element set."""
    payload = [
        {
            "code": element.code,
            "name_zh": element.name_zh,
            "name_en": element.name_en,
            "definition": element.definition,
            "representation_class": element.representation_class,
            "datatype": element.datatype,
            "unit": element.unit,
            "obligation": element.obligation,
            "bound_table": element.bound_table,
            "bound_column": element.bound_column,
            "aliases": list(element.aliases),
        }
        for element in sorted(
            elements,
            key=lambda item: (item.bound_table, item.code, item.bound_column),
        )
    ]
    return _canonical_sha256(payload)


def _standard_fingerprint(elements: Sequence[StandardDataElement]) -> str:
    """Backward-compatible internal alias for existing acceptance reports."""
    return standard_elements_fingerprint(elements)


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0 if numerator == 0 else 0.0
    return round(numerator / denominator, 6)
