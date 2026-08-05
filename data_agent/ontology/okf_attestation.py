"""Deterministic receipts and attestation for version-locked ontology demos."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .okf_bundle import (
    OKF_BUNDLE_ID,
    OKF_VERSION,
    load_concept_frontmatter,
    okf_reference,
    resolve_okf_resource,
    scenario_computation_id,
)

RECEIPT_SCHEMA = "gda.okf.attested-computation-receipt.v1"
VERDICT_SCHEMA = "gda.okf.attestation-verdict.v1"
EXECUTOR_ACTOR = "gda-ontology-demo-executor/1.0"
ATTESTER_ACTOR = "process:gda-ontology-scenario-attester-v1"


def _digest(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _counts(features: list[dict[str, Any]], property_name: str) -> dict[str, int]:
    values = Counter(
        str((feature.get("properties") or {}).get(property_name) or "").strip()
        for feature in features
    )
    values.pop("", None)
    return dict(sorted(values.items()))


def _authoritative_result(demo: Any, scenario_id: str) -> dict[str, Any]:
    scenario = demo._scenario(scenario_id)
    filename = (
        "heping_changed_parcels.geojson"
        if scenario_id == "heping_review"
        else "banzhu_changed_parcels.geojson"
    )
    features = demo._geojson(filename).get("features") or []
    changed_area_ha = round(
        sum(float((feature.get("properties") or {}).get("area_ha") or 0) for feature in features),
        2,
    )
    result: dict[str, Any] = {
        "scenario_id": scenario_id,
        "changed_count": len(features),
        "changed_area_ha": changed_area_ha,
        "process_counts": _counts(features, "process"),
    }
    if scenario_id == "heping_review":
        status_counts = _counts(features, "review_status")
        result["review_status_counts"] = status_counts
        result["headline"] = (
            f"识别 {len(features)} 个变化地块、"
            f"{status_counts.get('空间冲突', 0)} 个空间冲突和 "
            f"{status_counts.get('材料待补', 0)} 个审批证据缺口"
        )
    else:
        rows = {row["name"]: row for row in scenario.get("structure_rows") or []}
        result["structure_deltas_ha"] = {
            name: rows[name]["delta_ha"]
            for name in ("农用地合计", "旱地", "园地", "林地", "宅基地（村居住用地）")
            if name in rows
        }
        result["headline"] = (
            f"规划图斑中识别 {len(features)} 个变化地块，"
            "结构表显示农用地净增 9.06 公顷"
        )
    return result


def _displayed_result(raw_result: dict[str, Any]) -> dict[str, Any]:
    scenario = raw_result.get("scenario") or {}
    result: dict[str, Any] = {
        "scenario_id": scenario.get("id"),
        "changed_count": scenario.get("changed_count"),
        "changed_area_ha": scenario.get("changed_area_ha"),
        "process_counts": dict(sorted((scenario.get("process_counts") or {}).items())),
        "headline": raw_result.get("headline"),
    }
    if scenario.get("id") == "heping_review":
        result["review_status_counts"] = dict(
            sorted((scenario.get("review_status_counts") or {}).items())
        )
    else:
        rows = {row["name"]: row for row in scenario.get("structure_rows") or []}
        result["structure_deltas_ha"] = {
            name: rows[name]["delta_ha"]
            for name in ("农用地合计", "旱地", "园地", "林地", "宅基地（村居住用地）")
            if name in rows
        }
    return result


def build_scenario_receipt(
    demo: Any,
    scenario_id: str,
    raw_result: dict[str, Any],
    *,
    executed_at: str | None = None,
) -> dict[str, Any]:
    concept_id = scenario_computation_id(scenario_id)
    contract = load_concept_frontmatter(concept_id)
    computation_path = resolve_okf_resource(str(contract["computation"]))
    input_artifacts = []
    for artifact in demo.manifest.get("files") or []:
        filename = str(artifact.get("name") or "")
        if filename:
            path = demo.bundle_dir / filename
            input_artifacts.append(
                {
                    "name": filename,
                    "sha256": _file_sha256(path),
                    "manifest_sha256": artifact.get("sha256"),
                }
            )
    displayed_result = _displayed_result(raw_result)
    timestamp = executed_at or datetime.now(UTC).isoformat()
    body = {
        "schema": RECEIPT_SCHEMA,
        "okf_version": OKF_VERSION,
        "bundle_id": OKF_BUNDLE_ID,
        "concept_id": concept_id,
        "runtime": contract["runtime"],
        "parameters": {"scenario_id": scenario_id},
        "executor": EXECUTOR_ACTOR,
        "executed_at": timestamp,
        "executed_computation": {
            "resource": contract["computation"],
            "sha256": _file_sha256(computation_path),
        },
        "input_artifacts": input_artifacts,
        "result": displayed_result,
        "result_sha256": _digest(displayed_result),
    }
    return {**body, "receipt_id": f"sha256:{_digest(body)}"}


def attest_scenario_receipt(
    demo: Any,
    scenario_id: str,
    receipt: dict[str, Any],
    *,
    checked_at: str | None = None,
) -> dict[str, Any]:
    """Re-read sanctioned resources and independently check a runtime receipt."""
    concept_id = scenario_computation_id(scenario_id)
    contract = load_concept_frontmatter(concept_id)
    expected_result = _authoritative_result(demo, scenario_id)
    computation_path = resolve_okf_resource(str(contract["computation"]))
    errors: list[str] = []
    checks: list[dict[str, Any]] = []

    def check(check_id: str, passed: bool, detail: str) -> None:
        checks.append({"id": check_id, "passed": passed, "detail": detail})
        if not passed:
            errors.append(check_id)

    check("receipt_schema", receipt.get("schema") == RECEIPT_SCHEMA, "receipt ABI")
    receipt_body = {key: value for key, value in receipt.items() if key != "receipt_id"}
    check(
        "receipt_id",
        receipt.get("receipt_id") == f"sha256:{_digest(receipt_body)}",
        "receipt content digest",
    )
    check(
        "okf_contract",
        receipt.get("bundle_id") == OKF_BUNDLE_ID
        and receipt.get("concept_id") == concept_id,
        "bundle and concept binding",
    )
    check("runtime", receipt.get("runtime") == contract.get("runtime"), "runtime binding")
    check("executor", receipt.get("executor") == EXECUTOR_ACTOR, "sanctioned executor actor")
    check(
        "parameters",
        receipt.get("parameters") == {"scenario_id": scenario_id},
        "declared parameter values",
    )
    executed = receipt.get("executed_computation") or {}
    check(
        "computation_digest",
        executed.get("resource") == contract.get("computation")
        and executed.get("sha256") == _file_sha256(computation_path),
        "sanctioned computation resource and SHA-256",
    )
    artifact_checks = []
    receipt_artifact_names: list[str] = []
    manifest_files = {
        str(item.get("name")): str(item.get("sha256"))
        for item in demo.manifest.get("files") or []
    }
    for item in receipt.get("input_artifacts") or []:
        name = str(item.get("name") or "")
        receipt_artifact_names.append(name)
        path = demo.bundle_dir / name
        artifact_checks.append(
            bool(name)
            and path.is_file()
            and item.get("sha256") == _file_sha256(path)
            and item.get("manifest_sha256") == manifest_files.get(name)
        )
    check(
        "input_artifacts",
        len(receipt_artifact_names) == len(set(receipt_artifact_names))
        and set(receipt_artifact_names) == set(manifest_files)
        and all(artifact_checks),
        "all version-locked inputs match the demo manifest",
    )
    check(
        "result_digest",
        receipt.get("result_sha256") == _digest(receipt.get("result")),
        "receipt result digest",
    )
    check(
        "authoritative_result",
        receipt.get("result") == expected_result,
        "displayed result independently recomputed from source features",
    )
    passed = not errors
    body = {
        "schema": VERDICT_SCHEMA,
        "passed": passed,
        "attester": ATTESTER_ACTOR,
        "resource": contract["attester"]["resource"],
        "checked_at": checked_at or datetime.now(UTC).isoformat(),
        "receipt_id": receipt.get("receipt_id"),
        "checks": checks,
        "errors": errors,
        "gate": "display" if passed else "refuse_display",
        "scope": (
            "Verifies version-locked input integrity, sanctioned computation binding, "
            "and result consistency; it is not statutory approval."
        ),
    }
    return {**body, "verdict_id": f"sha256:{_digest(body)}"}


def execute_attested_scenario(
    demo: Any,
    scenario_id: str,
    computation: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    """Execute a registered scenario and gate display on deterministic attestation."""
    raw_result = computation(scenario_id)
    receipt = build_scenario_receipt(demo, scenario_id, raw_result)
    verdict = attest_scenario_receipt(demo, scenario_id, receipt)
    reference = okf_reference(query_type="demo_scenario_analysis", scenario_id=scenario_id)
    if not verdict["passed"]:
        return {
            "run_id": raw_result.get("run_id"),
            "scenario": {"id": scenario_id},
            "status": "attestation_failed",
            "headline": "执行证明未通过，结果已阻止展示。",
            "steps": raw_result.get("steps") or [],
            "findings": [],
            "decision_scope": raw_result.get("decision_scope"),
            "okf_reference": reference,
            "execution_receipt": receipt,
            "attestation": verdict,
        }
    return {
        **raw_result,
        "okf_reference": reference,
        "execution_receipt": receipt,
        "attestation": verdict,
    }
