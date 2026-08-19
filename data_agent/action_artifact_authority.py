"""PostgreSQL authority for immutable Proposal/ChangeSet/ActionResult artifacts.

The authority stores sealed documents only. PlatformRun remains the execution
state authority and no ActionRun scheduler is introduced here.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .action_runtime import ActionResult, ChangeSet, ProposalArtifact
from .cross_store_projection_authority import _sqlstate
from .db_engine import get_engine
from .temporal_entity_authority import GATEWAY_DATABASE_ROLE

ACTION_ARTIFACT_AUTHORITY_MIGRATION = (
    Path(__file__).resolve().parent / "migrations" / "196_action_artifact_authority.sql"
)


class ActionArtifactAuthorityError(RuntimeError):
    """Base error for the action artifact authority."""


class ActionArtifactAuthorityConfigurationError(ActionArtifactAuthorityError):
    """The database cannot enforce or read the artifact authority."""


class ActionArtifactAuthorityForbiddenError(ActionArtifactAuthorityError):
    """The current role or tenant context was denied."""


class ActionArtifactAuthorityConflictError(ActionArtifactAuthorityError):
    """An immutable identity is already bound to different content."""


class ActionArtifactAuthorityValidationError(ActionArtifactAuthorityError):
    """An artifact identity or document is invalid."""


class ActionArtifactKind(StrEnum):
    PROPOSAL = "proposal"
    CHANGE_SET = "change_set"
    ACTION_RESULT = "action_result"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _artifact_identity(
    artifact: ProposalArtifact | ChangeSet | ActionResult,
) -> tuple[ActionArtifactKind, str, str, UUID | None]:
    if isinstance(artifact, ProposalArtifact):
        return (
            ActionArtifactKind.PROPOSAL,
            artifact.proposal_sha256,
            str(artifact.proposal_artifact_id),
            artifact.proposed_run_id,
        )
    if isinstance(artifact, ChangeSet):
        return (
            ActionArtifactKind.CHANGE_SET,
            artifact.change_set_sha256,
            f"{artifact.action_definition_sha256}:{artifact.idempotency_key}",
            None,
        )
    if isinstance(artifact, ActionResult):
        return (
            ActionArtifactKind.ACTION_RESULT,
            artifact.result_sha256,
            str(artifact.run_id),
            artifact.run_id,
        )
    raise ActionArtifactAuthorityValidationError("unsupported action artifact type")


class PostgresActionArtifactAuthority:
    """Tenant-bound append-only repository with one governed write function."""

    def __init__(self, tenant_id: str, engine: Any = None):
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ActionArtifactAuthorityValidationError("artifact tenant_id is required")
        self.tenant_id = tenant_id.strip()
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise ActionArtifactAuthorityConfigurationError(
                "action artifact authority requires PostgreSQL"
            )
        return engine

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        try:
            with self._get_engine().connect() as connection:
                with connection.begin():
                    try:
                        connection.exec_driver_sql(f'SET LOCAL ROLE "{GATEWAY_DATABASE_ROLE}"')
                    except DBAPIError as exc:
                        raise ActionArtifactAuthorityConfigurationError(
                            "database login is not a member of the platform gateway role"
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": self.tenant_id},
                    )
                    yield connection
        except ActionArtifactAuthorityError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state == "42501":
                raise ActionArtifactAuthorityForbiddenError(
                    "action artifact tenant or role was denied"
                ) from exc
            if state == "23505":
                raise ActionArtifactAuthorityConflictError(
                    "action artifact identity is already bound to different content"
                ) from exc
            if state in {"22023", "22P02", "23502", "23514", "55000"}:
                raise ActionArtifactAuthorityValidationError(
                    "action artifact evidence was rejected"
                ) from exc
            raise ActionArtifactAuthorityConfigurationError(
                "action artifact authority operation failed"
            ) from exc
        except SQLAlchemyError as exc:
            raise ActionArtifactAuthorityConfigurationError(
                "action artifact authority operation failed"
            ) from exc

    @staticmethod
    def _validate_stored(
        kind: ActionArtifactKind, document: Any
    ) -> ProposalArtifact | ChangeSet | ActionResult:
        try:
            model: type[ProposalArtifact | ChangeSet | ActionResult] = {
                ActionArtifactKind.PROPOSAL: ProposalArtifact,
                ActionArtifactKind.CHANGE_SET: ChangeSet,
                ActionArtifactKind.ACTION_RESULT: ActionResult,
            }[kind]
            return model.model_validate(_json_value(document))
        except (TypeError, ValueError, ValidationError) as exc:
            raise ActionArtifactAuthorityConfigurationError(
                "stored action artifact is invalid"
            ) from exc

    def record(
        self, artifact: ProposalArtifact | ChangeSet | ActionResult
    ) -> ProposalArtifact | ChangeSet | ActionResult:
        try:
            artifact = type(artifact).model_validate(artifact.model_dump(mode="python"))
        except (AttributeError, TypeError, ValueError, ValidationError) as exc:
            raise ActionArtifactAuthorityValidationError("action artifact is invalid") from exc
        tenant_id = getattr(artifact, "tenant_id", None)
        if tenant_id != self.tenant_id:
            raise ActionArtifactAuthorityForbiddenError("action artifact tenant differs")
        kind, artifact_sha256, identity_key, run_id = _artifact_identity(artifact)
        with self._transaction() as connection:
            row = (
                connection.execute(
                    text(
                        """
                    SELECT artifact_document, created
                    FROM gda_control.record_action_artifact(
                        :tenant_id, :artifact_kind, :artifact_sha256,
                        :identity_key, :run_id, CAST(:artifact_document AS jsonb)
                    )
                    """
                    ),
                    {
                        "tenant_id": self.tenant_id,
                        "artifact_kind": kind.value,
                        "artifact_sha256": artifact_sha256,
                        "identity_key": identity_key,
                        "run_id": run_id,
                        "artifact_document": _json(artifact.model_dump(mode="json")),
                    },
                )
                .mappings()
                .one()
            )
        stored = self._validate_stored(kind, row["artifact_document"])
        if stored != artifact:
            raise ActionArtifactAuthorityConfigurationError(
                "action artifact authority returned different content"
            )
        return stored

    def get(
        self, kind: ActionArtifactKind, artifact_sha256: str
    ) -> ProposalArtifact | ChangeSet | ActionResult | None:
        if not isinstance(kind, ActionArtifactKind):
            raise ActionArtifactAuthorityValidationError("artifact kind is invalid")
        if (
            not isinstance(artifact_sha256, str)
            or len(artifact_sha256) != 64
            or any(character not in "0123456789abcdef" for character in artifact_sha256)
        ):
            raise ActionArtifactAuthorityValidationError("artifact SHA-256 is invalid")
        with self._transaction() as connection:
            row = (
                connection.execute(
                    text(
                        """
                    SELECT artifact_document
                    FROM gda_control.action_artifact
                    WHERE tenant_id = :tenant_id
                      AND artifact_kind = :artifact_kind
                      AND artifact_sha256 = :artifact_sha256
                    """
                    ),
                    {
                        "tenant_id": self.tenant_id,
                        "artifact_kind": kind.value,
                        "artifact_sha256": artifact_sha256,
                    },
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else self._validate_stored(kind, row["artifact_document"])


__all__ = [
    "ACTION_ARTIFACT_AUTHORITY_MIGRATION",
    "ActionArtifactAuthorityConfigurationError",
    "ActionArtifactAuthorityConflictError",
    "ActionArtifactAuthorityError",
    "ActionArtifactAuthorityForbiddenError",
    "ActionArtifactAuthorityValidationError",
    "ActionArtifactKind",
    "PostgresActionArtifactAuthority",
]
