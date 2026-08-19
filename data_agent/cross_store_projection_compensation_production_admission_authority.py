"""Durable append-only authority for five-Provider production admission.

The repository records explicit admission decisions. It cannot derive a grant
from technical baselines and it never invokes a Provider.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .cross_store_projection_authority import _sqlstate
from .cross_store_projection_compensation_production_admission import (
    ChongqingFiveProviderProductionAdmissionHistory,
)
from .db_engine import get_engine
from .temporal_entity_authority import GATEWAY_DATABASE_ROLE

CHONGQING_FIVE_PROVIDER_PRODUCTION_ADMISSION_AUTHORITY_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "187_chongqing_five_provider_production_admission_authority.sql"
)


class ChongqingFiveProviderProductionAdmissionAuthorityError(RuntimeError):
    """Base error for the durable production admission authority."""


class ChongqingFiveProviderProductionAdmissionAuthorityConfigurationError(
    ChongqingFiveProviderProductionAdmissionAuthorityError
):
    """PostgreSQL cannot enforce or read the admission authority."""


class ChongqingFiveProviderProductionAdmissionAuthorityForbiddenError(
    ChongqingFiveProviderProductionAdmissionAuthorityError
):
    """The current role or tenant context was denied."""


class ChongqingFiveProviderProductionAdmissionAuthorityValidationError(
    ChongqingFiveProviderProductionAdmissionAuthorityError
):
    """An admission history or authority query is invalid."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _postgres_validation_message(exc: DBAPIError) -> str:
    diagnostic = getattr(getattr(exc, "orig", None), "diag", None)
    detail = getattr(diagnostic, "message_primary", None)
    if isinstance(detail, str) and detail.strip():
        return f"five-Provider production admission history was rejected: {detail.strip()}"
    return "five-Provider production admission history was rejected"


class PostgresChongqingFiveProviderProductionAdmissionAuthorityStore:
    """Tenant-bound append-only repository and callback-time current reader."""

    def __init__(self, tenant_id: str, engine: Any = None):
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ChongqingFiveProviderProductionAdmissionAuthorityValidationError(
                "five-Provider production admission tenant_id is required"
            )
        self.tenant_id = tenant_id.strip()
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise ChongqingFiveProviderProductionAdmissionAuthorityConfigurationError(
                "five-Provider production admission authority requires PostgreSQL"
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
                        raise (
                            ChongqingFiveProviderProductionAdmissionAuthorityConfigurationError(
                                "database login is not a member of the platform gateway role"
                            )
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": self.tenant_id},
                    )
                    yield connection
        except ChongqingFiveProviderProductionAdmissionAuthorityError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state == "42501":
                raise ChongqingFiveProviderProductionAdmissionAuthorityForbiddenError(
                    "five-Provider production admission tenant or role was denied"
                ) from exc
            if state in {
                "22007",
                "22023",
                "22P02",
                "23502",
                "23505",
                "23514",
                "40001",
                "55000",
            }:
                raise ChongqingFiveProviderProductionAdmissionAuthorityValidationError(
                    _postgres_validation_message(exc)
                ) from exc
            raise ChongqingFiveProviderProductionAdmissionAuthorityConfigurationError(
                "five-Provider production admission authority operation failed"
            ) from exc
        except SQLAlchemyError as exc:
            raise ChongqingFiveProviderProductionAdmissionAuthorityConfigurationError(
                "five-Provider production admission authority operation failed"
            ) from exc

    @staticmethod
    def _history(document: Any) -> ChongqingFiveProviderProductionAdmissionHistory:
        try:
            return ChongqingFiveProviderProductionAdmissionHistory.model_validate(
                _json_value(document)
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise ChongqingFiveProviderProductionAdmissionAuthorityConfigurationError(
                "stored five-Provider production admission history is invalid"
            ) from exc

    @staticmethod
    def _run_id(run_id: str) -> str:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ChongqingFiveProviderProductionAdmissionAuthorityValidationError(
                "five-Provider production admission run_id is required"
            )
        if len(run_id.strip()) > 512:
            raise ChongqingFiveProviderProductionAdmissionAuthorityValidationError(
                "five-Provider production admission run_id is too long"
            )
        return run_id.strip()

    def record(
        self,
        history: ChongqingFiveProviderProductionAdmissionHistory,
    ) -> ChongqingFiveProviderProductionAdmissionHistory:
        """Append one complete sealed lifecycle snapshot through governed SQL."""

        try:
            history = ChongqingFiveProviderProductionAdmissionHistory.model_validate(
                history.model_dump(mode="python")
            )
        except (AttributeError, TypeError, ValueError, ValidationError) as exc:
            raise ChongqingFiveProviderProductionAdmissionAuthorityValidationError(
                "five-Provider production admission history is invalid"
            ) from exc
        if history.tenant_id != self.tenant_id:
            raise ChongqingFiveProviderProductionAdmissionAuthorityForbiddenError(
                "five-Provider production admission history tenant differs from the store"
            )
        current = history.current_event
        with self._transaction() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT history_document, created
                    FROM gda_control.
                         record_chongqing_five_provider_production_admission_history(
                        :tenant_id, :run_id, :current_event_version,
                        :current_event_sha256, :history_sha256,
                        CAST(:history_document AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": self.tenant_id,
                    "run_id": history.run_id,
                    "current_event_version": current.event_version,
                    "current_event_sha256": current.event_sha256,
                    "history_sha256": history.history_sha256,
                    "history_document": _json(history.model_dump(mode="json")),
                },
            ).mappings().one()
        stored = self._history(row["history_document"])
        if stored != history:
            raise ChongqingFiveProviderProductionAdmissionAuthorityConfigurationError(
                "production admission authority returned a different history"
            )
        return stored

    def admission_history_current(
        self,
        run_id: str,
    ) -> ChongqingFiveProviderProductionAdmissionHistory | None:
        """Read the latest lifecycle snapshot for callback-time admission."""

        run_id = self._run_id(run_id)
        with self._transaction() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT history_document
                    FROM gda_control.
                         chongqing_five_provider_production_admission_history_current
                    WHERE tenant_id = :tenant_id AND run_id = :run_id
                    """
                ),
                {"tenant_id": self.tenant_id, "run_id": run_id},
            ).mappings().one_or_none()
        return None if row is None else self._history(row["history_document"])

    def history_snapshots(
        self,
        run_id: str,
    ) -> tuple[ChongqingFiveProviderProductionAdmissionHistory, ...]:
        """Read every immutable snapshot in lifecycle-version order."""

        run_id = self._run_id(run_id)
        with self._transaction() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT history_document
                    FROM gda_control.
                         chongqing_five_provider_production_admission_history
                    WHERE tenant_id = :tenant_id AND run_id = :run_id
                    ORDER BY current_event_version
                    """
                ),
                {"tenant_id": self.tenant_id, "run_id": run_id},
            ).mappings().all()
        return tuple(self._history(row["history_document"]) for row in rows)


__all__ = [
    "CHONGQING_FIVE_PROVIDER_PRODUCTION_ADMISSION_AUTHORITY_MIGRATION",
    "ChongqingFiveProviderProductionAdmissionAuthorityConfigurationError",
    "ChongqingFiveProviderProductionAdmissionAuthorityError",
    "ChongqingFiveProviderProductionAdmissionAuthorityForbiddenError",
    "ChongqingFiveProviderProductionAdmissionAuthorityValidationError",
    "PostgresChongqingFiveProviderProductionAdmissionAuthorityStore",
]
