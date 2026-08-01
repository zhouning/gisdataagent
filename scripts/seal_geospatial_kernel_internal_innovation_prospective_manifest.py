#!/usr/bin/env python3
"""Seal one real issue-time manifest for outcome-free Manning execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

if __package__:
    from scripts.assess_geospatial_kernel_internal_innovation_episode_preflight import (
        ADDENDUM_PATH,
        ADDENDUM_SCHEMA,
        EXPECTED_PROTOCOL_FILE_SHA256,
        EXPECTED_PROTOCOL_SEAL_SHA256,
        MANIFEST_SCHEMA,
        PROTOCOL_PATH,
        REPO_ROOT,
        REQUIRED_INPUT_ARTIFACTS,
        SYSTEM_IDS,
        assess_manifest,
    )
else:
    from assess_geospatial_kernel_internal_innovation_episode_preflight import (
        ADDENDUM_PATH,
        ADDENDUM_SCHEMA,
        EXPECTED_PROTOCOL_FILE_SHA256,
        EXPECTED_PROTOCOL_SEAL_SHA256,
        MANIFEST_SCHEMA,
        PROTOCOL_PATH,
        REPO_ROOT,
        REQUIRED_INPUT_ARTIFACTS,
        SYSTEM_IDS,
        assess_manifest,
    )

SCHEMA = "gwm.geospatial_kernel.prospective_manifest_issuance.v1"
MANNING_OPERATOR_SCHEMA = "gwm.geospatial_kernel.branching_manning_network_storage.v1"
MAXIMUM_ISSUANCE_LATENCY = timedelta(minutes=15)
_SOURCE_INPUT_NAMES = tuple(
    name for name in REQUIRED_INPUT_ARTIFACTS if name != "input_availability_receipts"
)
_FORBIDDEN_KEYS = {
    "outcome_values",
    "outcome_columns",
    "outcome_manifest",
    "outcome_path",
    "outcome_url",
    "future_target_observations",
    "score_report",
    "candidate_fit_parameters",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode-id", required=True)
    parser.add_argument("--system-id", choices=SYSTEM_IDS, required=True)
    parser.add_argument("--forecast-issue-time", required=True)
    parser.add_argument("--support-start", required=True)
    for name in _SOURCE_INPUT_NAMES:
        parser.add_argument(f"--{name.replace('_', '-')}", type=Path, required=True)
    parser.add_argument("--input-availability-receipts", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL_PATH)
    parser.add_argument("--execution-addendum", type=Path, default=ADDENDUM_PATH)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--enable-prospective-manifest-sealing",
        action="store_true",
        help="Acknowledge real issue-time sealing; no outcome or fit is performed.",
    )
    return parser.parse_args()


def seal_prospective_manifest(
    *,
    episode_id: str,
    system_id: str,
    forecast_issue_time: datetime,
    support_start: datetime,
    input_artifact_paths: Mapping[str, Path],
    input_availability_receipts_path: Path,
    output_path: Path,
    protocol_path: Path = PROTOCOL_PATH,
    execution_addendum_path: Path = ADDENDUM_PATH,
    repo_root: Path = REPO_ROOT,
    enable_prospective_manifest_sealing: bool = False,
    sealed_at: datetime | None = None,
) -> dict[str, Any]:
    """Validate, preflight, and exclusively publish one prospective manifest."""

    if enable_prospective_manifest_sealing is not True:
        raise RuntimeError("internal_innovation_prospective_manifest_sealing_disabled")
    if not isinstance(episode_id, str) or not episode_id.strip() or system_id not in SYSTEM_IDS:
        raise ValueError("internal_innovation_prospective_manifest_identity_invalid")
    issue_time = _aware_datetime(forecast_issue_time, "forecast_issue_time")
    start = _aware_datetime(support_start, "support_start")
    sealing_time = _aware_datetime(
        sealed_at if sealed_at is not None else _now(),
        "sealed_at",
    )
    if (
        sealing_time < issue_time
        or sealing_time > issue_time + MAXIMUM_ISSUANCE_LATENCY
        or sealing_time >= start
        or issue_time > start
    ):
        raise ValueError("internal_innovation_prospective_manifest_ordering_invalid")
    if set(input_artifact_paths) != set(_SOURCE_INPUT_NAMES):
        raise ValueError("internal_innovation_prospective_manifest_input_inventory_invalid")

    root = Path(repo_root).resolve()
    source_artifacts = {
        name: _load_source_artifact(
            root,
            Path(input_artifact_paths[name]),
            expected_schema=REQUIRED_INPUT_ARTIFACTS[name],
            episode_id=episode_id,
            system_id=system_id,
        )
        for name in _SOURCE_INPUT_NAMES
    }
    receipt_path = _inside_root(root, input_availability_receipts_path)
    receipt_body = receipt_path.read_bytes()
    receipts = _strict_json_object(receipt_body)
    if _find_forbidden_content(receipts):
        raise ValueError("internal_innovation_prospective_manifest_outcome_content_forbidden")
    if (
        receipts.get("schema") != REQUIRED_INPUT_ARTIFACTS["input_availability_receipts"]
        or receipts.get("episode_id") != episode_id
        or receipts.get("system_id") != system_id
        or not _nonempty_string(receipts.get("issuer_id"))
    ):
        raise ValueError("internal_innovation_prospective_manifest_receipts_invalid")
    receipt_issued_at = _time_text(receipts.get("issued_at"), "receipt_issued_at")
    if receipt_issued_at > issue_time or receipt_issued_at > sealing_time:
        raise ValueError("internal_innovation_prospective_manifest_receipt_ordering_invalid")
    receipt_rows = _receipt_rows(receipts.get("receipts"))
    descriptors = {}
    for name, source in source_artifacts.items():
        receipt = receipt_rows[name]
        available_at = _time_text(receipt.get("available_at"), f"{name}_available_at")
        if (
            receipt.get("artifact_sha256") != source["sha256"]
            or available_at > issue_time
            or not _nonempty_string(receipt.get("source_id"))
        ):
            raise ValueError(
                "internal_innovation_prospective_manifest_source_receipt_mismatch"
            )
        descriptors[name] = {
            **source,
            "available_at": receipt["available_at"],
            "provenance_id": receipt["source_id"],
        }
    descriptors["input_availability_receipts"] = {
        "path": receipt_path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(receipt_body).hexdigest(),
        "size_bytes": len(receipt_body),
        "schema": REQUIRED_INPUT_ARTIFACTS["input_availability_receipts"],
        "available_at": receipts["issued_at"],
        "provenance_id": receipts["issuer_id"],
    }

    protocol = _protocol_descriptor(root, protocol_path)
    addendum = _addendum_descriptor(root, execution_addendum_path)
    support_end = start + timedelta(hours=24)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "episode_id": episode_id,
        "system_id": system_id,
        "operator_schema": MANNING_OPERATOR_SCHEMA,
        "forecast_issue_time": issue_time.isoformat(),
        "support": {
            "start_inclusive": start.isoformat(),
            "end_exclusive": support_end.isoformat(),
            "time_step_seconds": 3600,
            "step_count": 24,
        },
        "protocol": protocol,
        "execution_addendum": addendum,
        "artifacts": descriptors,
        "issuance": {
            "schema": SCHEMA,
            "sealed_at": sealing_time.isoformat(),
            "input_inventory_complete": True,
            "source_availability_receipts_sha256": descriptors[
                "input_availability_receipts"
            ]["sha256"],
            "trusted_external_timestamp_verified": False,
            "preflight_required_before_publish": True,
            "outcome_argument_accepted": False,
            "outcome_values_loaded": False,
            "physical_rollout_executed": False,
            "innovation_fit_executed": False,
            "network_requests_performed": False,
        },
        "claim_boundary": {
            "outcomes_included": False,
            "retrospective_replay": False,
            "inputs_frozen_before_execution": True,
        },
    }
    if _find_forbidden_content(manifest):
        raise ValueError("internal_innovation_prospective_manifest_outcome_content_forbidden")
    target = _new_output_path(root, output_path)
    body = _canonical_json_bytes(manifest)
    preflight = _preflight_and_publish(
        root=root,
        target=target,
        body=body,
        protocol_path=protocol_path,
    )
    return {
        "schema": SCHEMA,
        "status": "prospective_manifest_sealed_preflight_ready",
        "manifest_artifact": {
            "path": target.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(body).hexdigest(),
            "size_bytes": len(body),
            "schema": MANIFEST_SCHEMA,
        },
        "episode_id": episode_id,
        "system_id": system_id,
        "forecast_issue_time": issue_time.isoformat(),
        "sealed_at": sealing_time.isoformat(),
        "preflight": preflight,
        "data_isolation": {
            "outcome_argument_accepted": False,
            "outcome_values_loaded": False,
            "physical_rollout_executed": False,
            "innovation_fit_executed": False,
            "network_requests_performed": False,
        },
        "claim_boundary": {
            "source_receipts_hash_bound": True,
            "trusted_external_timestamp_verified": False,
            "prospective_manifest_sealed": True,
            "physical_prediction_executed": False,
            "outcomes_acquired": False,
            "innovation_fitted": False,
            "candidate_promoted": False,
            "runtime_enabled": False,
            "geospatial_kernel_validated": False,
        },
    }


def _load_source_artifact(
    root: Path,
    path_value: Path,
    *,
    expected_schema: str,
    episode_id: str,
    system_id: str,
) -> dict[str, object]:
    path = _inside_root(root, path_value)
    body = path.read_bytes()
    payload = _strict_json_object(body)
    if _find_forbidden_content(payload):
        raise ValueError("internal_innovation_prospective_manifest_outcome_content_forbidden")
    if (
        payload.get("schema") != expected_schema
        or payload.get("episode_id") != episode_id
        or payload.get("system_id") != system_id
    ):
        raise ValueError("internal_innovation_prospective_manifest_source_identity_invalid")
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
        "schema": expected_schema,
    }


def _receipt_rows(value: object) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, list) or len(value) != len(_SOURCE_INPUT_NAMES):
        raise ValueError("internal_innovation_prospective_manifest_receipts_invalid")
    rows = {}
    for row in value:
        if not isinstance(row, dict) or not _nonempty_string(row.get("artifact_name")):
            raise ValueError("internal_innovation_prospective_manifest_receipts_invalid")
        name = str(row["artifact_name"])
        if name in rows:
            raise ValueError("internal_innovation_prospective_manifest_receipts_invalid")
        rows[name] = row
    if set(rows) != set(_SOURCE_INPUT_NAMES):
        raise ValueError("internal_innovation_prospective_manifest_receipts_invalid")
    return rows


def _protocol_descriptor(root: Path, path_value: Path) -> dict[str, object]:
    path = _inside_root(root, path_value)
    body = path.read_bytes()
    payload = _strict_json_object(body)
    if (
        hashlib.sha256(body).hexdigest() != EXPECTED_PROTOCOL_FILE_SHA256
        or payload.get("protocol_seal", {}).get("sha256")
        != EXPECTED_PROTOCOL_SEAL_SHA256
    ):
        raise ValueError("internal_innovation_prospective_manifest_protocol_mismatch")
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": EXPECTED_PROTOCOL_FILE_SHA256,
        "protocol_seal_sha256": EXPECTED_PROTOCOL_SEAL_SHA256,
    }


def _addendum_descriptor(root: Path, path_value: Path) -> dict[str, object]:
    path = _inside_root(root, path_value)
    body = path.read_bytes()
    payload = _strict_json_object(body)
    seal = payload.get("addendum_seal")
    if (
        payload.get("schema") != ADDENDUM_SCHEMA
        or not isinstance(seal, dict)
        or not _valid_sha256(seal.get("sha256"))
    ):
        raise ValueError("internal_innovation_prospective_manifest_addendum_invalid")
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
        "schema": ADDENDUM_SCHEMA,
        "addendum_seal_sha256": seal["sha256"],
    }


def _preflight_and_publish(
    *,
    root: Path,
    target: Path,
    body: bytes,
    protocol_path: Path,
) -> dict[str, Any]:
    descriptor = tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=f".{target.name}.",
        suffix=".preflight",
        dir=target.parent,
        delete=False,
    )
    temporary = Path(descriptor.name)
    published = False
    try:
        with descriptor:
            descriptor.write(body)
            descriptor.flush()
            os.fsync(descriptor.fileno())
        assessment = assess_manifest(
            temporary,
            repo_root=root,
            protocol_path=protocol_path,
        )
        if assessment.get("episode_execution_ready") is not True:
            raise ValueError("internal_innovation_prospective_manifest_preflight_failed")
        try:
            os.link(temporary, target)
        except FileExistsError as error:
            raise FileExistsError(
                "internal_innovation_prospective_manifest_output_conflict"
            ) from error
        published = True
    finally:
        temporary.unlink(missing_ok=True)
    if not published:
        raise RuntimeError("internal_innovation_prospective_manifest_publish_failed")
    return assess_manifest(target, repo_root=root, protocol_path=protocol_path)


def _new_output_path(root: Path, path_value: Path) -> Path:
    candidate = path_value if path_value.is_absolute() else root / path_value
    if candidate.is_symlink():
        raise ValueError("internal_innovation_prospective_manifest_symlink_forbidden")
    resolved_parent = candidate.parent.resolve()
    try:
        resolved_parent.relative_to(root)
    except ValueError as error:
        raise ValueError(
            "internal_innovation_prospective_manifest_path_outside_repository"
        ) from error
    if not resolved_parent.is_dir():
        raise ValueError("internal_innovation_prospective_manifest_output_parent_missing")
    target = resolved_parent / candidate.name
    if target.exists():
        raise FileExistsError("internal_innovation_prospective_manifest_output_conflict")
    return target


def _inside_root(root: Path, path_value: Path) -> Path:
    candidate = path_value if path_value.is_absolute() else root / path_value
    if candidate.is_symlink():
        raise ValueError("internal_innovation_prospective_manifest_symlink_forbidden")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(
            "internal_innovation_prospective_manifest_path_outside_repository"
        ) from error
    if not resolved.is_file():
        raise ValueError("internal_innovation_prospective_manifest_artifact_missing")
    return resolved


def _strict_json_object(body: bytes) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("internal_innovation_prospective_manifest_json_duplicate_key")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> None:
        raise ValueError(f"internal_innovation_prospective_manifest_json_nonfinite:{value}")

    try:
        payload = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite,
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("internal_innovation_prospective_manifest_json_invalid") from error
    if not isinstance(payload, dict):
        raise ValueError("internal_innovation_prospective_manifest_json_root_not_object")
    return payload


def _find_forbidden_content(value: object, location: str = "$") -> list[str]:
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_location = f"{location}.{key}"
            if key in _FORBIDDEN_KEYS:
                found.append(child_location)
            found.extend(_find_forbidden_content(child, child_location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_find_forbidden_content(child, f"{location}[{index}]"))
    return found


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _aware_datetime(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"internal_innovation_prospective_manifest_{name}_invalid")
    return value


def _time_text(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"internal_innovation_prospective_manifest_{name}_invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"internal_innovation_prospective_manifest_{name}_invalid") from error
    return _aware_datetime(parsed, name)


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _now() -> datetime:
    return datetime.now(UTC)


def main() -> int:
    args = parse_args()
    input_paths = {
        name: getattr(args, name)
        for name in _SOURCE_INPUT_NAMES
    }
    report = seal_prospective_manifest(
        episode_id=args.episode_id,
        system_id=args.system_id,
        forecast_issue_time=_time_text(args.forecast_issue_time, "forecast_issue_time"),
        support_start=_time_text(args.support_start, "support_start"),
        input_artifact_paths=input_paths,
        input_availability_receipts_path=args.input_availability_receipts,
        output_path=args.output,
        protocol_path=args.protocol,
        execution_addendum_path=args.execution_addendum,
        enable_prospective_manifest_sealing=args.enable_prospective_manifest_sealing,
    )
    print(report["manifest_artifact"]["path"])
    print(f"status={report['status']}")
    print(f"sha256={report['manifest_artifact']['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
