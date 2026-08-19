"""PostgreSQL authority for the Chongqing unknown-resume attempt budget."""

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
from .cross_store_projection_compensation_chongqing_federated_recovery_attempt import (
    ChongqingFederatedCompensationUnknownResumeAttemptReceipt,
    ChongqingFederatedCompensationUnknownResumeAttemptRequest,
    build_chongqing_federated_compensation_unknown_resume_attempt_receipt,
)
from .db_engine import get_engine
from .temporal_entity_authority import GATEWAY_DATABASE_ROLE

CHONGQING_FIVE_PROVIDER_UNKNOWN_RESUME_ATTEMPT_AUTHORITY_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "188_chongqing_five_provider_unknown_resume_attempt_authority.sql"
)


class ChongqingFiveProviderUnknownResumeAttemptAuthorityError(RuntimeError):
    """Base error for the durable unknown-resume attempt authority."""


class ChongqingFiveProviderUnknownResumeAttemptAuthorityConfigurationError(
    ChongqingFiveProviderUnknownResumeAttemptAuthorityError
):
    """PostgreSQL cannot enforce or read the attempt authority."""


class ChongqingFiveProviderUnknownResumeAttemptAuthorityForbiddenError(
    ChongqingFiveProviderUnknownResumeAttemptAuthorityError
):
    """The current role or tenant context was denied."""


class ChongqingFiveProviderUnknownResumeAttemptAuthorityConflictError(
    ChongqingFiveProviderUnknownResumeAttemptAuthorityError
):
    """The expected zero-attempt predecessor is stale or already consumed."""


class ChongqingFiveProviderUnknownResumeAttemptAuthorityValidationError(
    ChongqingFiveProviderUnknownResumeAttemptAuthorityError
):
    """An attempt request, receipt, or authority query is invalid."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _postgres_message(exc: DBAPIError, fallback: str) -> str:
    diagnostic = getattr(getattr(exc, "orig", None), "diag", None)
    detail = getattr(diagnostic, "message_primary", None)
    if isinstance(detail, str) and detail.strip():
        return f"{fallback}: {detail.strip()}"
    return fallback


class PostgresChongqingFiveProviderUnknownResumeAttemptAuthority:
    """Tenant-bound append-only repository for one pre-callback attempt."""

    def __init__(self, tenant_id: str, engine: Any = None):
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ChongqingFiveProviderUnknownResumeAttemptAuthorityValidationError(
                "unknown-resume attempt tenant_id is required"
            )
        self.tenant_id = tenant_id.strip()
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise ChongqingFiveProviderUnknownResumeAttemptAuthorityConfigurationError(
                "unknown-resume attempt authority requires PostgreSQL"
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
                            ChongqingFiveProviderUnknownResumeAttemptAuthorityConfigurationError(
                                "database login is not a member of the platform gateway role"
                            )
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": self.tenant_id},
                    )
                    yield connection
        except ChongqingFiveProviderUnknownResumeAttemptAuthorityError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state == "42501":
                raise ChongqingFiveProviderUnknownResumeAttemptAuthorityForbiddenError(
                    "unknown-resume attempt tenant or role was denied"
                ) from exc
            if state == "40001":
                raise ChongqingFiveProviderUnknownResumeAttemptAuthorityConflictError(
                    _postgres_message(
                        exc,
                        "unknown-resume attempt budget was already consumed",
                    )
                ) from exc
            if state in {
                "22007",
                "22023",
                "22P02",
                "23502",
                "23505",
                "23514",
                "55000",
            }:
                raise ChongqingFiveProviderUnknownResumeAttemptAuthorityValidationError(
                    _postgres_message(exc, "unknown-resume attempt was rejected")
                ) from exc
            raise ChongqingFiveProviderUnknownResumeAttemptAuthorityConfigurationError(
                "unknown-resume attempt authority operation failed"
            ) from exc
        except SQLAlchemyError as exc:
            raise ChongqingFiveProviderUnknownResumeAttemptAuthorityConfigurationError(
                "unknown-resume attempt authority operation failed"
            ) from exc

    @staticmethod
    def _receipt(document: Any) -> ChongqingFederatedCompensationUnknownResumeAttemptReceipt:
        try:
            return ChongqingFederatedCompensationUnknownResumeAttemptReceipt.model_validate(
                _json_value(document)
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise ChongqingFiveProviderUnknownResumeAttemptAuthorityConfigurationError(
                "stored unknown-resume attempt receipt is invalid"
            ) from exc

    @staticmethod
    def _identity(
        run_id: str,
        request_bundle_sha256: str,
        position: int,
    ) -> tuple[str, str, int]:
        if not isinstance(run_id, str) or not run_id.strip() or len(run_id.strip()) > 512:
            raise ChongqingFiveProviderUnknownResumeAttemptAuthorityValidationError(
                "unknown-resume attempt run_id is invalid"
            )
        if (
            not isinstance(request_bundle_sha256, str)
            or len(request_bundle_sha256) != 64
            or any(character not in "0123456789abcdef" for character in request_bundle_sha256)
        ):
            raise ChongqingFiveProviderUnknownResumeAttemptAuthorityValidationError(
                "unknown-resume attempt request bundle fingerprint is invalid"
            )
        if not isinstance(position, int) or isinstance(position, bool) or not 0 <= position <= 31:
            raise ChongqingFiveProviderUnknownResumeAttemptAuthorityValidationError(
                "unknown-resume attempt position is invalid"
            )
        return run_id.strip(), request_bundle_sha256, position

    def consume(
        self,
        request: ChongqingFederatedCompensationUnknownResumeAttemptRequest,
    ) -> ChongqingFederatedCompensationUnknownResumeAttemptReceipt:
        """Atomically consume expected count zero before any Provider callback."""

        try:
            request = ChongqingFederatedCompensationUnknownResumeAttemptRequest.model_validate(
                request.model_dump(mode="python")
            )
        except (AttributeError, TypeError, ValueError, ValidationError) as exc:
            raise ChongqingFiveProviderUnknownResumeAttemptAuthorityValidationError(
                "unknown-resume attempt request is invalid"
            ) from exc
        if request.tenant_id != self.tenant_id:
            raise ChongqingFiveProviderUnknownResumeAttemptAuthorityForbiddenError(
                "unknown-resume attempt request tenant differs from the authority"
            )
        receipt = build_chongqing_federated_compensation_unknown_resume_attempt_receipt(
            request
        )
        with self._transaction() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT receipt_document
                    FROM gda_control.
                         consume_chongqing_five_provider_unknown_resume_attempt(
                        :tenant_id, :run_id, :request_bundle_sha256, :position,
                        :attempt_id, :prior_execution_result_sha256,
                        :reconciliation_case_sha256, :action_map_sha256,
                        :action_execution_binding_sha256, :target_engine,
                        :request_sha256, :unknown_outcome_sha256,
                        :observation_sha256, :expected_consumed_attempts,
                        :attempt_limit, :consumed_by, :requested_at,
                        :request_fingerprint_sha256, :receipt_sha256,
                        CAST(:request_document AS jsonb),
                        CAST(:receipt_document AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": request.tenant_id,
                    "run_id": request.run_id,
                    "request_bundle_sha256": request.request_bundle_sha256,
                    "position": request.position,
                    "attempt_id": request.attempt_id,
                    "prior_execution_result_sha256": (
                        request.prior_execution_result_sha256
                    ),
                    "reconciliation_case_sha256": request.reconciliation_case_sha256,
                    "action_map_sha256": request.action_map_sha256,
                    "action_execution_binding_sha256": (
                        request.action_execution_binding_sha256
                    ),
                    "target_engine": request.target_engine.value,
                    "request_sha256": request.request_sha256,
                    "unknown_outcome_sha256": request.unknown_outcome_sha256,
                    "observation_sha256": request.observation_sha256,
                    "expected_consumed_attempts": request.expected_consumed_attempts,
                    "attempt_limit": request.attempt_limit,
                    "consumed_by": request.consumed_by,
                    "requested_at": request.requested_at,
                    "request_fingerprint_sha256": request.request_fingerprint_sha256,
                    "receipt_sha256": receipt.receipt_sha256,
                    "request_document": _json(request.model_dump(mode="json")),
                    "receipt_document": _json(receipt.model_dump(mode="json")),
                },
            ).mappings().one()
        stored = self._receipt(row["receipt_document"])
        if stored != receipt or stored.request != request:
            raise ChongqingFiveProviderUnknownResumeAttemptAuthorityConfigurationError(
                "unknown-resume attempt authority returned different evidence"
            )
        return stored

    def current(
        self,
        *,
        run_id: str,
        request_bundle_sha256: str,
        position: int,
    ) -> ChongqingFederatedCompensationUnknownResumeAttemptReceipt | None:
        """Read the consumed attempt for one exact run/bundle/position identity."""

        run_id, request_bundle_sha256, position = self._identity(
            run_id, request_bundle_sha256, position
        )
        with self._transaction() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT receipt_document
                    FROM gda_control.
                         chongqing_five_provider_unknown_resume_attempt_current
                    WHERE tenant_id = :tenant_id
                      AND run_id = :run_id
                      AND request_bundle_sha256 = :request_bundle_sha256
                      AND position = :position
                    """
                ),
                {
                    "tenant_id": self.tenant_id,
                    "run_id": run_id,
                    "request_bundle_sha256": request_bundle_sha256,
                    "position": position,
                },
            ).mappings().one_or_none()
        return None if row is None else self._receipt(row["receipt_document"])


__all__ = [
    "CHONGQING_FIVE_PROVIDER_UNKNOWN_RESUME_ATTEMPT_AUTHORITY_MIGRATION",
    "ChongqingFiveProviderUnknownResumeAttemptAuthorityConfigurationError",
    "ChongqingFiveProviderUnknownResumeAttemptAuthorityConflictError",
    "ChongqingFiveProviderUnknownResumeAttemptAuthorityError",
    "ChongqingFiveProviderUnknownResumeAttemptAuthorityForbiddenError",
    "ChongqingFiveProviderUnknownResumeAttemptAuthorityValidationError",
    "PostgresChongqingFiveProviderUnknownResumeAttemptAuthority",
]
