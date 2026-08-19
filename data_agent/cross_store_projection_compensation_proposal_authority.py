"""PostgreSQL authority for immutable federated compensation proposals."""

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
from .cross_store_projection_compensation_proposal import (
    FederatedProjectionCompensationProposal,
    FederatedProjectionCompensationProposalError,
    FederatedProjectionCompensationProposalReadRequest,
    FederatedProjectionCompensationProposalReadResponse,
)
from .db_engine import get_engine
from .temporal_entity_authority import GATEWAY_DATABASE_ROLE

FEDERATED_PROJECTION_COMPENSATION_PROPOSAL_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "178_cross_store_projection_compensation_proposal.sql"
)


class FederatedProjectionCompensationProposalAuthorityError(RuntimeError):
    """Base error for the durable proposal authority."""


class FederatedProjectionCompensationProposalConfigurationError(
    FederatedProjectionCompensationProposalAuthorityError
):
    """The database or gateway role cannot enforce proposal storage."""


class FederatedProjectionCompensationProposalForbiddenError(
    FederatedProjectionCompensationProposalAuthorityError
):
    """The current database role or tenant context was denied."""


class FederatedProjectionCompensationProposalValidationError(
    FederatedProjectionCompensationProposalAuthorityError,
    FederatedProjectionCompensationProposalError,
):
    """The proposal or its source recovery snapshot is invalid."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


class PostgresFederatedProjectionCompensationProposalStore:
    """Tenant-bound repository with a single governed append path."""

    def __init__(self, tenant_id: str, engine: Any = None):
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise FederatedProjectionCompensationProposalValidationError(
                "projection compensation proposal tenant_id is required"
            )
        self.tenant_id = tenant_id.strip()
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise FederatedProjectionCompensationProposalConfigurationError(
                "projection compensation proposal authority requires PostgreSQL"
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
                        raise FederatedProjectionCompensationProposalConfigurationError(
                            "database login is not a member of the platform gateway role"
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": self.tenant_id},
                    )
                    yield connection
        except FederatedProjectionCompensationProposalAuthorityError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state in {"23505", "40001", "55000"}:
                raise FederatedProjectionCompensationProposalError(
                    "projection compensation proposal idempotency conflict"
                ) from exc
            if state == "42501":
                raise FederatedProjectionCompensationProposalForbiddenError(
                    "projection compensation proposal tenant or role was denied"
                ) from exc
            if state in {"22023", "22P02", "23502", "23503", "23514"}:
                raise FederatedProjectionCompensationProposalValidationError(
                    "projection compensation proposal evidence was rejected"
                ) from exc
            raise FederatedProjectionCompensationProposalConfigurationError(
                "projection compensation proposal operation failed"
            ) from exc
        except SQLAlchemyError as exc:
            raise FederatedProjectionCompensationProposalConfigurationError(
                "projection compensation proposal operation failed"
            ) from exc

    @staticmethod
    def _proposal(document: Any) -> FederatedProjectionCompensationProposal:
        try:
            return FederatedProjectionCompensationProposal.model_validate(
                _json_value(document)
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise FederatedProjectionCompensationProposalConfigurationError(
                "stored projection compensation proposal is invalid"
            ) from exc

    def record(
        self,
        proposal: FederatedProjectionCompensationProposal,
    ) -> FederatedProjectionCompensationProposal:
        if proposal.tenant_id != self.tenant_id:
            raise FederatedProjectionCompensationProposalForbiddenError(
                "projection compensation proposal tenant differs from the store"
            )
        proposal = self._proposal(proposal.model_dump(mode="json"))
        with self._transaction() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT proposal_document, created
                    FROM gda_control.record_cross_store_projection_compensation_proposal(
                        :tenant_id, :run_id, :source_snapshot_sha256,
                        :blocked_plan_sha256, :proposal_sha256,
                        :ontology_content_sha256,
                        CAST(:proposal_document AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": self.tenant_id,
                    "run_id": proposal.run_id,
                    "source_snapshot_sha256": proposal.source_snapshot_sha256,
                    "blocked_plan_sha256": proposal.blocked_plan_sha256,
                    "proposal_sha256": proposal.proposal_sha256,
                    "ontology_content_sha256": proposal.ontology.content_sha256,
                    "proposal_document": _json(proposal.model_dump(mode="json")),
                },
            ).mappings().one()
        stored = self._proposal(row["proposal_document"])
        if stored.proposal_sha256 != proposal.proposal_sha256:
            raise FederatedProjectionCompensationProposalConfigurationError(
                "proposal authority returned a different proposal"
            )
        return stored

    def current(
        self,
        run_id: str,
    ) -> FederatedProjectionCompensationProposal | None:
        with self._transaction() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT proposal_document
                    FROM gda_control.cross_store_projection_compensation_proposal_current
                    WHERE tenant_id = :tenant_id AND run_id = :run_id
                    """
                ),
                {"tenant_id": self.tenant_id, "run_id": run_id},
            ).mappings().one_or_none()
        return None if row is None else self._proposal(row["proposal_document"])

    def history(
        self,
        run_id: str,
    ) -> tuple[FederatedProjectionCompensationProposal, ...]:
        with self._transaction() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT proposal_document
                    FROM gda_control.cross_store_projection_compensation_proposal
                    WHERE tenant_id = :tenant_id AND run_id = :run_id
                    ORDER BY recorded_at, proposal_sha256
                    """
                ),
                {"tenant_id": self.tenant_id, "run_id": run_id},
            ).mappings().all()
        return tuple(self._proposal(row["proposal_document"]) for row in rows)

    def lookup(
        self,
        run_id: str,
    ) -> FederatedProjectionCompensationProposalReadResponse | None:
        """Read current and immutable history from one PostgreSQL statement."""

        try:
            query = FederatedProjectionCompensationProposalReadRequest(
                run_id=run_id
            )
        except ValidationError as exc:
            raise FederatedProjectionCompensationProposalValidationError(
                "projection compensation proposal run_id is invalid"
            ) from exc
        with self._transaction() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT current.proposal_document AS current_document,
                           history.history_documents
                    FROM gda_control.cross_store_projection_compensation_proposal_current
                         AS current
                    CROSS JOIN LATERAL (
                        SELECT COALESCE(
                            jsonb_agg(
                                stored.proposal_document
                                ORDER BY stored.recorded_at, stored.proposal_sha256
                            ),
                            '[]'::jsonb
                        ) AS history_documents
                        FROM gda_control.cross_store_projection_compensation_proposal
                             AS stored
                        WHERE stored.tenant_id = :tenant_id
                          AND stored.run_id = :run_id
                    ) AS history
                    WHERE current.tenant_id = :tenant_id
                      AND current.run_id = :run_id
                    """
                ),
                {"tenant_id": self.tenant_id, "run_id": query.run_id},
            ).mappings().one_or_none()
        if row is None:
            return None
        current = self._proposal(row["current_document"])
        documents = _json_value(row["history_documents"])
        if not isinstance(documents, list):
            raise FederatedProjectionCompensationProposalConfigurationError(
                "stored projection compensation proposal history is invalid"
            )
        history = tuple(self._proposal(document) for document in documents)
        try:
            return FederatedProjectionCompensationProposalReadResponse(
                tenant_id=self.tenant_id,
                run_id=query.run_id,
                current=current,
                history=history,
                history_count=len(history),
            )
        except ValidationError as exc:
            raise FederatedProjectionCompensationProposalConfigurationError(
                "stored projection compensation proposal lookup is inconsistent"
            ) from exc


__all__ = [
    "FEDERATED_PROJECTION_COMPENSATION_PROPOSAL_MIGRATION",
    "FederatedProjectionCompensationProposalAuthorityError",
    "FederatedProjectionCompensationProposalConfigurationError",
    "FederatedProjectionCompensationProposalForbiddenError",
    "FederatedProjectionCompensationProposalValidationError",
    "PostgresFederatedProjectionCompensationProposalStore",
]
