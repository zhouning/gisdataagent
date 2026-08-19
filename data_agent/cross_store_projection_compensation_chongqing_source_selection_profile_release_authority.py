"""Durable authority for Chongqing source-selection profile release histories.

The repository persists immutable technical release-history snapshots. It does
not approve a profile, promote it to production, or authorize Provider calls.
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
from .cross_store_projection_compensation_chongqing_source_selection_profile_release import (
    ChongqingSourceSelectionProfileReleaseHistory,
)
from .db_engine import get_engine
from .temporal_entity_authority import GATEWAY_DATABASE_ROLE

CHONGQING_SOURCE_SELECTION_PROFILE_RELEASE_AUTHORITY_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "185_chongqing_source_selection_profile_release_authority.sql"
)


class ChongqingSourceSelectionProfileReleaseAuthorityError(RuntimeError):
    """Base error for the durable profile-release authority."""


class ChongqingSourceSelectionProfileReleaseAuthorityConfigurationError(
    ChongqingSourceSelectionProfileReleaseAuthorityError
):
    """The database cannot enforce or read the release authority."""


class ChongqingSourceSelectionProfileReleaseAuthorityForbiddenError(
    ChongqingSourceSelectionProfileReleaseAuthorityError
):
    """The current role or tenant context was denied."""


class ChongqingSourceSelectionProfileReleaseAuthorityValidationError(
    ChongqingSourceSelectionProfileReleaseAuthorityError
):
    """A release history or authority query is invalid."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _postgres_validation_message(exc: DBAPIError) -> str:
    diagnostic = getattr(getattr(exc, "orig", None), "diag", None)
    detail = getattr(diagnostic, "message_primary", None)
    if isinstance(detail, str) and detail.strip():
        return f"source-selection profile release history was rejected: {detail.strip()}"
    return "source-selection profile release history was rejected"


class PostgresChongqingSourceSelectionProfileReleaseAuthorityStore:
    """Tenant-bound append-only repository and callback-time current reader."""

    def __init__(self, tenant_id: str, engine: Any = None):
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ChongqingSourceSelectionProfileReleaseAuthorityValidationError(
                "source-selection profile release authority tenant_id is required"
            )
        self.tenant_id = tenant_id.strip()
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise ChongqingSourceSelectionProfileReleaseAuthorityConfigurationError(
                "source-selection profile release authority requires PostgreSQL"
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
                            ChongqingSourceSelectionProfileReleaseAuthorityConfigurationError(
                                "database login is not a member of the platform gateway role"
                            )
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": self.tenant_id},
                    )
                    yield connection
        except ChongqingSourceSelectionProfileReleaseAuthorityError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state == "42501":
                raise ChongqingSourceSelectionProfileReleaseAuthorityForbiddenError(
                    "source-selection profile release authority tenant or role was denied"
                ) from exc
            if state in {"22023", "22P02", "23502", "23505", "23514", "40001", "55000"}:
                raise ChongqingSourceSelectionProfileReleaseAuthorityValidationError(
                    _postgres_validation_message(exc)
                ) from exc
            raise ChongqingSourceSelectionProfileReleaseAuthorityConfigurationError(
                "source-selection profile release authority operation failed"
            ) from exc
        except SQLAlchemyError as exc:
            raise ChongqingSourceSelectionProfileReleaseAuthorityConfigurationError(
                "source-selection profile release authority operation failed"
            ) from exc

    @staticmethod
    def _history(document: Any) -> ChongqingSourceSelectionProfileReleaseHistory:
        try:
            return ChongqingSourceSelectionProfileReleaseHistory.model_validate(
                _json_value(document)
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise ChongqingSourceSelectionProfileReleaseAuthorityConfigurationError(
                "stored source-selection profile release history is invalid"
            ) from exc

    @staticmethod
    def _identity(profile_id: str, scenario_id: str) -> tuple[str, str]:
        if not isinstance(profile_id, str) or not profile_id.strip():
            raise ChongqingSourceSelectionProfileReleaseAuthorityValidationError(
                "source-selection profile release profile_id is required"
            )
        if scenario_id not in {"heping_review", "banzhu_adjustment"}:
            raise ChongqingSourceSelectionProfileReleaseAuthorityValidationError(
                "source-selection profile release scenario_id is invalid"
            )
        return profile_id.strip(), scenario_id

    def record(
        self,
        history: ChongqingSourceSelectionProfileReleaseHistory,
    ) -> ChongqingSourceSelectionProfileReleaseHistory:
        """Append one complete, sealed history snapshot through governed SQL."""

        try:
            history = ChongqingSourceSelectionProfileReleaseHistory.model_validate(
                history.model_dump(mode="python")
            )
        except (AttributeError, TypeError, ValueError, ValidationError) as exc:
            raise ChongqingSourceSelectionProfileReleaseAuthorityValidationError(
                "source-selection profile release history is invalid"
            ) from exc
        if history.tenant_id != self.tenant_id:
            raise ChongqingSourceSelectionProfileReleaseAuthorityForbiddenError(
                "source-selection profile release history tenant differs from the store"
            )
        active = history.active_release
        with self._transaction() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT history_document, created
                    FROM gda_control.
                         record_chongqing_source_selection_profile_release_history(
                        :tenant_id, :profile_id, :scenario_id,
                        :active_release_version, :active_release_sha256,
                        :history_sha256, CAST(:history_document AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": self.tenant_id,
                    "profile_id": history.profile_id,
                    "scenario_id": history.scenario_id,
                    "active_release_version": active.release_version,
                    "active_release_sha256": active.release_sha256,
                    "history_sha256": history.history_sha256,
                    "history_document": _json(history.model_dump(mode="json")),
                },
            ).mappings().one()
        stored = self._history(row["history_document"])
        if stored != history:
            raise ChongqingSourceSelectionProfileReleaseAuthorityConfigurationError(
                "profile release authority returned a different history"
            )
        return stored

    def release_history_current(
        self,
        profile_id: str,
        scenario_id: str,
    ) -> ChongqingSourceSelectionProfileReleaseHistory | None:
        """Read the active history snapshot for the existing execution port."""

        profile_id, scenario_id = self._identity(profile_id, scenario_id)
        with self._transaction() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT history_document
                    FROM gda_control.
                         chongqing_source_selection_profile_release_history_current
                    WHERE tenant_id = :tenant_id
                      AND profile_id = :profile_id
                      AND scenario_id = :scenario_id
                    """
                ),
                {
                    "tenant_id": self.tenant_id,
                    "profile_id": profile_id,
                    "scenario_id": scenario_id,
                },
            ).mappings().one_or_none()
        return None if row is None else self._history(row["history_document"])

    def history_snapshots(
        self,
        profile_id: str,
        scenario_id: str,
    ) -> tuple[ChongqingSourceSelectionProfileReleaseHistory, ...]:
        """Read every immutable history snapshot in release-version order."""

        profile_id, scenario_id = self._identity(profile_id, scenario_id)
        with self._transaction() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT history_document
                    FROM gda_control.chongqing_source_selection_profile_release_history
                    WHERE tenant_id = :tenant_id
                      AND profile_id = :profile_id
                      AND scenario_id = :scenario_id
                    ORDER BY active_release_version
                    """
                ),
                {
                    "tenant_id": self.tenant_id,
                    "profile_id": profile_id,
                    "scenario_id": scenario_id,
                },
            ).mappings().all()
        return tuple(self._history(row["history_document"]) for row in rows)


__all__ = [
    "CHONGQING_SOURCE_SELECTION_PROFILE_RELEASE_AUTHORITY_MIGRATION",
    "ChongqingSourceSelectionProfileReleaseAuthorityConfigurationError",
    "ChongqingSourceSelectionProfileReleaseAuthorityError",
    "ChongqingSourceSelectionProfileReleaseAuthorityForbiddenError",
    "ChongqingSourceSelectionProfileReleaseAuthorityValidationError",
    "PostgresChongqingSourceSelectionProfileReleaseAuthorityStore",
]
