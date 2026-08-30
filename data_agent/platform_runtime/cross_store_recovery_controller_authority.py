"""PostgreSQL durable ledger for cross-store recovery controller snapshots."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from ..cross_store_projection_authority import _sqlstate
from ..db_engine import get_engine
from ..temporal_entity_authority import GATEWAY_DATABASE_ROLE
from .cross_store_recovery_controller import (
    CrossStoreRecoveryControllerError,
    CrossStoreRecoveryControllerEvent,
    CrossStoreRecoveryControllerLedger,
    CrossStoreRecoveryControllerSnapshot,
    CrossStoreRecoveryRunState,
)

CONTROLLER_AUTHORITY_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "233_cross_store_recovery_controller_authority.sql"
)


class CrossStoreRecoveryControllerAuthorityError(RuntimeError):
    """Base error for the durable controller ledger."""


class CrossStoreRecoveryControllerAuthorityConfigurationError(
    CrossStoreRecoveryControllerAuthorityError
):
    """The database or gateway role cannot enforce the controller contract."""


class CrossStoreRecoveryControllerAuthorityForbiddenError(
    CrossStoreRecoveryControllerAuthorityError
):
    """The controller ledger tenant boundary was denied."""


class CrossStoreRecoveryControllerAuthorityValidationError(
    CrossStoreRecoveryControllerAuthorityError,
    CrossStoreRecoveryControllerError,
):
    """The controller snapshot or event chain was rejected."""


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _snapshot(document: Any) -> CrossStoreRecoveryControllerSnapshot:
    value = _json_value(document)
    if not isinstance(value, dict):
        raise CrossStoreRecoveryControllerAuthorityConfigurationError(
            "stored controller snapshot is not an object"
        )
    try:
        events = tuple(
            CrossStoreRecoveryControllerEvent(
                sequence=int(item["sequence"]),
                event_type=item["event_type"],
                occurred_at=datetime.fromisoformat(
                    str(item["occurred_at"]).replace("Z", "+00:00")
                ),
                detail=dict(item.get("detail") or {}),
                event_sha256=item["event_sha256"],
            )
            for item in value["events"]
        )
        result = CrossStoreRecoveryControllerSnapshot(
            run_id=value["run_id"],
            state=CrossStoreRecoveryRunState(value["state"]),
            next_action=value["next_action"],
            tenant_ids=tuple(value["tenant_ids"]),
            binding_sha256=value.get("binding_sha256"),
            events=events,
            snapshot_sha256=value["snapshot_sha256"],
        )
        result.validate()
        return result
    except (KeyError, TypeError, ValueError, CrossStoreRecoveryControllerError) as exc:
        raise CrossStoreRecoveryControllerAuthorityConfigurationError(
            "stored controller snapshot is invalid"
        ) from exc


class PostgresCrossStoreRecoveryControllerLedger(
    CrossStoreRecoveryControllerLedger
):
    """Tenant-copy ledger with one transaction for all covered tenants."""

    def __init__(self, tenant_ids: tuple[str, ...], engine: Any = None):
        normalized = tuple(tenant_ids)
        if not normalized or tuple(sorted(set(normalized))) != normalized:
            raise CrossStoreRecoveryControllerAuthorityValidationError(
                "controller authority tenant ids must be sorted and unique"
            )
        self.tenant_ids = normalized
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise CrossStoreRecoveryControllerAuthorityConfigurationError(
                "cross-store recovery controller authority requires PostgreSQL"
            )
        return engine

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        try:
            with self._get_engine().connect() as connection:
                with connection.begin():
                    try:
                        connection.exec_driver_sql(
                            f'SET LOCAL ROLE "{GATEWAY_DATABASE_ROLE}"'
                        )
                    except DBAPIError as exc:
                        raise CrossStoreRecoveryControllerAuthorityConfigurationError(
                            "database login is not a member of the platform gateway role"
                        ) from exc
                    yield connection
        except CrossStoreRecoveryControllerAuthorityError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state == "42501":
                raise CrossStoreRecoveryControllerAuthorityForbiddenError(
                    "controller ledger tenant or database role was denied"
                ) from exc
            if state in {"22023", "23514", "40001", "23505", "55000"}:
                raise CrossStoreRecoveryControllerAuthorityValidationError(
                    "controller ledger evidence or append-only contract was rejected"
                ) from exc
            raise CrossStoreRecoveryControllerAuthorityConfigurationError(
                "controller ledger operation failed"
            ) from exc
        except SQLAlchemyError as exc:
            raise CrossStoreRecoveryControllerAuthorityConfigurationError(
                "controller ledger operation failed"
            ) from exc

    def _check_snapshot(self, snapshot: CrossStoreRecoveryControllerSnapshot) -> None:
        try:
            snapshot.validate()
        except CrossStoreRecoveryControllerError as exc:
            raise CrossStoreRecoveryControllerAuthorityValidationError(str(exc)) from exc
        if snapshot.tenant_ids and snapshot.tenant_ids != self.tenant_ids:
            raise CrossStoreRecoveryControllerAuthorityForbiddenError(
                "controller snapshot tenants do not match authority tenants"
            )

    @staticmethod
    def _document(snapshot: CrossStoreRecoveryControllerSnapshot) -> str:
        return json.dumps(
            snapshot.as_dict(),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )

    def append(
        self, snapshot: CrossStoreRecoveryControllerSnapshot
    ) -> CrossStoreRecoveryControllerSnapshot:
        self._check_snapshot(snapshot)
        documents: list[Any] = []
        with self._transaction() as connection:
            for tenant_id in self.tenant_ids:
                connection.execute(
                    text("SELECT set_config('app.current_tenant', :tenant, true)"),
                    {"tenant": tenant_id},
                )
                row = connection.execute(
                    text(
                        """
                        SELECT snapshot_document, created
                        FROM gda_control.record_cross_store_recovery_controller_snapshot(
                            :tenant_id, :run_id, CAST(:snapshot_document AS jsonb),
                            :snapshot_sha256
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "run_id": snapshot.run_id,
                        "snapshot_document": self._document(snapshot),
                        "snapshot_sha256": snapshot.snapshot_sha256,
                    },
                ).mappings().one()
                documents.append(row["snapshot_document"])
        stored = tuple(_snapshot(document) for document in documents)
        if not stored or any(item.as_dict() != stored[0].as_dict() for item in stored[1:]):
            raise CrossStoreRecoveryControllerAuthorityConfigurationError(
                "controller ledger tenant copies differ"
            )
        if stored[0].as_dict() != snapshot.as_dict():
            raise CrossStoreRecoveryControllerAuthorityConfigurationError(
                "controller ledger returned a different snapshot"
            )
        return stored[0]

    def current(self, run_id: str) -> CrossStoreRecoveryControllerSnapshot | None:
        documents: list[Any] = []
        missing = False
        with self._transaction() as connection:
            for tenant_id in self.tenant_ids:
                connection.execute(
                    text("SELECT set_config('app.current_tenant', :tenant, true)"),
                    {"tenant": tenant_id},
                )
                row = connection.execute(
                    text(
                        """
                        SELECT snapshot_document
                        FROM gda_control.cross_store_recovery_controller_current
                        WHERE tenant_id = :tenant_id AND run_id = :run_id
                        """
                    ),
                    {"tenant_id": tenant_id, "run_id": run_id},
                ).mappings().one_or_none()
                if row is None:
                    missing = True
                    continue
                documents.append(row["snapshot_document"])
        if missing and documents:
            raise CrossStoreRecoveryControllerAuthorityConfigurationError(
                "controller ledger tenant current snapshots are incomplete"
            )
        if not documents:
            return None
        snapshots = tuple(_snapshot(document) for document in documents)
        if any(item.as_dict() != snapshots[0].as_dict() for item in snapshots[1:]):
            raise CrossStoreRecoveryControllerAuthorityConfigurationError(
                "controller ledger tenant current snapshots differ"
            )
        return snapshots[0]

    def history(self, run_id: str) -> tuple[CrossStoreRecoveryControllerSnapshot, ...]:
        histories: list[tuple[CrossStoreRecoveryControllerSnapshot, ...]] = []
        with self._transaction() as connection:
            for tenant_id in self.tenant_ids:
                connection.execute(
                    text("SELECT set_config('app.current_tenant', :tenant, true)"),
                    {"tenant": tenant_id},
                )
                rows = connection.execute(
                    text(
                        """
                        SELECT snapshot_document
                        FROM gda_control.cross_store_recovery_controller_history
                        WHERE tenant_id = :tenant_id AND run_id = :run_id
                        ORDER BY snapshot_version
                        """
                    ),
                    {"tenant_id": tenant_id, "run_id": run_id},
                ).mappings().all()
                histories.append(tuple(_snapshot(row["snapshot_document"]) for row in rows))
        if not histories or any(item != histories[0] for item in histories[1:]):
            raise CrossStoreRecoveryControllerAuthorityConfigurationError(
                "controller ledger tenant histories differ"
            )
        return histories[0]


__all__ = [
    "CONTROLLER_AUTHORITY_MIGRATION",
    "CrossStoreRecoveryControllerAuthorityConfigurationError",
    "CrossStoreRecoveryControllerAuthorityError",
    "CrossStoreRecoveryControllerAuthorityForbiddenError",
    "CrossStoreRecoveryControllerAuthorityValidationError",
    "PostgresCrossStoreRecoveryControllerLedger",
]
