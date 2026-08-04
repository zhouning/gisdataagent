"""Single-node reference registry for one-shot state-prior evaluations."""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from .state_prior_transition_execution import (
    DAM_GK_STATE_PRIOR_SINGLE_USE_FINALIZATION_SCHEMA,
    DAM_GK_STATE_PRIOR_SINGLE_USE_RESERVATION_SCHEMA,
    compute_state_prior_transition_single_use_finalization_sha256,
    compute_state_prior_transition_single_use_reservation_sha256,
)

DAM_GK_STATE_PRIOR_SINGLE_USE_REGISTRY_RECORD_SCHEMA = (
    "gwm.geospatial_kernel.state_prior_transition_single_use_registry_record.v1"
)
SQLITE_STATE_PRIOR_SINGLE_USE_REGISTRY_BACKEND = "sqlite_reference_single_node"

_NO_INDEPENDENT_CLAIM = {
    "single_use_registry_receipt_only": True,
    "scientific_result_claim": False,
    "transition_skill_improvement_claim": False,
    "policy_causal_effect_claim": False,
    "general_geospatial_world_model_validation_claim": False,
}
_EXECUTION_RECEIPT_NO_INDEPENDENT_CLAIM = {
    "single_use_execution_receipt_only": True,
    "scientific_result_claim": False,
    "transition_skill_improvement_claim": False,
    "policy_causal_effect_claim": False,
    "general_geospatial_world_model_validation_claim": False,
}


class SQLiteStatePriorTransitionSingleUseRegistry:
    """Append-only SQLite reference backend for cross-path attempt uniqueness."""

    def __init__(self, database_path: Path, *, timeout_seconds: float = 5.0) -> None:
        if not isinstance(database_path, Path):
            raise TypeError("single_use_registry_database_path_must_be_path")
        if not database_path.parent.is_dir():
            raise ValueError("single_use_registry_database_parent_must_exist")
        if timeout_seconds <= 0:
            raise ValueError("single_use_registry_timeout_must_be_positive")
        self.database_path = database_path
        self.timeout_seconds = float(timeout_seconds)
        self.registry_uri = database_path.resolve().as_uri()
        self._initialize()

    def reserve(self, receipt: Mapping[str, Any]) -> dict[str, Any]:
        """Atomically reserve a globally unique single-use key."""

        reservation = _validated_reservation(receipt)
        key = reservation["single_use_key_sha256"]
        reservation_sha256 = reservation["reservation_receipt_sha256"]
        reservation_json = _canonical_json(reservation)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO single_use_attempts (
                        single_use_key_sha256,
                        reservation_receipt_sha256,
                        reservation_json,
                        registered_at
                    ) VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                    """,
                    (key, reservation_sha256, reservation_json),
                )
                connection.execute(
                    """
                    INSERT INTO single_use_events (
                        single_use_key_sha256,
                        sequence_number,
                        event_type,
                        receipt_sha256,
                        receipt_json,
                        recorded_at
                    ) VALUES (?, 1, 'reserved', ?, ?,
                              strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                    """,
                    (key, reservation_sha256, reservation_json),
                )
                record = self._build_record(connection, key)
        except sqlite3.IntegrityError as exc:
            raise RuntimeError("single_use_registry_key_already_reserved") from exc
        self._require_valid_record(record, reservation=reservation, finalization=None)
        return record

    def record_finalization(self, receipt: Mapping[str, Any]) -> dict[str, Any]:
        """Append the sole terminal event for an existing reservation."""

        finalization = _validated_finalization(receipt)
        reservation = finalization["reservation"]
        key = reservation["single_use_key_sha256"]
        finalization_sha256 = finalization["finalization_receipt_sha256"]
        finalization_json = _canonical_json(finalization)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                stored = connection.execute(
                    """
                    SELECT reservation_json
                    FROM single_use_attempts
                    WHERE single_use_key_sha256 = ?
                    """,
                    (key,),
                ).fetchone()
                if stored is None:
                    raise RuntimeError("single_use_registry_reservation_not_found")
                if json.loads(stored["reservation_json"]) != reservation:
                    raise RuntimeError("single_use_registry_reservation_receipt_mismatch")
                existing = connection.execute(
                    """
                    SELECT 1
                    FROM single_use_events
                    WHERE single_use_key_sha256 = ? AND sequence_number = 2
                    """,
                    (key,),
                ).fetchone()
                if existing is not None:
                    raise RuntimeError("single_use_registry_already_finalized")
                connection.execute(
                    """
                    INSERT INTO single_use_events (
                        single_use_key_sha256,
                        sequence_number,
                        event_type,
                        receipt_sha256,
                        receipt_json,
                        recorded_at
                    ) VALUES (?, 2, ?, ?, ?,
                              strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                    """,
                    (
                        key,
                        finalization["status"],
                        finalization_sha256,
                        finalization_json,
                    ),
                )
                record = self._build_record(connection, key)
        except sqlite3.IntegrityError as exc:
            raise RuntimeError("single_use_registry_already_finalized") from exc
        self._require_valid_record(
            record,
            reservation=reservation,
            finalization=finalization,
        )
        return record

    def get_record(self, single_use_key_sha256: str) -> dict[str, Any]:
        """Read and validate the current immutable event chain for one key."""

        if not _valid_sha256(single_use_key_sha256):
            raise ValueError("single_use_registry_key_sha256_invalid")
        with self._connect() as connection:
            record = self._build_record(connection, single_use_key_sha256)
        reservation = record["reservation_receipt"]
        finalization = record["finalization_receipt"]
        self._require_valid_record(
            record,
            reservation=reservation,
            finalization=finalization,
        )
        return record

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS single_use_attempts (
                    single_use_key_sha256 TEXT PRIMARY KEY,
                    reservation_receipt_sha256 TEXT NOT NULL UNIQUE,
                    reservation_json TEXT NOT NULL,
                    registered_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS single_use_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    single_use_key_sha256 TEXT NOT NULL,
                    sequence_number INTEGER NOT NULL CHECK (sequence_number IN (1, 2)),
                    event_type TEXT NOT NULL
                        CHECK (event_type IN ('reserved', 'completed', 'failed')),
                    receipt_sha256 TEXT NOT NULL,
                    receipt_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    FOREIGN KEY (single_use_key_sha256)
                        REFERENCES single_use_attempts(single_use_key_sha256),
                    UNIQUE (single_use_key_sha256, sequence_number)
                );

                CREATE TRIGGER IF NOT EXISTS single_use_attempts_no_update
                BEFORE UPDATE ON single_use_attempts
                BEGIN
                    SELECT RAISE(ABORT, 'single_use_registry_append_only');
                END;

                CREATE TRIGGER IF NOT EXISTS single_use_attempts_no_delete
                BEFORE DELETE ON single_use_attempts
                BEGIN
                    SELECT RAISE(ABORT, 'single_use_registry_append_only');
                END;

                CREATE TRIGGER IF NOT EXISTS single_use_events_no_update
                BEFORE UPDATE ON single_use_events
                BEGIN
                    SELECT RAISE(ABORT, 'single_use_registry_append_only');
                END;

                CREATE TRIGGER IF NOT EXISTS single_use_events_no_delete
                BEFORE DELETE ON single_use_events
                BEGIN
                    SELECT RAISE(ABORT, 'single_use_registry_append_only');
                END;
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=self.timeout_seconds,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _build_record(
        self,
        connection: sqlite3.Connection,
        single_use_key_sha256: str,
    ) -> dict[str, Any]:
        attempt = connection.execute(
            """
            SELECT reservation_json
            FROM single_use_attempts
            WHERE single_use_key_sha256 = ?
            """,
            (single_use_key_sha256,),
        ).fetchone()
        if attempt is None:
            raise KeyError("single_use_registry_key_not_found")
        rows = connection.execute(
            """
            SELECT sequence_number, event_type, receipt_sha256, receipt_json, recorded_at
            FROM single_use_events
            WHERE single_use_key_sha256 = ?
            ORDER BY sequence_number ASC
            """,
            (single_use_key_sha256,),
        ).fetchall()
        reservation = json.loads(attempt["reservation_json"])
        finalization = json.loads(rows[1]["receipt_json"]) if len(rows) == 2 else None
        status = finalization["status"] if finalization is not None else "reserved"
        record = {
            "schema": DAM_GK_STATE_PRIOR_SINGLE_USE_REGISTRY_RECORD_SCHEMA,
            "version": "0.1",
            "backend": SQLITE_STATE_PRIOR_SINGLE_USE_REGISTRY_BACKEND,
            "registry_uri": self.registry_uri,
            "single_use_key_sha256": single_use_key_sha256,
            "status": status,
            "reservation_receipt": reservation,
            "finalization_receipt": finalization,
            "events": [
                {
                    "sequence": row["sequence_number"],
                    "event_type": row["event_type"],
                    "receipt_sha256": row["receipt_sha256"],
                    "recorded_at": row["recorded_at"],
                }
                for row in rows
            ],
            "rerun_permitted": False,
            "claim_boundary": copy.deepcopy(_NO_INDEPENDENT_CLAIM),
        }
        record["registry_record_sha256"] = (
            compute_state_prior_transition_single_use_registry_record_sha256(record)
        )
        return record

    @staticmethod
    def _require_valid_record(
        record: Mapping[str, Any],
        *,
        reservation: Mapping[str, Any],
        finalization: Mapping[str, Any] | None,
    ) -> None:
        validation = validate_state_prior_transition_single_use_registry_record(
            record,
            reservation=reservation,
            finalization=finalization,
        )
        if not validation["valid"]:
            raise RuntimeError(
                "single_use_registry_record_invalid:" + ";".join(validation["errors"])
            )


def validate_state_prior_transition_single_use_registry_record(
    payload: Any,
    *,
    reservation: Mapping[str, Any],
    finalization: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Validate a registry artifact against the local receipt chain."""

    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["single_use_registry_record_must_be_dictionary"]}
    errors: list[str] = []
    expected_fields = {
        "schema",
        "version",
        "backend",
        "registry_uri",
        "single_use_key_sha256",
        "status",
        "reservation_receipt",
        "finalization_receipt",
        "events",
        "rerun_permitted",
        "claim_boundary",
        "registry_record_sha256",
    }
    if set(payload) != expected_fields:
        errors.append("single_use_registry_record_field_set_mismatch")
    if payload.get("schema") != DAM_GK_STATE_PRIOR_SINGLE_USE_REGISTRY_RECORD_SCHEMA:
        errors.append("single_use_registry_record_schema_mismatch")
    if payload.get("version") != "0.1":
        errors.append("single_use_registry_record_version_mismatch")
    if payload.get("backend") != SQLITE_STATE_PRIOR_SINGLE_USE_REGISTRY_BACKEND:
        errors.append("single_use_registry_record_backend_mismatch")
    if not _nonempty_string(payload.get("registry_uri")):
        errors.append("single_use_registry_record_uri_required")

    reservation_values = dict(reservation) if isinstance(reservation, Mapping) else {}
    finalization_values = dict(finalization) if isinstance(finalization, Mapping) else None
    if payload.get("reservation_receipt") != reservation_values:
        errors.append("single_use_registry_record_reservation_mismatch")
    expected_key = reservation_values.get("single_use_key_sha256")
    if not _valid_sha256(expected_key) or payload.get("single_use_key_sha256") != expected_key:
        errors.append("single_use_registry_record_key_sha256_mismatch")
    if payload.get("finalization_receipt") != finalization_values:
        errors.append("single_use_registry_record_finalization_mismatch")
    expected_status = finalization_values.get("status") if finalization_values else "reserved"
    if finalization_values is not None and expected_status not in {"completed", "failed"}:
        errors.append("single_use_registry_record_finalization_status_invalid")
    if payload.get("status") != expected_status:
        errors.append("single_use_registry_record_status_mismatch")

    if reservation_values:
        expected_reservation_sha256 = reservation_values.get("reservation_receipt_sha256")
        if reservation_values.get("schema") != DAM_GK_STATE_PRIOR_SINGLE_USE_RESERVATION_SCHEMA:
            errors.append("single_use_registry_record_reservation_schema_mismatch")
        if (
            reservation_values.get("version") != "0.1"
            or reservation_values.get("status") != "reserved"
        ):
            errors.append("single_use_registry_record_reservation_status_invalid")
        if reservation_values.get("rerun_permitted") is not False:
            errors.append("single_use_registry_record_reservation_rerun_must_be_false")
        if reservation_values.get("claim_boundary") != _EXECUTION_RECEIPT_NO_INDEPENDENT_CLAIM:
            errors.append("single_use_registry_record_reservation_claim_boundary_invalid")
        if expected_reservation_sha256 != (
            compute_state_prior_transition_single_use_reservation_sha256(reservation_values)
        ):
            errors.append("single_use_registry_record_reservation_sha256_mismatch")
    else:
        expected_reservation_sha256 = None

    expected_events: list[tuple[int, str, Any]] = [(1, "reserved", expected_reservation_sha256)]
    if finalization_values is not None:
        expected_finalization_sha256 = finalization_values.get("finalization_receipt_sha256")
        if finalization_values.get("schema") != DAM_GK_STATE_PRIOR_SINGLE_USE_FINALIZATION_SCHEMA:
            errors.append("single_use_registry_record_finalization_schema_mismatch")
        if finalization_values.get("reservation") != reservation_values:
            errors.append("single_use_registry_record_finalization_reservation_mismatch")
        if finalization_values.get("version") != "0.1":
            errors.append("single_use_registry_record_finalization_version_mismatch")
        if finalization_values.get("rerun_permitted") is not False:
            errors.append("single_use_registry_record_finalization_rerun_must_be_false")
        if finalization_values.get("claim_boundary") != _EXECUTION_RECEIPT_NO_INDEPENDENT_CLAIM:
            errors.append("single_use_registry_record_finalization_claim_boundary_invalid")
        if expected_finalization_sha256 != (
            compute_state_prior_transition_single_use_finalization_sha256(finalization_values)
        ):
            errors.append("single_use_registry_record_finalization_sha256_mismatch")
        expected_events.append((2, str(expected_status), expected_finalization_sha256))

    events = payload.get("events")
    if not isinstance(events, list) or len(events) != len(expected_events):
        errors.append("single_use_registry_record_event_count_mismatch")
    else:
        previous_recorded_at: datetime | None = None
        for event, (sequence, event_type, receipt_sha256) in zip(
            events, expected_events, strict=True
        ):
            if not isinstance(event, dict) or set(event) != {
                "sequence",
                "event_type",
                "receipt_sha256",
                "recorded_at",
            }:
                errors.append("single_use_registry_record_event_field_set_mismatch")
                continue
            if event.get("sequence") != sequence:
                errors.append("single_use_registry_record_event_sequence_mismatch")
            if event.get("event_type") != event_type:
                errors.append("single_use_registry_record_event_type_mismatch")
            if event.get("receipt_sha256") != receipt_sha256:
                errors.append("single_use_registry_record_event_receipt_sha256_mismatch")
            recorded_at = _parse_aware_timestamp(event.get("recorded_at"))
            if recorded_at is None:
                errors.append("single_use_registry_record_event_recorded_at_invalid")
            elif previous_recorded_at is not None and recorded_at < previous_recorded_at:
                errors.append("single_use_registry_record_event_order_invalid")
            if recorded_at is not None:
                previous_recorded_at = recorded_at

    if payload.get("rerun_permitted") is not False:
        errors.append("single_use_registry_record_rerun_must_be_false")
    if payload.get("claim_boundary") != _NO_INDEPENDENT_CLAIM:
        errors.append("single_use_registry_record_claim_boundary_invalid")
    record_sha256 = payload.get("registry_record_sha256")
    if not _valid_sha256(record_sha256):
        errors.append("single_use_registry_record_sha256_invalid")
    elif record_sha256 != (
        compute_state_prior_transition_single_use_registry_record_sha256(payload)
    ):
        errors.append("single_use_registry_record_sha256_mismatch")
    return {"valid": not errors, "errors": errors}


def compute_state_prior_transition_single_use_registry_record_sha256(
    payload: Mapping[str, Any],
) -> str:
    """Compute the canonical digest of one registry audit record."""

    values = copy.deepcopy(dict(payload))
    values.pop("registry_record_sha256", None)
    return hashlib.sha256(_canonical_json(values).encode("utf-8")).hexdigest()


def _validated_reservation(receipt: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(receipt, Mapping):
        raise TypeError("single_use_registry_reservation_must_be_mapping")
    values = copy.deepcopy(dict(receipt))
    if values.get("schema") != DAM_GK_STATE_PRIOR_SINGLE_USE_RESERVATION_SCHEMA:
        raise ValueError("single_use_registry_reservation_schema_mismatch")
    if values.get("status") != "reserved" or values.get("rerun_permitted") is not False:
        raise ValueError("single_use_registry_reservation_status_invalid")
    if values.get("claim_boundary") != _EXECUTION_RECEIPT_NO_INDEPENDENT_CLAIM:
        raise ValueError("single_use_registry_reservation_claim_boundary_invalid")
    if not _valid_sha256(values.get("single_use_key_sha256")):
        raise ValueError("single_use_registry_key_sha256_invalid")
    if values.get("reservation_receipt_sha256") != (
        compute_state_prior_transition_single_use_reservation_sha256(values)
    ):
        raise ValueError("single_use_registry_reservation_sha256_mismatch")
    return values


def _validated_finalization(receipt: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(receipt, Mapping):
        raise TypeError("single_use_registry_finalization_must_be_mapping")
    values = copy.deepcopy(dict(receipt))
    if values.get("schema") != DAM_GK_STATE_PRIOR_SINGLE_USE_FINALIZATION_SCHEMA:
        raise ValueError("single_use_registry_finalization_schema_mismatch")
    if values.get("status") not in {"completed", "failed"}:
        raise ValueError("single_use_registry_finalization_status_invalid")
    reservation = values.get("reservation")
    if not isinstance(reservation, Mapping):
        raise ValueError("single_use_registry_finalization_reservation_invalid")
    _validated_reservation(reservation)
    if values.get("rerun_permitted") is not False:
        raise ValueError("single_use_registry_finalization_rerun_must_be_false")
    if values.get("claim_boundary") != _EXECUTION_RECEIPT_NO_INDEPENDENT_CLAIM:
        raise ValueError("single_use_registry_finalization_claim_boundary_invalid")
    if values.get("finalization_receipt_sha256") != (
        compute_state_prior_transition_single_use_finalization_sha256(values)
    ):
        raise ValueError("single_use_registry_finalization_sha256_mismatch")
    return values


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _valid_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(character in "0123456789abcdef" for character in value)


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _parse_aware_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed
