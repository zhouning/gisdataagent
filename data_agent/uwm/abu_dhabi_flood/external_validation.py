"""Sanitized audit view of Abu Dhabi GWM external-validation receipts.

The source receipts and prediction arrays are private local artifacts.  This
module verifies the receipt hashes, keeps the confirmatory and supplementary
cohorts separate, and exposes only aggregate metrics and claim boundaries.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

DEFAULT_VALIDATION_WORKSPACE = (
    Path.home() / "Downloads/阿布扎比/GDB提交版_模型工作区_20260821"
)
DEFAULT_CONFIRMATORY_RECEIPT = (
    DEFAULT_VALIDATION_WORKSPACE
    / "customer_gwm_confirmatory_external_validation_20260916_v1"
    / "evaluation_v3"
    / "run_receipt.json"
)
DEFAULT_SUPPLEMENTARY_RECEIPT = (
    DEFAULT_VALIDATION_WORKSPACE
    / "customer_gwm_supplementary_external_validation_20260917_v1"
    / "evaluation_final_v1"
    / "run_receipt.json"
)

CONFIRMATORY_SCHEMA = "gwm.abu_dhabi_flood.confirmatory_evaluation.v1"
SUPPLEMENTARY_SCHEMA = (
    "gwm.abu_dhabi_flood.supplementary_external_validation_evaluation.v1"
)
CONFIRMATORY_TARGET_EVENT_COUNT = 5


def _configured_receipt(environment_name: str, default: Path) -> Path:
    configured = os.environ.get(environment_name, "").strip()
    return Path(configured).expanduser() if configured else default


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: dict[str, Any], *, ensure_ascii: bool) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=ensure_ascii,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii" if ensure_ascii else "utf-8")
    ).hexdigest()


def _read_verified_receipt(
    path: Path,
    *,
    expected_schema: str,
    ensure_ascii: bool,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    audit: dict[str, Any] = {
        "available": False,
        "schema_valid": False,
        "integrity_verified": False,
    }
    try:
        raw = path.read_text(encoding="utf-8")
        value = json.loads(raw)
    except FileNotFoundError:
        audit["error_code"] = "receipt_not_found"
        return None, audit
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        audit["error_code"] = "receipt_unreadable"
        return None, audit
    if not isinstance(value, dict):
        audit["error_code"] = "receipt_not_object"
        return None, audit

    audit["available"] = True
    audit["file_sha256"] = _sha256(path)
    audit["schema_valid"] = value.get("schema") == expected_schema
    claimed = str(value.get("receipt_sha256") or "")
    unhashed = dict(value)
    unhashed.pop("receipt_sha256", None)
    computed = _canonical_sha256(unhashed, ensure_ascii=ensure_ascii)
    audit.update(
        {
            "declared_sha256": claimed,
            "computed_content_sha256": computed,
            "integrity_verified": bool(claimed) and claimed == computed,
        }
    )
    if not audit["schema_valid"]:
        audit["error_code"] = "receipt_schema_mismatch"
    elif not audit["integrity_verified"]:
        audit["error_code"] = "receipt_hash_mismatch"
    return value, audit


def _event_ids(receipt: dict[str, Any] | None) -> list[str]:
    if receipt is None or not isinstance(receipt.get("event_ids"), list):
        return []
    return [
        value.strip()
        for value in receipt["event_ids"]
        if isinstance(value, str) and value.strip()
    ]


def _model_metrics(rows: Any, *, value_keys: tuple[str, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if not isinstance(rows, list):
        return result
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("model"), str):
            continue
        result[row["model"]] = {
            key: row.get(key)
            for key in value_keys
            if key in row and isinstance(row.get(key), (int, float))
        }
    return result


def _supplementary_source_metrics(rows: Any) -> list[dict[str, Any]]:
    """Return source-specific metrics without ever pooling sensors."""

    allowed = (
        "observation_source",
        "space",
        "model",
        "event_count",
        "macro_iou",
        "macro_precision",
        "macro_recall",
        "macro_f1",
        "macro_brier_score",
    )
    if not isinstance(rows, list):
        return []
    sanitized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = {
            key: row.get(key)
            for key in allowed
            if isinstance(row.get(key), (str, int, float)) or row.get(key) is None
        }
        if item:
            sanitized.append(item)
    return sanitized


def _claim_boundary(receipt: dict[str, Any] | None) -> list[str]:
    if receipt is None or not isinstance(receipt.get("claim_boundary"), list):
        return []
    private_path_markers = ("/Users/", "/private/", "/tmp/", "/Volumes/", "\\")
    return [
        item.strip()
        for item in receipt["claim_boundary"]
        if isinstance(item, str)
        and item.strip()
        and not any(marker in item for marker in private_path_markers)
    ]


def external_validation_payload() -> dict[str, Any]:
    """Build a path-free, non-pooled audit ledger for authenticated clients."""

    confirmatory, confirmatory_audit = _read_verified_receipt(
        _configured_receipt(
            "ABU_DHABI_GWM_CONFIRMATORY_RECEIPT", DEFAULT_CONFIRMATORY_RECEIPT
        ),
        expected_schema=CONFIRMATORY_SCHEMA,
        ensure_ascii=True,
    )
    supplementary, supplementary_audit = _read_verified_receipt(
        _configured_receipt(
            "ABU_DHABI_GWM_SUPPLEMENTARY_RECEIPT", DEFAULT_SUPPLEMENTARY_RECEIPT
        ),
        expected_schema=SUPPLEMENTARY_SCHEMA,
        ensure_ascii=False,
    )

    confirmatory_ids = _event_ids(confirmatory)
    supplementary_ids = _event_ids(supplementary)
    confirmatory_set = set(confirmatory_ids)
    supplementary_set = set(supplementary_ids)
    overlap_count = len(confirmatory_set & supplementary_set)
    confirmatory_count = len(confirmatory_set)
    supplementary_count = len(supplementary_set)
    supplementary_target = int(
        (supplementary or {}).get("target_event_count")
        or CONFIRMATORY_TARGET_EVENT_COUNT
    )

    confirmatory_valid = bool(
        confirmatory_audit["schema_valid"]
        and confirmatory_audit["integrity_verified"]
    )
    supplementary_valid = bool(
        supplementary_audit["schema_valid"]
        and supplementary_audit["integrity_verified"]
    )
    event_ids_unique = (
        len(confirmatory_ids) == confirmatory_count
        and len(supplementary_ids) == supplementary_count
    )
    event_ids_disjoint = overlap_count == 0
    receipt_event_counts_consistent = bool(
        int((confirmatory or {}).get("event_count") or 0) == confirmatory_count
        and int((supplementary or {}).get("event_count") or 0) == supplementary_count
    )
    confirmatory_target_reached = (
        confirmatory_valid
        and confirmatory_count >= CONFIRMATORY_TARGET_EVENT_COUNT
    )
    supplementary_target_reached = bool(
        supplementary_valid
        and supplementary_count >= supplementary_target
        and (supplementary or {}).get("target_sample_size_reached") is True
    )

    if (
        confirmatory_valid
        and supplementary_valid
        and event_ids_unique
        and event_ids_disjoint
        and receipt_event_counts_consistent
    ):
        status = "completed_evidence_limited"
    elif confirmatory_audit["available"] or supplementary_audit["available"]:
        status = "partial_or_invalid"
    else:
        status = "unavailable"

    confirmatory_receipt = confirmatory or {}
    supplementary_receipt = supplementary or {}
    engineering_admitted = False
    admission_reason_codes = [
        "satellite_masks_are_not_observed_depth",
        "engineering_calibration_not_established",
    ]
    if not confirmatory_target_reached:
        admission_reason_codes.insert(0, "strict_confirmatory_target_not_reached")
    if not supplementary_target_reached:
        admission_reason_codes.insert(1, "supplementary_target_not_reached")
    return {
        "schema": "gwm.abu_dhabi_flood.external_validation_summary.v1",
        "status": status,
        "strict_confirmatory": {
            "status": confirmatory_receipt.get("status") or "unavailable",
            "evidence_class": "confirmatory_small_n",
            "observation_source": "sentinel2_cloud_screened_surface_water",
            "event_count": confirmatory_count,
            "target_event_count": CONFIRMATORY_TARGET_EVENT_COUNT,
            "target_sample_size_reached": confirmatory_target_reached,
            "receipt": confirmatory_audit,
            "physics_emulation": _model_metrics(
                confirmatory_receipt.get("physics_emulation_macro_metrics"),
                value_keys=(
                    "macro_depth_mae_m",
                    "macro_depth_rmse_m",
                    "macro_physics_binary_iou",
                ),
            ),
            "sentinel2_observation": _model_metrics(
                confirmatory_receipt.get("sentinel2_macro_metrics"),
                value_keys=("macro_iou", "macro_precision", "macro_recall"),
            ),
            "claim_boundary": _claim_boundary(confirmatory),
        },
        "supplementary": {
            "status": supplementary_receipt.get("status") or "unavailable",
            "evidence_class": "exploratory_supplementary_underpowered",
            "event_count": supplementary_count,
            "target_event_count": supplementary_target,
            "target_sample_size_reached": supplementary_target_reached,
            "receipt": supplementary_audit,
            "source_specific_metrics": _supplementary_source_metrics(
                supplementary_receipt.get("source_specific_metrics")
            ),
            "claim_boundary": _claim_boundary(supplementary),
        },
        "cross_cohort": {
            "independent_event_count": len(confirmatory_set | supplementary_set),
            "overlap_event_count": overlap_count,
            "event_ids_unique_within_cohorts": event_ids_unique,
            "event_ids_disjoint": event_ids_disjoint,
            "performance_metrics_pooled": False,
            "pooling_prohibited_reason": "different_sensor_observation_contracts",
        },
        "engineering_admission": {
            "admitted": engineering_admitted,
            "status": "not_admitted",
            "reason_codes": admission_reason_codes,
        },
        "audit": {
            "all_available_receipts_integrity_verified": bool(
                confirmatory_valid and supplementary_valid
            ),
            "event_deduplication_passed": bool(event_ids_unique and event_ids_disjoint),
            "receipt_event_counts_consistent": receipt_event_counts_consistent,
            "raw_paths_exposed": False,
            "raw_prediction_arrays_exposed": False,
        },
    }
