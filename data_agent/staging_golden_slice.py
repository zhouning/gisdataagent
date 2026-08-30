"""Build a staging golden slice from evidence-gated PlatformRun truth.

The command is intentionally read-only.  It requires an explicitly selected
tenant, Run, and capability, then verifies the exact success event, provider
observation, output Artifact, independent quality verdict, and lineage edge
that the control ledger used to finalize the Run.  It never selects a recent
Run implicitly and never changes platform state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from .staging_live_evidence import (
    COLLECTION_SCHEMA,
    GOLDEN_SLICE_SCHEMA,
    SHA256_PATTERN,
    SOURCE_REVISION_PATTERN,
    golden_slice_fingerprint,
)

TENANT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
CAPABILITY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
IMAGE_DIGEST_PATTERN = re.compile(r"@(?P<digest>sha256:[0-9a-f]{64})$")
SUCCESS_EVIDENCE_SCHEMA = "gda.run_success_evidence.v1"
LEDGER_EXPORT_SCHEMA = "gda.staging_golden_ledger_export.v1"
GOLDEN_LEDGER_FIELDS = frozenset(
    {
        "tenant_id",
        "run_id",
        "capability_id",
        "definition_version_id",
        "definition_sha256",
        "run_status",
        "run_submitted_at",
        "run_started_at",
        "run_terminal_at",
        "terminal_actor_subject",
        "event_to_status",
        "terminal_event_occurred_at",
        "success_evidence_schema",
        "attempt_observation_id",
        "output_artifact_id",
        "quality_result_id",
        "lineage_event_id",
        "run_success_evidence_fingerprint",
        "attempt_framework_kind",
        "attempt_observed_state",
        "attempt_observed_at",
        "output_artifact_role",
        "output_artifact_sha256",
        "output_resource_version_id",
        "output_created_at",
        "quality_verdict",
        "quality_resource_version_id",
        "quality_rule_version_ref",
        "quality_metrics",
        "quality_evidence_artifact_id",
        "quality_result_sha256",
        "quality_evaluated_by",
        "quality_evaluated_at",
        "quality_evidence_artifact_role",
        "lineage_target_resource_version_id",
        "lineage_source_resource_version_id",
        "lineage_occurred_at",
    }
)


class StagingGoldenSliceError(RuntimeError):
    """The selected Run cannot become protected staging evidence."""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _items(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _timestamp(value: Any, *, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise StagingGoldenSliceError(f"{label} is not an ISO timestamp") from exc
    else:
        raise StagingGoldenSliceError(f"{label} is missing")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StagingGoldenSliceError(f"{label} must be timezone-aware")
    return parsed.astimezone(UTC)


def _uuid(value: Any, *, label: str) -> str:
    try:
        parsed = UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise StagingGoldenSliceError(f"{label} is not a UUID") from exc
    canonical = str(parsed)
    if str(value) != canonical:
        raise StagingGoldenSliceError(f"{label} is not a canonical UUID")
    return canonical


def _sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise StagingGoldenSliceError(f"{label} is not a SHA-256 fingerprint")
    return value


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _run_success_evidence_fingerprint(
    *,
    tenant_id: str,
    run_id: str,
    attempt_observation_id: str,
    output_artifact_id: str,
    quality_result_id: str,
    lineage_event_id: str,
) -> str:
    return _canonical_sha256(
        {
            "tenant_id": tenant_id,
            "run_id": run_id,
            "attempt_observation_id": attempt_observation_id,
            "output_artifact_id": output_artifact_id,
            "quality_result_id": quality_result_id,
            "lineage_event_id": lineage_event_id,
        }
    )


def _quality_result_fingerprint(
    *,
    tenant_id: str,
    run_id: str,
    resource_version_id: str,
    rule_version_ref: str,
    metrics: Mapping[str, Any],
    evidence_artifact_id: str,
    evaluated_by: str,
    evaluated_at: datetime,
) -> str:
    return _canonical_sha256(
        {
            "tenant_id": tenant_id,
            "run_id": run_id,
            "resource_version_id": resource_version_id,
            "rule_version_ref": rule_version_ref,
            "verdict": "passed",
            "metrics": dict(metrics),
            "evidence_artifact_id": evidence_artifact_id,
            "evaluated_by": evaluated_by,
            "evaluated_at": evaluated_at.astimezone(UTC)
            .isoformat()
            .replace("+00:00", "Z"),
        }
    )


def staging_binding_from_collection(
    collection: Mapping[str, Any],
) -> tuple[dict[str, str], datetime]:
    """Extract immutable deployment bindings and the latest ready Pod time."""
    if collection.get("schema") != COLLECTION_SCHEMA:
        raise StagingGoldenSliceError("live collection schema is unsupported")
    kubernetes = _mapping(collection.get("kubernetes"))
    deployment = _mapping(kubernetes.get("deployment"))
    platform = _mapping(collection.get("platform_snapshot"))
    config = _mapping(platform.get("config"))
    environment_access = _mapping(platform.get("environment_access"))
    runtime = _mapping(platform.get("runtime"))

    if deployment.get("environment") != "staging":
        raise StagingGoldenSliceError("live deployment is not staging")
    source_revision = deployment.get("source_revision")
    if not isinstance(source_revision, str) or not SOURCE_REVISION_PATTERN.fullmatch(
        source_revision
    ):
        raise StagingGoldenSliceError("live deployment source revision is invalid")
    image = deployment.get("image")
    image_match = IMAGE_DIGEST_PATTERN.search(str(image or ""))
    if image_match is None:
        raise StagingGoldenSliceError("live deployment image is not digest-bound")

    ready_pod_times = [
        _timestamp(pod.get("created_at"), label="ready Pod creation time")
        for pod in _items(kubernetes.get("pods"))
        if pod.get("ready") is True
    ]
    if not ready_pod_times:
        raise StagingGoldenSliceError("live deployment has no timestamped ready Pod")

    binding = {
        "source_revision": source_revision,
        "deployment_uid": _uuid(
            deployment.get("uid"), label="live deployment UID"
        ),
        "image_digest": image_match.group("digest"),
        "schema_fingerprint": _sha256(
            deployment.get("schema_fingerprint"),
            label="live schema fingerprint",
        ),
        "config_fingerprint": _sha256(
            config.get("config_fingerprint"),
            label="live config fingerprint",
        ),
        "environment_access_fingerprint": _sha256(
            environment_access.get("fingerprint"),
            label="live environment-access fingerprint",
        ),
        "runtime_fingerprint": _sha256(
            runtime.get("inventory_fingerprint"),
            label="live runtime fingerprint",
        ),
    }
    return binding, max(ready_pod_times)


def build_staging_golden_slice(
    ledger: Mapping[str, Any],
    collection: Mapping[str, Any],
    *,
    tenant_id: str,
    run_id: str,
    capability_id: str,
    definition_version_id: str,
    input_resource_version_id: str,
    now: datetime | None = None,
    max_run_age_seconds: float = 3600,
) -> dict[str, Any]:
    """Build evidence only when a fresh Run matches every ledger binding."""
    current = (now or datetime.now(UTC)).astimezone(UTC)
    if not math.isfinite(max_run_age_seconds) or max_run_age_seconds <= 0:
        raise StagingGoldenSliceError("maximum Run age must be positive")
    if not TENANT_PATTERN.fullmatch(tenant_id):
        raise StagingGoldenSliceError("tenant ID is invalid")
    canonical_run_id = _uuid(run_id, label="selected Run ID")
    if not CAPABILITY_PATTERN.fullmatch(capability_id):
        raise StagingGoldenSliceError("capability ID is invalid")
    canonical_definition_id = _uuid(
        definition_version_id, label="selected definition version ID"
    )
    canonical_input_id = _uuid(
        input_resource_version_id, label="selected input resource version ID"
    )

    binding, pod_not_before = staging_binding_from_collection(collection)
    expected = {
        "tenant_id": tenant_id,
        "run_id": canonical_run_id,
        "capability_id": capability_id,
        "definition_version_id": canonical_definition_id,
        "lineage_source_resource_version_id": canonical_input_id,
        "run_status": "succeeded",
        "event_to_status": "succeeded",
        "success_evidence_schema": SUCCESS_EVIDENCE_SCHEMA,
        "attempt_framework_kind": "dolphinscheduler",
        "attempt_observed_state": "success",
        "output_artifact_role": "output",
        "quality_verdict": "passed",
        "quality_evidence_artifact_role": "evidence",
    }
    for field, value in expected.items():
        if ledger.get(field) != value:
            raise StagingGoldenSliceError(
                f"selected Run {field} does not match the golden contract"
            )

    identifier_fields = (
        "attempt_observation_id",
        "output_artifact_id",
        "quality_result_id",
        "lineage_event_id",
    )
    for field in identifier_fields:
        _uuid(ledger.get(field), label=field)
    for field in (
        "definition_sha256",
        "output_artifact_sha256",
        "quality_result_sha256",
        "run_success_evidence_fingerprint",
    ):
        _sha256(ledger.get(field), label=field)

    expected_success_fingerprint = _run_success_evidence_fingerprint(
        tenant_id=tenant_id,
        run_id=canonical_run_id,
        attempt_observation_id=str(ledger["attempt_observation_id"]),
        output_artifact_id=str(ledger["output_artifact_id"]),
        quality_result_id=str(ledger["quality_result_id"]),
        lineage_event_id=str(ledger["lineage_event_id"]),
    )
    if ledger.get("run_success_evidence_fingerprint") != (
        expected_success_fingerprint
    ):
        raise StagingGoldenSliceError("Run success evidence fingerprint drifted")
    metrics = ledger.get("quality_metrics")
    if not isinstance(metrics, Mapping) or not metrics:
        raise StagingGoldenSliceError("quality metrics are missing")
    expected_quality_fingerprint = _quality_result_fingerprint(
        tenant_id=tenant_id,
        run_id=canonical_run_id,
        resource_version_id=_uuid(
            ledger.get("quality_resource_version_id"),
            label="quality resource version ID",
        ),
        rule_version_ref=str(ledger.get("quality_rule_version_ref") or ""),
        metrics=metrics,
        evidence_artifact_id=_uuid(
            ledger.get("quality_evidence_artifact_id"),
            label="quality evidence artifact ID",
        ),
        evaluated_by=str(ledger.get("quality_evaluated_by") or ""),
        evaluated_at=_timestamp(
            ledger.get("quality_evaluated_at"), label="quality evaluation time"
        ),
    )
    if ledger.get("quality_result_sha256") != expected_quality_fingerprint:
        raise StagingGoldenSliceError("quality result fingerprint drifted")

    if ledger.get("quality_resource_version_id") != ledger.get(
        "output_resource_version_id"
    ):
        raise StagingGoldenSliceError("quality result is not bound to the output")
    if ledger.get("lineage_target_resource_version_id") != ledger.get(
        "output_resource_version_id"
    ):
        raise StagingGoldenSliceError("lineage target is not bound to the output")
    if ledger.get("quality_evaluated_by") == ledger.get("terminal_actor_subject"):
        raise StagingGoldenSliceError("quality verdict is not independent")

    evidence_times = [
        _timestamp(ledger.get(field), label=field)
        for field in (
            "run_submitted_at",
            "run_started_at",
            "run_terminal_at",
            "terminal_event_occurred_at",
            "attempt_observed_at",
            "output_created_at",
            "quality_evaluated_at",
            "lineage_occurred_at",
        )
    ]
    if min(evidence_times) < pod_not_before:
        raise StagingGoldenSliceError(
            "selected Run predates the newest ready staging Pod"
        )
    terminal_at = _timestamp(ledger.get("run_terminal_at"), label="Run terminal time")
    age = (current - terminal_at).total_seconds()
    if age < -300:
        raise StagingGoldenSliceError("selected Run terminal time is in the future")
    if age > max_run_age_seconds:
        raise StagingGoldenSliceError("selected Run is stale")

    golden = {
        "schema": GOLDEN_SLICE_SCHEMA,
        "environment": "staging",
        "status": "passed",
        **binding,
        "tenant_id": tenant_id,
        "capability_id": capability_id,
        "definition_version_id": canonical_definition_id,
        "definition_sha256": ledger["definition_sha256"],
        "input_resource_version_id": canonical_input_id,
        "output_resource_version_id": ledger["output_resource_version_id"],
        "run_id": canonical_run_id,
        "output_artifact_sha256": ledger["output_artifact_sha256"],
        "quality_result_id": ledger["quality_result_id"],
        "quality_evidence_fingerprint": ledger["quality_result_sha256"],
        "lineage_event_id": ledger["lineage_event_id"],
        "run_success_evidence_fingerprint": ledger[
            "run_success_evidence_fingerprint"
        ],
        "observed_at": current.isoformat(),
        "evidence_fingerprint": "",
    }
    golden["evidence_fingerprint"] = golden_slice_fingerprint(golden)
    return golden


def _load_json_object(path: str, *, label: str) -> dict[str, Any]:
    try:
        raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise StagingGoldenSliceError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise StagingGoldenSliceError(f"{label} must be a JSON object")
    return value


def load_golden_ledger_export(path: str) -> dict[str, Any]:
    """Load the exact allowlisted row emitted by the protected SQL exporter."""
    export = _load_json_object(path, label="golden ledger export")
    if set(export) != {"schema", "rows"}:
        raise StagingGoldenSliceError("golden ledger export fields are invalid")
    if export.get("schema") != LEDGER_EXPORT_SCHEMA:
        raise StagingGoldenSliceError("golden ledger export schema is unsupported")
    rows = export.get("rows")
    if not isinstance(rows, list) or len(rows) != 1:
        raise StagingGoldenSliceError(
            "selected Run did not resolve to exactly one evidence set"
        )
    row = rows[0]
    if not isinstance(row, dict) or set(row) != GOLDEN_LEDGER_FIELDS:
        raise StagingGoldenSliceError("golden ledger evidence fields are invalid")
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--capability-id", required=True)
    parser.add_argument("--definition-version-id", required=True)
    parser.add_argument("--input-resource-version-id", required=True)
    parser.add_argument("--ledger-evidence", required=True)
    parser.add_argument("--live-collection", required=True)
    parser.add_argument("--max-run-age-seconds", type=float, default=3600)
    args = parser.parse_args(argv)
    try:
        golden = build_staging_golden_slice(
            load_golden_ledger_export(args.ledger_evidence),
            _load_json_object(args.live_collection, label="live collection"),
            tenant_id=args.tenant_id,
            run_id=args.run_id,
            capability_id=args.capability_id,
            definition_version_id=args.definition_version_id,
            input_resource_version_id=args.input_resource_version_id,
            max_run_age_seconds=args.max_run_age_seconds,
        )
    except StagingGoldenSliceError as exc:
        print(f"staging golden slice blocked: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(golden, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
