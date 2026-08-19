"""External contract for governed Chongqing package reconciliation.

Callers provide the two sealed technical baselines and execution controls. The
service deliberately resolves current entity, source, and Link authority state
inside the high-level reconciler; authority snapshots are not client input.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from .chongqing_data_package_reconciliation import (
    ChongqingDataPackageReconciliationPlan,
    ChongqingDataPackageReconciliationReceipt,
    ReconciliationCancelCheck,
    ReconciliationProgressCallback,
    apply_chongqing_data_package_reconciliation_plan,
    chongqing_data_package_reconciliation_batch_count,
    plan_chongqing_data_package_reconciliation,
)
from .chongqing_entity_link_baseline import (
    DEFAULT_ACTOR,
    ONTOLOGY_PACKAGE_ID,
    ONTOLOGY_PACKAGE_SHA256,
    ChongqingEntityLinkBaseline,
)
from .db_engine import get_engine
from .entity_link_authority import EntityLinkAuthority
from .platform_contracts import (
    FrozenContract,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
)
from .temporal_entity_authority import (
    GATEWAY_DATABASE_ROLE,
    TemporalEntityAuthority,
)


class ChongqingDataPackageReconciliationServiceError(RuntimeError):
    code = "chongqing_data_package_reconciliation_service_error"


class ChongqingDataPackageReconciliationServiceConfigurationError(
    ChongqingDataPackageReconciliationServiceError
):
    code = "chongqing_data_package_reconciliation_service_configuration_error"


class ChongqingDataPackageReconciliationServiceConflictError(
    ChongqingDataPackageReconciliationServiceError
):
    code = "chongqing_data_package_reconciliation_service_conflict"


class ChongqingDataPackageReconciliationServiceForbiddenError(
    ChongqingDataPackageReconciliationServiceError
):
    code = "chongqing_data_package_reconciliation_service_forbidden"


class ChongqingDataPackageReconciliationServiceValidationError(
    ChongqingDataPackageReconciliationServiceError
):
    code = "chongqing_data_package_reconciliation_service_validation_error"


def _aware_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _baseline_actors(baseline: ChongqingEntityLinkBaseline) -> set[str]:
    return {
        *(draft.recorded_by for draft in baseline.temporal_entity_drafts),
        *(draft.recorded_by for draft in baseline.source_binding_drafts),
        baseline.link_type_draft.created_by,
        *(draft.recorded_by for draft in baseline.link_assertion_drafts),
    }


def _baseline_tenants(baseline: ChongqingEntityLinkBaseline) -> set[str]:
    return {
        baseline.tenant_id,
        *(draft.tenant_id for draft in baseline.temporal_entity_drafts),
        *(draft.tenant_id for draft in baseline.source_binding_drafts),
        baseline.link_type_draft.tenant_id,
        *(draft.tenant_id for draft in baseline.link_assertion_drafts),
    }


class ChongqingDataPackageReconciliationRequest(FrozenContract):
    """Canonical synchronous request for one full-package delta."""

    schema_id: Literal["gda.chongqing-data-package-reconciliation-request.v1"] = (
        "gda.chongqing-data-package-reconciliation-request.v1"
    )
    tenant_id: TenantId
    previous_baseline: ChongqingEntityLinkBaseline
    desired_baseline: ChongqingEntityLinkBaseline
    effective_at: datetime
    evaluated_at: datetime
    batch_size: int = Field(default=250, ge=1, le=500)
    verify_replay: bool = True
    idempotency_key: str = Field(
        min_length=3,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$",
    )
    recorded_by: str = Field(min_length=3, max_length=512)

    @field_validator("effective_at", "evaluated_at")
    @classmethod
    def _times(cls, value: datetime, info) -> datetime:
        return _aware_utc(value, info.field_name)

    @field_validator("recorded_by")
    @classmethod
    def _actor_ref(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith(("human:", "agent:", "workload:")):
            raise ValueError("recorded_by must be a canonical actor reference")
        return value

    @model_validator(mode="after")
    def _governed_baselines(self) -> ChongqingDataPackageReconciliationRequest:
        baselines = (self.previous_baseline, self.desired_baseline)
        if any(_baseline_tenants(item) != {self.tenant_id} for item in baselines):
            raise ValueError("baseline tenant_id must match every nested authority draft")
        if any(_baseline_actors(item) != {DEFAULT_ACTOR} for item in baselines):
            raise ValueError("baseline evidence actors must use the pinned baseline builder")
        if any(
            item.ontology_package_id != ONTOLOGY_PACKAGE_ID
            or item.ontology_package_sha256 != ONTOLOGY_PACKAGE_SHA256
            for item in baselines
        ):
            raise ValueError("baselines must use natural-resource ontology 2.3.0")
        if (
            self.previous_baseline.customer_bundle_id
            != self.desired_baseline.customer_bundle_id
        ):
            raise ValueError("previous and desired baselines must describe one customer bundle")
        return self

    @property
    def request_sha256(self) -> Sha256:
        return canonical_json_fingerprint(self.model_dump(mode="json"))


class ChongqingDataPackageReconciliationResponse(FrozenContract):
    """Compact, machine-verifiable result for REST and MCP callers."""

    schema_id: Literal["gda.chongqing-data-package-reconciliation-response.v1"] = (
        "gda.chongqing-data-package-reconciliation-response.v1"
    )
    tenant_id: TenantId
    idempotency_key: str
    recorded_by: str
    request_sha256: Sha256
    previous_customer_bundle_version: str
    desired_customer_bundle_version: str
    effective_at: datetime
    evaluated_at: datetime
    plan_sha256: Sha256
    receipt_sha256: Sha256
    previous_baseline_sha256: Sha256
    desired_baseline_sha256: Sha256
    authority_state_sha256: Sha256
    operation_count: int = Field(ge=0)
    batch_count: int = Field(ge=0)
    unchanged_entity_count: int = Field(ge=0)
    unchanged_source_count: int = Field(ge=0)
    retained_retired_source_count: int = Field(ge=0)
    entity_correction_count: int = Field(ge=0)
    entity_addition_count: int = Field(ge=0)
    entity_activation_count: int = Field(ge=0)
    source_binding_count: int = Field(ge=0)
    entity_retirement_count: int = Field(ge=0)
    link_operation_count: int = Field(ge=0)
    link_correction_count: int = Field(ge=0)
    link_retraction_count: int = Field(ge=0)
    link_restoration_count: int = Field(ge=0)
    link_addition_count: int = Field(ge=0)
    replay_verification: Literal["not_requested", "passed"]
    write_mode: Literal["phased_chunked_atomic_authority_batches"]
    atomicity_status: Literal["atomic_per_batch_resumable_across_phases"]
    execution_status: Literal["succeeded"] = "succeeded"
    idempotency_status: Literal["durable_sealed_plan_replay_enforced"] = (
        "durable_sealed_plan_replay_enforced"
    )
    technical_baseline_status: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    decision_status: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )

    @field_validator("effective_at", "evaluated_at")
    @classmethod
    def _times(cls, value: datetime, info) -> datetime:
        return _aware_utc(value, info.field_name)


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


class ChongqingDataPackageReconciliationLedger:
    """Durable reservation and response ledger for endpoint-level replay."""

    def __init__(self, engine: Any = None):
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise ChongqingDataPackageReconciliationServiceConfigurationError(
                "package reconciliation ledger requires PostgreSQL"
            )
        return engine

    @contextmanager
    def _transaction(self, tenant_id: str) -> Iterator[Any]:
        try:
            with self._get_engine().connect() as connection:
                with connection.begin():
                    try:
                        connection.exec_driver_sql(
                            f'SET LOCAL ROLE "{GATEWAY_DATABASE_ROLE}"'
                        )
                    except DBAPIError as exc:
                        raise (
                            ChongqingDataPackageReconciliationServiceConfigurationError(
                                "database login is not a member of the platform gateway role"
                            )
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": tenant_id},
                    )
                    yield connection
        except ChongqingDataPackageReconciliationServiceError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state in {"23505", "40001", "55000"}:
                raise ChongqingDataPackageReconciliationServiceConflictError(
                    "package reconciliation idempotency conflict"
                ) from exc
            if state == "42501":
                raise ChongqingDataPackageReconciliationServiceForbiddenError(
                    "package reconciliation tenant or role was denied"
                ) from exc
            if state in {"22023", "23514"}:
                raise ChongqingDataPackageReconciliationServiceValidationError(
                    "package reconciliation ledger payload is invalid"
                ) from exc
            if state == "P0002":
                raise ChongqingDataPackageReconciliationServiceConflictError(
                    "package reconciliation reservation was not found"
                ) from exc
            raise ChongqingDataPackageReconciliationServiceConfigurationError(
                "package reconciliation ledger is unavailable"
            ) from exc

    def load(
        self,
        request: ChongqingDataPackageReconciliationRequest,
    ) -> dict[str, Any] | None:
        with self._transaction(request.tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT status, request_sha256, plan_document, response_document
                    FROM gda_control.chongqing_data_package_reconciliation
                    WHERE tenant_id = :tenant_id AND idempotency_key = :idempotency_key
                    """
                ),
                {
                    "tenant_id": request.tenant_id,
                    "idempotency_key": request.idempotency_key,
                },
            ).mappings().one_or_none()
        if row is None:
            return None
        value = dict(row)
        value["plan_document"] = _json_value(value["plan_document"])
        value["response_document"] = _json_value(value["response_document"])
        return value

    def reserve(
        self,
        request: ChongqingDataPackageReconciliationRequest,
        plan: ChongqingDataPackageReconciliationPlan,
    ) -> dict[str, Any]:
        with self._transaction(request.tenant_id) as connection:
            result = connection.execute(
                text(
                    """
                    SELECT gda_control.reserve_chongqing_data_package_reconciliation(
                        :tenant_id,
                        :idempotency_key,
                        :request_sha256,
                        :recorded_by,
                        CAST(:plan_document AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": request.tenant_id,
                    "idempotency_key": request.idempotency_key,
                    "request_sha256": request.request_sha256,
                    "recorded_by": request.recorded_by,
                    "plan_document": json.dumps(plan.model_dump(mode="json")),
                },
            ).scalar_one()
        value = _json_value(result)
        if not isinstance(value, dict):
            raise ChongqingDataPackageReconciliationServiceValidationError(
                "package reconciliation reservation returned an invalid document"
            )
        return value

    def complete(
        self,
        request: ChongqingDataPackageReconciliationRequest,
        receipt: ChongqingDataPackageReconciliationReceipt,
        response: ChongqingDataPackageReconciliationResponse,
    ) -> dict[str, Any]:
        with self._transaction(request.tenant_id) as connection:
            result = connection.execute(
                text(
                    """
                    SELECT gda_control.complete_chongqing_data_package_reconciliation(
                        :tenant_id,
                        :idempotency_key,
                        :request_sha256,
                        CAST(:receipt_document AS jsonb),
                        CAST(:response_document AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": request.tenant_id,
                    "idempotency_key": request.idempotency_key,
                    "request_sha256": request.request_sha256,
                    "receipt_document": json.dumps(receipt.model_dump(mode="json")),
                    "response_document": json.dumps(response.model_dump(mode="json")),
                },
            ).scalar_one()
        value = _json_value(result)
        if not isinstance(value, dict):
            raise ChongqingDataPackageReconciliationServiceValidationError(
                "package reconciliation completion returned an invalid document"
            )
        return value


def _assert_replay_request(
    request: ChongqingDataPackageReconciliationRequest,
    entry: dict[str, Any],
) -> None:
    if entry.get("request_sha256") != request.request_sha256:
        raise ChongqingDataPackageReconciliationServiceConflictError(
            "idempotency key already belongs to a different reconciliation request"
        )


def _completed_response(
    request: ChongqingDataPackageReconciliationRequest,
    entry: dict[str, Any],
) -> ChongqingDataPackageReconciliationResponse | None:
    _assert_replay_request(request, entry)
    if entry.get("status") != "completed":
        return None
    try:
        return ChongqingDataPackageReconciliationResponse.model_validate(
            entry.get("response_document")
        )
    except (TypeError, ValidationError) as exc:
        raise ChongqingDataPackageReconciliationServiceValidationError(
            "stored package reconciliation response is invalid"
        ) from exc


def _response_from_receipt(
    request: ChongqingDataPackageReconciliationRequest,
    plan: ChongqingDataPackageReconciliationPlan,
    receipt: ChongqingDataPackageReconciliationReceipt,
) -> ChongqingDataPackageReconciliationResponse:
    return ChongqingDataPackageReconciliationResponse(
        tenant_id=request.tenant_id,
        idempotency_key=request.idempotency_key,
        recorded_by=request.recorded_by,
        request_sha256=request.request_sha256,
        previous_customer_bundle_version=(
            request.previous_baseline.customer_bundle_version
        ),
        desired_customer_bundle_version=request.desired_baseline.customer_bundle_version,
        effective_at=request.effective_at,
        evaluated_at=request.evaluated_at,
        plan_sha256=plan.plan_sha256,
        receipt_sha256=receipt.receipt_sha256,
        previous_baseline_sha256=receipt.previous_baseline_sha256,
        desired_baseline_sha256=receipt.desired_baseline_sha256,
        authority_state_sha256=receipt.authority_state_sha256,
        operation_count=receipt.operation_count,
        batch_count=receipt.batch_count,
        unchanged_entity_count=receipt.unchanged_entity_count,
        unchanged_source_count=receipt.unchanged_source_count,
        retained_retired_source_count=receipt.retained_retired_source_count,
        entity_correction_count=receipt.entity_correction_count,
        entity_addition_count=receipt.entity_addition_count,
        entity_activation_count=receipt.entity_activation_count,
        source_binding_count=receipt.source_binding_count,
        entity_retirement_count=receipt.entity_retirement_count,
        link_operation_count=receipt.link_operation_count,
        link_correction_count=receipt.link_correction_count,
        link_retraction_count=receipt.link_retraction_count,
        link_restoration_count=receipt.link_restoration_count,
        link_addition_count=receipt.link_addition_count,
        replay_verification=receipt.replay_verification,
        write_mode=receipt.write_mode,
        atomicity_status=receipt.atomicity_status,
    )


def execute_chongqing_data_package_reconciliation(
    request: ChongqingDataPackageReconciliationRequest,
    *,
    engine: Any = None,
    temporal_authority: Any = None,
    link_authority: Any = None,
    ledger: Any = None,
    progress_callback: ReconciliationProgressCallback | None = None,
    cancel_check: ReconciliationCancelCheck | None = None,
) -> ChongqingDataPackageReconciliationResponse:
    """Reserve one sealed plan, apply or resume it, and persist its response."""

    temporal_writer = temporal_authority or TemporalEntityAuthority(engine=engine)
    link_writer = link_authority or EntityLinkAuthority(engine=engine)
    durable_ledger = ledger or ChongqingDataPackageReconciliationLedger(engine=engine)
    if cancel_check is not None:
        cancel_check()
    if progress_callback is not None:
        progress_callback("planning", 0, 1)
    entry = durable_ledger.load(request)
    if entry is not None:
        completed = _completed_response(request, entry)
        if completed is not None:
            if progress_callback is not None:
                progress_callback("completed", 1, 1)
            return completed
        try:
            plan = ChongqingDataPackageReconciliationPlan.model_validate(
                entry.get("plan_document")
            )
        except (TypeError, ValidationError) as exc:
            raise ChongqingDataPackageReconciliationServiceValidationError(
                "stored package reconciliation plan is invalid"
            ) from exc
    else:
        candidate = plan_chongqing_data_package_reconciliation(
            previous_baseline=request.previous_baseline,
            desired_baseline=request.desired_baseline,
            effective_at=request.effective_at,
            evaluated_at=request.evaluated_at,
            temporal_authority=temporal_writer,
            link_authority=link_writer,
        )
        entry = durable_ledger.reserve(request, candidate)
        completed = _completed_response(request, entry)
        if completed is not None:
            if progress_callback is not None:
                progress_callback("completed", 1, 1)
            return completed
        try:
            plan = ChongqingDataPackageReconciliationPlan.model_validate(
                entry.get("plan_document")
            )
        except (TypeError, ValidationError) as exc:
            raise ChongqingDataPackageReconciliationServiceValidationError(
                "reserved package reconciliation plan is invalid"
            ) from exc

    batches_per_pass = chongqing_data_package_reconciliation_batch_count(
        plan,
        request.batch_size,
    )
    total_batches = batches_per_pass * (2 if request.verify_replay else 1)
    if cancel_check is not None:
        cancel_check()
    if progress_callback is not None:
        progress_callback("applying", 0, total_batches)
    receipt = apply_chongqing_data_package_reconciliation_plan(
        plan,
        temporal_authority=temporal_writer,
        link_authority=link_writer,
        batch_size=request.batch_size,
        verify_replay=request.verify_replay,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )
    response = _response_from_receipt(request, plan, receipt)
    if cancel_check is not None:
        cancel_check()
    if progress_callback is not None:
        progress_callback("finalizing", 0, 1)
    persisted = durable_ledger.complete(
        request,
        receipt,
        response,
    )
    result = ChongqingDataPackageReconciliationResponse.model_validate(persisted)
    if progress_callback is not None:
        progress_callback("completed", 1, 1)
    return result


__all__ = [
    "ChongqingDataPackageReconciliationLedger",
    "ChongqingDataPackageReconciliationRequest",
    "ChongqingDataPackageReconciliationResponse",
    "ChongqingDataPackageReconciliationServiceConfigurationError",
    "ChongqingDataPackageReconciliationServiceConflictError",
    "ChongqingDataPackageReconciliationServiceError",
    "ChongqingDataPackageReconciliationServiceForbiddenError",
    "ChongqingDataPackageReconciliationServiceValidationError",
    "execute_chongqing_data_package_reconciliation",
]
