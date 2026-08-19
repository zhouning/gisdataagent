"""Controlled authority writer for sealed compensation checkpoint requests.

The writer rechecks every authority predecessor before the first side effect,
then records checkpoints through the existing authority port in deterministic
position order.  The authority remains responsible for PostgreSQL RLS,
advisory locks, compare-and-swap and idempotency.  A partial or uncertain
attempt is returned as reconciliation evidence and never marks compensation
complete.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cross_store_projection_authority import (
    PostgresProjectionCheckpointAuthority,
    ProjectionCheckpointAuthorityConfigurationError,
    ProjectionCheckpointAuthorityError,
    ProjectionCheckpointAuthorityForbiddenError,
    ProjectionCheckpointAuthorityValidationError,
)
from .cross_store_projection_compensation_checkpoint_write_request import (
    FederatedProjectionCompensationCheckpointWriteRequest,
    FederatedProjectionCompensationCheckpointWriteRequestSet,
)
from .cross_store_projection_consistency import (
    ProjectionCheckpoint,
    ProjectionCheckpointConflictError,
    ProjectionCheckpointWriteResult,
    ProjectionEngine,
)
from .platform_contracts import (
    NonEmptyText,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
)


class FederatedProjectionCompensationCheckpointWriterError(ValueError):
    """The sealed request set or its live authority predecessors are unsafe."""


class ProjectionCheckpointAuthorityWriter(Protocol):
    """Minimal authority port; production uses PostgreSQL authority."""

    def current(
        self,
        *,
        tenant_id: str,
        projection_id: str,
        target_engine: ProjectionEngine | str,
        target_ref: str,
    ) -> ProjectionCheckpoint | None: ...

    def record(
        self,
        checkpoint: ProjectionCheckpoint,
        *,
        previous_checkpoint_sha256: str | None = None,
    ) -> ProjectionCheckpointWriteResult: ...


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


_TYPED_SUBJECT_RE = re.compile(r"^(human|workload|agent):[^\s]{1,128}$")


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": payload})


RecordStatus = Literal[
    "created",
    "idempotent_replay",
    "conflict",
    "forbidden",
    "validation_rejected",
    "authority_outcome_unknown",
    "authority_response_mismatch",
]
RecordState = Literal["recorded", "not_recorded", "unknown"]
FailureCode = Literal[
    "checkpoint_conflict",
    "authority_forbidden",
    "authority_validation_rejected",
    "authority_outcome_unknown",
    "authority_response_mismatch",
]


class FederatedProjectionCompensationCheckpointAuthorityRecordItem(_FrozenModel):
    """One authority invocation result, including explicit uncertain outcomes."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-checkpoint-authority-record-item.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    position: int = Field(ge=0, le=31)
    write_request_sha256: Sha256
    checkpoint_sha256: Sha256
    previous_checkpoint_sha256: Sha256 | None
    checkpoint_version: int = Field(ge=1)
    record_status: RecordStatus
    record_state: RecordState
    created: bool | None
    failure_code: FailureCode | None
    authority_record_invoked: Literal[True] = True
    compensation_completion_allowed: Literal[False] = False
    item_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_item(
        self,
    ) -> FederatedProjectionCompensationCheckpointAuthorityRecordItem:
        expected_outcomes = {
            "created": ("recorded", True, None),
            "idempotent_replay": ("recorded", False, None),
            "conflict": ("not_recorded", None, "checkpoint_conflict"),
            "forbidden": ("not_recorded", None, "authority_forbidden"),
            "validation_rejected": (
                "not_recorded",
                None,
                "authority_validation_rejected",
            ),
            "authority_outcome_unknown": (
                "unknown",
                None,
                "authority_outcome_unknown",
            ),
            "authority_response_mismatch": (
                "unknown",
                None,
                "authority_response_mismatch",
            ),
        }
        if (self.record_state, self.created, self.failure_code) != expected_outcomes[
            self.record_status
        ]:
            raise ValueError("checkpoint authority record item outcome is inconsistent")
        if not self.authority_record_invoked or self.compensation_completion_allowed:
            raise ValueError("checkpoint authority record item cannot complete compensation")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"item_sha256"}),
            "item_sha256",
        )
        if self.item_sha256 != expected:
            raise ValueError("checkpoint authority record item fingerprint is invalid")
        return self


class FederatedProjectionCompensationCheckpointAuthorityRecordSet(_FrozenModel):
    """Complete or explicitly incomplete result of one ordered writer attempt."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-checkpoint-authority-record-set.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    write_request_set_sha256: Sha256
    writer_subject: NonEmptyText
    expected_positions: tuple[int, ...] = Field(min_length=1, max_length=32)
    records: tuple[FederatedProjectionCompensationCheckpointAuthorityRecordItem, ...] = Field(
        min_length=1, max_length=32
    )
    unattempted_positions: tuple[int, ...]
    record_state: Literal[
        "checkpoint_authority_records_complete_pending_compensation_completion",
        "checkpoint_authority_records_incomplete_pending_reconciliation",
    ]
    all_checkpoints_recorded: bool
    authority_record_performed: Literal[True] = True
    compensation_completion_allowed: Literal[False] = False
    compensation_completion_recorded: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    record_set_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_set(
        self,
    ) -> FederatedProjectionCompensationCheckpointAuthorityRecordSet:
        if self.expected_positions != tuple(sorted(set(self.expected_positions))):
            raise ValueError("checkpoint authority expected positions must be unique and ordered")
        record_positions = tuple(record.position for record in self.records)
        if record_positions != self.expected_positions[: len(record_positions)]:
            raise ValueError("checkpoint authority records must be an ordered attempt prefix")
        if self.unattempted_positions != self.expected_positions[len(record_positions) :]:
            raise ValueError("checkpoint authority unattempted positions are inconsistent")
        for record in self.records:
            if (
                record.tenant_id != self.tenant_id
                or record.run_id != self.run_id
                or not record.authority_record_invoked
                or record.compensation_completion_allowed
            ):
                raise ValueError("checkpoint authority record differs from its set")
        successful = all(record.record_state == "recorded" for record in self.records)
        complete = len(self.records) == len(self.expected_positions) and successful
        if complete:
            if (
                self.record_state
                != "checkpoint_authority_records_complete_pending_compensation_completion"
                or not self.all_checkpoints_recorded
                or self.unattempted_positions
            ):
                raise ValueError("complete checkpoint authority record set is inconsistent")
        elif (
            self.record_state != "checkpoint_authority_records_incomplete_pending_reconciliation"
            or self.all_checkpoints_recorded
            or self.records[-1].record_state == "recorded"
        ):
            raise ValueError("incomplete checkpoint authority record set is inconsistent")
        if _TYPED_SUBJECT_RE.fullmatch(self.writer_subject) is None:
            raise ValueError("checkpoint authority writer must use a typed subject")
        if (
            not self.authority_record_performed
            or self.compensation_completion_allowed
            or self.compensation_completion_recorded
        ):
            raise ValueError("checkpoint authority writer cannot complete compensation")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"record_set_sha256"}),
            "record_set_sha256",
        )
        if self.record_set_sha256 != expected:
            raise ValueError("checkpoint authority record set fingerprint is invalid")
        return self


def _record_item(
    request: FederatedProjectionCompensationCheckpointWriteRequest,
    *,
    status: RecordStatus,
) -> FederatedProjectionCompensationCheckpointAuthorityRecordItem:
    outcomes: dict[RecordStatus, tuple[RecordState, bool | None, FailureCode | None]] = {
        "created": ("recorded", True, None),
        "idempotent_replay": ("recorded", False, None),
        "conflict": ("not_recorded", None, "checkpoint_conflict"),
        "forbidden": ("not_recorded", None, "authority_forbidden"),
        "validation_rejected": (
            "not_recorded",
            None,
            "authority_validation_rejected",
        ),
        "authority_outcome_unknown": (
            "unknown",
            None,
            "authority_outcome_unknown",
        ),
        "authority_response_mismatch": (
            "unknown",
            None,
            "authority_response_mismatch",
        ),
    }
    record_state, created, failure_code = outcomes[status]
    values = {
        "tenant_id": request.tenant_id,
        "run_id": request.run_id,
        "position": request.position,
        "write_request_sha256": request.request_sha256,
        "checkpoint_sha256": request.checkpoint.checkpoint_sha256,
        "previous_checkpoint_sha256": request.previous_checkpoint_sha256,
        "checkpoint_version": request.checkpoint.checkpoint_version,
        "record_status": status,
        "record_state": record_state,
        "created": created,
        "failure_code": failure_code,
        "authority_record_invoked": True,
        "compensation_completion_allowed": False,
    }
    return FederatedProjectionCompensationCheckpointAuthorityRecordItem(
        **values,
        item_sha256=_fingerprint(
            FederatedProjectionCompensationCheckpointAuthorityRecordItem.schema_id,
            values,
            "item_sha256",
        ),
    )


def _record_set(
    request_set: FederatedProjectionCompensationCheckpointWriteRequestSet,
    records: list[FederatedProjectionCompensationCheckpointAuthorityRecordItem],
    *,
    writer_subject: str,
) -> FederatedProjectionCompensationCheckpointAuthorityRecordSet:
    expected_positions = tuple(request.position for request in request_set.requests)
    complete = len(records) == len(expected_positions) and all(
        record.record_state == "recorded" for record in records
    )
    values = {
        "tenant_id": request_set.tenant_id,
        "run_id": request_set.run_id,
        "write_request_set_sha256": request_set.request_set_sha256,
        "writer_subject": writer_subject,
        "expected_positions": expected_positions,
        "records": tuple(records),
        "unattempted_positions": expected_positions[len(records) :],
        "record_state": (
            "checkpoint_authority_records_complete_pending_compensation_completion"
            if complete
            else "checkpoint_authority_records_incomplete_pending_reconciliation"
        ),
        "all_checkpoints_recorded": complete,
        "authority_record_performed": True,
        "compensation_completion_allowed": False,
        "compensation_completion_recorded": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    normalized = FederatedProjectionCompensationCheckpointAuthorityRecordSet.model_construct(
        **values,
        record_set_sha256="0" * 64,
    ).model_dump(mode="json", exclude={"record_set_sha256"})
    return FederatedProjectionCompensationCheckpointAuthorityRecordSet(
        **values,
        record_set_sha256=_fingerprint(
            FederatedProjectionCompensationCheckpointAuthorityRecordSet.schema_id,
            normalized,
            "record_set_sha256",
        ),
    )


def _preflight_current(
    request: FederatedProjectionCompensationCheckpointWriteRequest,
    current: ProjectionCheckpoint | None,
) -> None:
    if current is None:
        if request.previous_checkpoint_sha256 is not None:
            raise FederatedProjectionCompensationCheckpointWriterError(
                "authority preflight is missing the requested predecessor"
            )
        return
    if current == request.checkpoint:
        return
    if (
        current.checkpoint_sha256 != request.previous_checkpoint_sha256
        or current.checkpoint_version != request.previous_checkpoint_version
        or current.tenant_id != request.tenant_id
        or current.projection_id != request.checkpoint.projection_id
        or current.target_engine is not request.checkpoint.target_engine
        or current.target_ref != request.checkpoint.target_ref
    ):
        raise FederatedProjectionCompensationCheckpointWriterError(
            "authority preflight predecessor differs from sealed write request"
        )


def record_federated_compensation_checkpoint_write_request_set(
    request_set: FederatedProjectionCompensationCheckpointWriteRequestSet,
    authority: ProjectionCheckpointAuthorityWriter | PostgresProjectionCheckpointAuthority,
    *,
    writer_subject: str,
) -> FederatedProjectionCompensationCheckpointAuthorityRecordSet:
    """Record an ordered request set, stopping on the first unsafe outcome."""

    try:
        request_set = FederatedProjectionCompensationCheckpointWriteRequestSet.model_validate(
            request_set.model_dump(mode="python")
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedProjectionCompensationCheckpointWriterError(
            "checkpoint writer input violates its sealed contract"
        ) from exc
    if (
        not isinstance(writer_subject, str)
        or writer_subject != request_set.updated_by
        or _TYPED_SUBJECT_RE.fullmatch(writer_subject) is None
    ):
        raise FederatedProjectionCompensationCheckpointWriterError(
            "checkpoint writer subject differs from sealed request updater"
        )

    for request in request_set.requests:
        try:
            current = authority.current(
                tenant_id=request.tenant_id,
                projection_id=request.checkpoint.projection_id,
                target_engine=request.checkpoint.target_engine,
                target_ref=request.checkpoint.target_ref,
            )
        except ProjectionCheckpointAuthorityError as exc:
            raise FederatedProjectionCompensationCheckpointWriterError(
                "authority preflight current read failed before any write"
            ) from exc
        except (AttributeError, TypeError, ValueError) as exc:
            raise FederatedProjectionCompensationCheckpointWriterError(
                "authority preflight returned an invalid checkpoint"
            ) from exc
        if current is not None and not isinstance(current, ProjectionCheckpoint):
            raise FederatedProjectionCompensationCheckpointWriterError(
                "authority preflight returned an invalid checkpoint"
            )
        _preflight_current(request, current)

    records: list[FederatedProjectionCompensationCheckpointAuthorityRecordItem] = []
    for request in request_set.requests:
        try:
            result = authority.record(
                request.checkpoint,
                previous_checkpoint_sha256=request.previous_checkpoint_sha256,
            )
        except ProjectionCheckpointConflictError:
            records.append(_record_item(request, status="conflict"))
            return _record_set(request_set, records, writer_subject=writer_subject)
        except ProjectionCheckpointAuthorityForbiddenError:
            records.append(_record_item(request, status="forbidden"))
            return _record_set(request_set, records, writer_subject=writer_subject)
        except ProjectionCheckpointAuthorityValidationError:
            records.append(_record_item(request, status="validation_rejected"))
            return _record_set(request_set, records, writer_subject=writer_subject)
        except (
            ProjectionCheckpointAuthorityConfigurationError,
            ProjectionCheckpointAuthorityError,
        ):
            records.append(_record_item(request, status="authority_outcome_unknown"))
            return _record_set(request_set, records, writer_subject=writer_subject)
        except (AttributeError, TypeError, ValueError):
            records.append(_record_item(request, status="authority_response_mismatch"))
            return _record_set(request_set, records, writer_subject=writer_subject)
        if (
            not isinstance(result, ProjectionCheckpointWriteResult)
            or not isinstance(result.created, bool)
            or result.checkpoint != request.checkpoint
        ):
            records.append(_record_item(request, status="authority_response_mismatch"))
            return _record_set(request_set, records, writer_subject=writer_subject)
        records.append(
            _record_item(
                request,
                status="created" if result.created else "idempotent_replay",
            )
        )
    return _record_set(request_set, records, writer_subject=writer_subject)


__all__ = [
    "FederatedProjectionCompensationCheckpointWriterError",
    "ProjectionCheckpointAuthorityWriter",
    "FederatedProjectionCompensationCheckpointAuthorityRecordItem",
    "FederatedProjectionCompensationCheckpointAuthorityRecordSet",
    "record_federated_compensation_checkpoint_write_request_set",
]
