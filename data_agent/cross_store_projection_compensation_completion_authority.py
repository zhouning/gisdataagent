"""Admission and append-only authority for checkpoint compensation completion."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar, Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .cross_store_projection_authority import (
    PostgresProjectionCheckpointAuthority,
    ProjectionCheckpointAuthorityError,
    _sqlstate,
)
from .cross_store_projection_compensation_checkpoint_write_request import (
    FederatedProjectionCompensationCheckpointWriteRequestSet,
)
from .cross_store_projection_compensation_checkpoint_writer import (
    FederatedProjectionCompensationCheckpointAuthorityRecordSet,
)
from .cross_store_projection_consistency import ProjectionCheckpoint, ProjectionEngine
from .db_engine import get_engine
from .platform_contracts import (
    NonEmptyText,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
)
from .temporal_entity_authority import GATEWAY_DATABASE_ROLE

FEDERATED_PROJECTION_COMPENSATION_COMPLETION_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "181_federated_projection_compensation_checkpoint_completion.sql"
)

_TYPED_SUBJECT_RE = re.compile(r"^(human|workload|agent):[^\s]{1,128}$")


class FederatedProjectionCompensationCompletionAdmissionError(ValueError):
    """The record set or live checkpoint authority cannot admit completion."""


class FederatedProjectionCompensationCompletionAuthorityError(RuntimeError):
    """Base error for durable compensation completion authority operations."""


class FederatedProjectionCompensationCompletionAuthorityConfigurationError(
    FederatedProjectionCompensationCompletionAuthorityError
):
    """PostgreSQL or returned completion evidence is not trustworthy."""


class FederatedProjectionCompensationCompletionAuthorityForbiddenError(
    FederatedProjectionCompensationCompletionAuthorityError
):
    """The database role or tenant boundary denied completion."""


class FederatedProjectionCompensationCompletionAuthorityValidationError(
    FederatedProjectionCompensationCompletionAuthorityError
):
    """Completion evidence drifted or conflicts with the append-only record."""


class ProjectionCheckpointCurrentReader(Protocol):
    def current(
        self,
        *,
        tenant_id: str,
        projection_id: str,
        target_engine: ProjectionEngine | str,
        target_ref: str,
    ) -> ProjectionCheckpoint | None: ...


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": payload})


class FederatedProjectionCompensationCompletionTarget(_FrozenModel):
    """One live checkpoint admitted into a complete compensation set."""

    schema_id: ClassVar[str] = "gda.federated-projection-compensation-completion-target.v1"
    tenant_id: TenantId
    run_id: NonEmptyText
    position: int = Field(ge=0, le=31)
    write_request_sha256: Sha256
    authority_record_item_sha256: Sha256
    projection_id: NonEmptyText
    target_engine: ProjectionEngine
    target_ref: NonEmptyText
    checkpoint_sha256: Sha256
    checkpoint_version: int = Field(ge=1)
    target_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_target(self) -> FederatedProjectionCompensationCompletionTarget:
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"target_sha256"}),
            "target_sha256",
        )
        if self.target_sha256 != expected:
            raise ValueError("compensation completion target fingerprint is invalid")
        return self


def _completion_idempotency_key(
    *,
    tenant_id: str,
    run_id: str,
    write_request_set_sha256: str,
    authority_record_set_sha256: str,
    targets: tuple[FederatedProjectionCompensationCompletionTarget, ...],
) -> str:
    return canonical_json_fingerprint(
        {
            "schema": "gda.federated-projection-compensation-completion-idempotency.v1",
            "tenant_id": tenant_id,
            "run_id": run_id,
            "write_request_set_sha256": write_request_set_sha256,
            "authority_record_set_sha256": authority_record_set_sha256,
            "target_sha256s": [target.target_sha256 for target in targets],
        }
    )


class FederatedProjectionCompensationCompletionRequest(_FrozenModel):
    """Complete live-current evidence admitted for one append-only record."""

    schema_id: ClassVar[str] = "gda.federated-projection-compensation-completion-request.v1"
    tenant_id: TenantId
    run_id: NonEmptyText
    write_request_set_sha256: Sha256
    authority_record_set_sha256: Sha256
    targets: tuple[FederatedProjectionCompensationCompletionTarget, ...] = Field(
        min_length=1, max_length=32
    )
    completed_by: NonEmptyText
    all_authority_currents_verified: Literal[True] = True
    completion_record_allowed: Literal[True] = True
    completion_recorded: Literal[False] = False
    provider_execution_performed_by_completion_authority: Literal[False] = False
    completion_idempotency_key: Sha256
    request_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_request(self) -> FederatedProjectionCompensationCompletionRequest:
        positions = tuple(target.position for target in self.targets)
        if positions != tuple(sorted(set(positions))):
            raise ValueError("compensation completion target positions must be unique and ordered")
        identities: set[tuple[str, str, str]] = set()
        for target in self.targets:
            identity = (
                target.projection_id,
                target.target_engine.value,
                target.target_ref,
            )
            if target.tenant_id != self.tenant_id or target.run_id != self.run_id:
                raise ValueError("compensation completion target differs from request")
            if identity in identities:
                raise ValueError("compensation completion target identities must be unique")
            identities.add(identity)
        if _TYPED_SUBJECT_RE.fullmatch(self.completed_by) is None:
            raise ValueError("compensation completion actor must use a typed subject")
        if (
            not self.all_authority_currents_verified
            or not self.completion_record_allowed
            or self.completion_recorded
            or self.provider_execution_performed_by_completion_authority
        ):
            raise ValueError("compensation completion request state is invalid")
        expected_key = _completion_idempotency_key(
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            write_request_set_sha256=self.write_request_set_sha256,
            authority_record_set_sha256=self.authority_record_set_sha256,
            targets=self.targets,
        )
        if self.completion_idempotency_key != expected_key:
            raise ValueError("compensation completion idempotency key is invalid")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"request_sha256"}),
            "request_sha256",
        )
        if self.request_sha256 != expected:
            raise ValueError("compensation completion request fingerprint is invalid")
        return self


class FederatedProjectionCompensationCompletionReceipt(_FrozenModel):
    """Durable technical completion evidence, not Provider invocation evidence."""

    schema_id: ClassVar[str] = "gda.federated-projection-compensation-completion-receipt.v1"
    tenant_id: TenantId
    run_id: NonEmptyText
    write_request_set_sha256: Sha256
    authority_record_set_sha256: Sha256
    targets: tuple[FederatedProjectionCompensationCompletionTarget, ...] = Field(
        min_length=1, max_length=32
    )
    completion_idempotency_key: Sha256
    completion_request_sha256: Sha256
    completed_by: NonEmptyText
    completed_at: datetime
    completion_state: Literal["checkpoint_compensation_completion_recorded"] = (
        "checkpoint_compensation_completion_recorded"
    )
    all_authority_currents_verified: Literal[True] = True
    checkpoint_compensation_completion_recorded: Literal[True] = True
    provider_execution_performed_by_completion_authority: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )

    @field_validator("completed_at")
    @classmethod
    def _aware_completed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("compensation completion timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _sealed_receipt(self) -> FederatedProjectionCompensationCompletionReceipt:
        request_values = {
            "tenant_id": self.tenant_id,
            "run_id": self.run_id,
            "write_request_set_sha256": self.write_request_set_sha256,
            "authority_record_set_sha256": self.authority_record_set_sha256,
            "targets": self.targets,
            "completed_by": self.completed_by,
            "all_authority_currents_verified": True,
            "completion_record_allowed": True,
            "completion_recorded": False,
            "provider_execution_performed_by_completion_authority": False,
            "completion_idempotency_key": self.completion_idempotency_key,
        }
        request = FederatedProjectionCompensationCompletionRequest(
            **request_values,
            request_sha256=_fingerprint(
                FederatedProjectionCompensationCompletionRequest.schema_id,
                FederatedProjectionCompensationCompletionRequest.model_construct(
                    **request_values,
                    request_sha256="0" * 64,
                ).model_dump(mode="json", exclude={"request_sha256"}),
                "request_sha256",
            ),
        )
        if request.request_sha256 != self.completion_request_sha256:
            raise ValueError("compensation completion receipt differs from request")
        if (
            not self.all_authority_currents_verified
            or not self.checkpoint_compensation_completion_recorded
            or self.provider_execution_performed_by_completion_authority
        ):
            raise ValueError("compensation completion receipt state is invalid")
        return self


class FederatedProjectionCompensationCompletionWriteResult(_FrozenModel):
    receipt: FederatedProjectionCompensationCompletionReceipt
    created: bool


def build_federated_projection_compensation_completion_request(
    write_request_set: FederatedProjectionCompensationCheckpointWriteRequestSet,
    authority_record_set: FederatedProjectionCompensationCheckpointAuthorityRecordSet,
    checkpoint_authority: ProjectionCheckpointCurrentReader | PostgresProjectionCheckpointAuthority,
    *,
    completed_by: str,
) -> FederatedProjectionCompensationCompletionRequest:
    """Re-read every current checkpoint before admitting completion."""

    try:
        write_request_set = FederatedProjectionCompensationCheckpointWriteRequestSet.model_validate(
            write_request_set.model_dump(mode="python")
        )
        authority_record_set = (
            FederatedProjectionCompensationCheckpointAuthorityRecordSet.model_validate(
                authority_record_set.model_dump(mode="python")
            )
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationCompletionAdmissionError(
            "compensation completion input violates a sealed contract"
        ) from exc
    if (
        authority_record_set.tenant_id != write_request_set.tenant_id
        or authority_record_set.run_id != write_request_set.run_id
        or authority_record_set.write_request_set_sha256 != write_request_set.request_set_sha256
        or not authority_record_set.all_checkpoints_recorded
        or authority_record_set.record_state
        != "checkpoint_authority_records_complete_pending_compensation_completion"
        or authority_record_set.unattempted_positions
    ):
        raise FederatedProjectionCompensationCompletionAdmissionError(
            "only a complete checkpoint authority record set can admit completion"
        )
    request_by_position = {request.position: request for request in write_request_set.requests}
    record_by_position = {record.position: record for record in authority_record_set.records}
    if set(request_by_position) != set(record_by_position):
        raise FederatedProjectionCompensationCompletionAdmissionError(
            "completion record set does not cover every write request"
        )

    targets: list[FederatedProjectionCompensationCompletionTarget] = []
    for position in sorted(request_by_position):
        write_request = request_by_position[position]
        record = record_by_position[position]
        if (
            record.write_request_sha256 != write_request.request_sha256
            or record.checkpoint_sha256 != write_request.checkpoint.checkpoint_sha256
            or record.previous_checkpoint_sha256 != write_request.previous_checkpoint_sha256
            or record.checkpoint_version != write_request.checkpoint.checkpoint_version
            or record.record_state != "recorded"
            or record.record_status not in {"created", "idempotent_replay"}
        ):
            raise FederatedProjectionCompensationCompletionAdmissionError(
                "completion authority record differs from its write request"
            )
        checkpoint = write_request.checkpoint
        try:
            current = checkpoint_authority.current(
                tenant_id=write_request.tenant_id,
                projection_id=checkpoint.projection_id,
                target_engine=checkpoint.target_engine,
                target_ref=checkpoint.target_ref,
            )
        except ProjectionCheckpointAuthorityError as exc:
            raise FederatedProjectionCompensationCompletionAdmissionError(
                "checkpoint authority current read failed during completion admission"
            ) from exc
        except (AttributeError, TypeError, ValueError) as exc:
            raise FederatedProjectionCompensationCompletionAdmissionError(
                "checkpoint authority returned invalid completion evidence"
            ) from exc
        if current != checkpoint:
            raise FederatedProjectionCompensationCompletionAdmissionError(
                "checkpoint authority current drifted before completion admission"
            )
        values = {
            "tenant_id": write_request_set.tenant_id,
            "run_id": write_request_set.run_id,
            "position": position,
            "write_request_sha256": write_request.request_sha256,
            "authority_record_item_sha256": record.item_sha256,
            "projection_id": checkpoint.projection_id,
            "target_engine": checkpoint.target_engine,
            "target_ref": checkpoint.target_ref,
            "checkpoint_sha256": checkpoint.checkpoint_sha256,
            "checkpoint_version": checkpoint.checkpoint_version,
        }
        targets.append(
            FederatedProjectionCompensationCompletionTarget(
                **values,
                target_sha256=_fingerprint(
                    FederatedProjectionCompensationCompletionTarget.schema_id,
                    values,
                    "target_sha256",
                ),
            )
        )

    target_tuple = tuple(targets)
    values = {
        "tenant_id": write_request_set.tenant_id,
        "run_id": write_request_set.run_id,
        "write_request_set_sha256": write_request_set.request_set_sha256,
        "authority_record_set_sha256": authority_record_set.record_set_sha256,
        "targets": target_tuple,
        "completed_by": completed_by,
        "all_authority_currents_verified": True,
        "completion_record_allowed": True,
        "completion_recorded": False,
        "provider_execution_performed_by_completion_authority": False,
        "completion_idempotency_key": _completion_idempotency_key(
            tenant_id=write_request_set.tenant_id,
            run_id=write_request_set.run_id,
            write_request_set_sha256=write_request_set.request_set_sha256,
            authority_record_set_sha256=authority_record_set.record_set_sha256,
            targets=target_tuple,
        ),
    }
    normalized = FederatedProjectionCompensationCompletionRequest.model_construct(
        **values,
        request_sha256="0" * 64,
    ).model_dump(mode="json", exclude={"request_sha256"})
    try:
        return FederatedProjectionCompensationCompletionRequest(
            **values,
            request_sha256=_fingerprint(
                FederatedProjectionCompensationCompletionRequest.schema_id,
                normalized,
                "request_sha256",
            ),
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationCompletionAdmissionError(
            "compensation completion request is invalid"
        ) from exc


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


class PostgresFederatedProjectionCompensationCompletionAuthority:
    """Tenant-bound completion authority with one SECURITY DEFINER write path."""

    def __init__(self, tenant_id: str, engine: Any = None):
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise FederatedProjectionCompensationCompletionAuthorityValidationError(
                "compensation completion authority tenant_id is required"
            )
        self.tenant_id = tenant_id.strip()
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise FederatedProjectionCompensationCompletionAuthorityConfigurationError(
                "compensation completion authority requires PostgreSQL"
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
                        raise FederatedProjectionCompensationCompletionAuthorityConfigurationError(
                            "database login is not a member of the platform gateway role"
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": self.tenant_id},
                    )
                    yield connection
        except FederatedProjectionCompensationCompletionAuthorityError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state in {"23505", "40001", "55000"}:
                raise FederatedProjectionCompensationCompletionAuthorityValidationError(
                    "compensation completion current or idempotency evidence differs"
                ) from exc
            if state == "42501":
                raise FederatedProjectionCompensationCompletionAuthorityForbiddenError(
                    "compensation completion tenant or database role was denied"
                ) from exc
            if state in {"22023", "22P02", "23502", "23514"}:
                raise FederatedProjectionCompensationCompletionAuthorityValidationError(
                    "compensation completion evidence was rejected"
                ) from exc
            raise FederatedProjectionCompensationCompletionAuthorityConfigurationError(
                "compensation completion authority operation failed"
            ) from exc
        except SQLAlchemyError as exc:
            raise FederatedProjectionCompensationCompletionAuthorityConfigurationError(
                "compensation completion authority operation failed"
            ) from exc

    @staticmethod
    def _receipt(document: Any) -> FederatedProjectionCompensationCompletionReceipt:
        if isinstance(document, str):
            document = json.loads(document)
        if not isinstance(document, dict):
            raise FederatedProjectionCompensationCompletionAuthorityConfigurationError(
                "stored compensation completion record is invalid"
            )
        values = dict(document)
        values["targets"] = values.pop("checkpoint_targets", values.get("targets"))
        values.update(
            {
                "completion_state": "checkpoint_compensation_completion_recorded",
                "all_authority_currents_verified": True,
                "checkpoint_compensation_completion_recorded": True,
                "provider_execution_performed_by_completion_authority": False,
                "review_state": "technical_baseline_unreviewed",
                "intended_use": "assisted_precheck_not_for_production_decision",
            }
        )
        try:
            return FederatedProjectionCompensationCompletionReceipt.model_validate(values)
        except (TypeError, ValueError, ValidationError) as exc:
            raise FederatedProjectionCompensationCompletionAuthorityConfigurationError(
                "stored compensation completion record is invalid"
            ) from exc

    def record(
        self,
        request: FederatedProjectionCompensationCompletionRequest,
    ) -> FederatedProjectionCompensationCompletionWriteResult:
        try:
            request = FederatedProjectionCompensationCompletionRequest.model_validate(
                request.model_dump(mode="python")
            )
        except (AttributeError, TypeError, ValueError, ValidationError) as exc:
            raise FederatedProjectionCompensationCompletionAuthorityValidationError(
                "compensation completion request is invalid"
            ) from exc
        if request.tenant_id != self.tenant_id:
            raise FederatedProjectionCompensationCompletionAuthorityForbiddenError(
                "compensation completion request tenant differs from authority"
            )
        with self._transaction() as connection:
            row = (
                connection.execute(
                    text(
                        """
                    SELECT completion_document, created
                    FROM gda_control.
                         record_federated_projection_compensation_checkpoint_completion(
                            :tenant_id, :run_id, :write_request_set_sha256,
                            :authority_record_set_sha256,
                            CAST(:checkpoint_targets AS jsonb),
                            :completion_idempotency_key,
                            :completion_request_sha256, :completed_by
                         )
                    """
                    ),
                    {
                        "tenant_id": request.tenant_id,
                        "run_id": request.run_id,
                        "write_request_set_sha256": request.write_request_set_sha256,
                        "authority_record_set_sha256": request.authority_record_set_sha256,
                        "checkpoint_targets": _json(
                            [target.model_dump(mode="json") for target in request.targets]
                        ),
                        "completion_idempotency_key": request.completion_idempotency_key,
                        "completion_request_sha256": request.request_sha256,
                        "completed_by": request.completed_by,
                    },
                )
                .mappings()
                .one()
            )
        receipt = self._receipt(row["completion_document"])
        if receipt.completion_request_sha256 != request.request_sha256:
            raise FederatedProjectionCompensationCompletionAuthorityConfigurationError(
                "completion authority returned a different request"
            )
        if type(row["created"]) is not bool:
            raise FederatedProjectionCompensationCompletionAuthorityConfigurationError(
                "completion authority returned an invalid creation status"
            )
        return FederatedProjectionCompensationCompletionWriteResult(
            receipt=receipt,
            created=row["created"],
        )

    def current(
        self,
        run_id: str,
    ) -> FederatedProjectionCompensationCompletionReceipt | None:
        run = str(run_id or "").strip()
        if not run or len(run.encode("utf-8")) > 512:
            raise FederatedProjectionCompensationCompletionAuthorityValidationError(
                "compensation completion run_id is invalid"
            )
        with self._transaction() as connection:
            row = (
                connection.execute(
                    text(
                        """
                    SELECT to_jsonb(completion) AS completion_document
                    FROM gda_control.
                         federated_projection_compensation_checkpoint_completion
                         AS completion
                    WHERE tenant_id = :tenant_id AND run_id = :run_id
                    """
                    ),
                    {"tenant_id": self.tenant_id, "run_id": run},
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else self._receipt(row["completion_document"])


__all__ = [
    "FEDERATED_PROJECTION_COMPENSATION_COMPLETION_MIGRATION",
    "FederatedProjectionCompensationCompletionAdmissionError",
    "FederatedProjectionCompensationCompletionAuthorityConfigurationError",
    "FederatedProjectionCompensationCompletionAuthorityError",
    "FederatedProjectionCompensationCompletionAuthorityForbiddenError",
    "FederatedProjectionCompensationCompletionAuthorityValidationError",
    "FederatedProjectionCompensationCompletionReceipt",
    "FederatedProjectionCompensationCompletionRequest",
    "FederatedProjectionCompensationCompletionTarget",
    "FederatedProjectionCompensationCompletionWriteResult",
    "PostgresFederatedProjectionCompensationCompletionAuthority",
    "build_federated_projection_compensation_completion_request",
]
