"""Typed DataProductBlueprint contract compiled into the platform definition authority."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .platform_contracts import (
    ApprovalCase,
    Artifact,
    DataIncident,
    FrameworkAttemptObservation,
    FrameworkKind,
    LineageEvent,
    NonEmptyText,
    OrchestrationClass,
    PlatformCommand,
    PlatformCommandType,
    PlatformDefinitionVersion,
    PlatformRun,
    PortabilityClass,
    QualityResult,
    Resource,
    ResourceBinding,
    ResourceVersion,
    RunStatus,
    RunSuccessEvidence,
    Sha256,
    TenantId,
    build_resource_urn,
    canonical_json_fingerprint,
    parse_resource_urn,
    platform_definition_fingerprint,
)

DATA_PRODUCT_BLUEPRINT_SCHEMA = "gda.data_product_blueprint.v1"
DATA_PRODUCT_BLUEPRINT_CHANGE_SET_SCHEMA = "gda.data_product_blueprint_change_set.v1"
DATA_PRODUCT_BLUEPRINT_RELEASE_SCHEMA = "gda.data_product_blueprint_release.v1"
DATA_PRODUCT_BLUEPRINT_TEST_SCHEMA = "gda.data_product_blueprint_contract_test.v1"
DATA_PRODUCT_BLUEPRINT_TEST_ADMISSION_SCHEMA = "gda.data_product_blueprint_test_admission.v1"
DATA_PRODUCT_BLUEPRINT_TEST_FAILURE_SCHEMA = "gda.blueprint_test_executor_failure.v1"
DATA_PRODUCT_BLUEPRINT_TEST_CANCEL_SCHEMA = "gda.blueprint_test_executor_cancel.v1"
DATA_PRODUCT_BLUEPRINT_PROVIDER_OBSERVATION_SCHEMA = (
    "gda.data_product_blueprint_provider_observation.v1"
)
DATA_PRODUCT_BLUEPRINT_PROVIDER_RECONCILE_SCHEMA = (
    "gda.data_product_blueprint_provider_reconcile.v1"
)
DATA_PRODUCT_BLUEPRINT_PROVIDER_CANCELLATION_TIMEOUT_SCHEMA = (
    "gda.data_product_blueprint_provider_cancellation_timeout.v1"
)
DATA_PRODUCT_BLUEPRINT_PROVIDER_RETRY_SCHEMA = (
    "gda.data_product_blueprint_provider_retry.v1"
)
_PRODUCT_BLUEPRINT_COMPILE_CHECK_SCHEMA = "gda.data_product_blueprint_compile_check.v1"
DATA_PRODUCT_BLUEPRINT_REVIEW_ACTION = "data_product_blueprint.change_review"


class DataProductBlueprintChange(BaseModel):
    """One deterministic logical-definition change exposed by compile preview."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: NonEmptyText
    operation: Literal["add", "remove", "replace"]
    before_value: Any = None
    after_value: Any = None


class DataProductBlueprintCompileCheck(BaseModel):
    """Content-bound evidence that one compile-time admission check passed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    check_id: NonEmptyText
    status: Literal["passed"] = "passed"
    evidence_sha256: Sha256


class DataProductBlueprintTestCheck(BaseModel):
    """One deterministic, non-executing Blueprint contract-test result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    check_id: NonEmptyText
    status: Literal["passed"] = "passed"
    evidence_sha256: Sha256


class DataProductBlueprintTestReport(BaseModel):
    """Content-bound preflight evidence for the first Build workbench gate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    product_urn: str
    version_key: str = Field(pattern=r"^v[0-9]+\.[0-9]+\.[0-9]+$")
    definition_urn: str
    definition_version_id: UUID
    blueprint_sha256: Sha256
    definition_sha256: Sha256
    checks: tuple[DataProductBlueprintTestCheck, ...] = Field(min_length=1)
    verdict: Literal["passed"] = "passed"
    test_report_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_test_report(self) -> DataProductBlueprintTestReport:
        product = parse_resource_urn(self.product_urn)
        definition = parse_resource_urn(self.definition_urn)
        if (
            product["tenant_id"] != self.tenant_id
            or product["resource_kind"] != "data_product"
        ):
            raise ValueError("Blueprint test product must be tenant-scoped")
        if (
            definition["tenant_id"] != self.tenant_id
            or definition["resource_kind"] != "definition"
        ):
            raise ValueError("Blueprint test definition must be tenant-scoped")
        expected = data_product_blueprint_test_report_fingerprint(self)
        if self.test_report_sha256 != expected:
            raise ValueError("test_report_sha256 does not match contract-test evidence")
        return self


class DataProductBlueprintPreview(BaseModel):
    """Non-mutating compile result and exact ApprovalCase review binding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    product_urn: str
    version_key: str = Field(pattern=r"^v[0-9]+\.[0-9]+\.[0-9]+$")
    definition_urn: str
    definition_version_id: UUID
    predecessor_definition_version_id: UUID | None = None
    blueprint_sha256: Sha256
    definition_sha256: Sha256
    predecessor_definition_sha256: Sha256 | None = None
    test_checks: tuple[DataProductBlueprintTestCheck, ...] = Field(min_length=1)
    test_verdict: Literal["passed"] = "passed"
    test_report_sha256: Sha256
    changes: tuple[DataProductBlueprintChange, ...] = Field(min_length=1)
    compile_checks: tuple[DataProductBlueprintCompileCheck, ...] = Field(min_length=1)
    compile_verdict: Literal["passed"] = "passed"
    change_set_sha256: Sha256
    review_action: Literal["data_product_blueprint.change_review"] = (
        DATA_PRODUCT_BLUEPRINT_REVIEW_ACTION
    )
    review_target_resource_urn: str
    review_target_fingerprint: Sha256

    @model_validator(mode="after")
    def _consistent_preview(self) -> DataProductBlueprintPreview:
        identity = parse_resource_urn(self.definition_urn)
        product_identity = parse_resource_urn(self.product_urn)
        if identity["tenant_id"] != self.tenant_id:
            raise ValueError("preview definition tenant must match")
        if identity["resource_kind"] != "definition":
            raise ValueError("preview target must be a definition Resource")
        if (
            product_identity["tenant_id"] != self.tenant_id
            or product_identity["resource_kind"] != "data_product"
        ):
            raise ValueError("preview product must be a tenant DataProduct")
        if self.review_target_resource_urn != self.definition_urn:
            raise ValueError("preview review target must be the compiled definition")
        if self.review_target_fingerprint != self.change_set_sha256:
            raise ValueError("preview review fingerprint must bind the change set")
        if (self.predecessor_definition_version_id is None) != (
            self.predecessor_definition_sha256 is None
        ):
            raise ValueError("preview predecessor identity and hash must be set together")
        test_report = DataProductBlueprintTestReport(
            tenant_id=self.tenant_id,
            product_urn=self.product_urn,
            version_key=self.version_key,
            definition_urn=self.definition_urn,
            definition_version_id=self.definition_version_id,
            blueprint_sha256=self.blueprint_sha256,
            definition_sha256=self.definition_sha256,
            checks=self.test_checks,
            verdict=self.test_verdict,
            test_report_sha256=self.test_report_sha256,
        )
        if test_report.verdict != "passed":
            raise ValueError("preview contract tests must pass")
        expected = data_product_blueprint_change_set_fingerprint(self)
        if self.change_set_sha256 != expected:
            raise ValueError("change_set_sha256 does not match compile preview")
        return self

    def approval_context(self) -> dict[str, Any]:
        """Return bounded evidence for the existing ApprovalCase authority."""
        return {
            "schema": DATA_PRODUCT_BLUEPRINT_CHANGE_SET_SCHEMA,
            "product_urn": self.product_urn,
            "version_key": self.version_key,
            "definition_version_id": str(self.definition_version_id),
            "predecessor_definition_version_id": (
                str(self.predecessor_definition_version_id)
                if self.predecessor_definition_version_id is not None
                else None
            ),
            "blueprint_sha256": self.blueprint_sha256,
            "definition_sha256": self.definition_sha256,
            "test_report_sha256": self.test_report_sha256,
            "test_verdict": self.test_verdict,
            "test_checks": [
                check.model_dump(mode="json") for check in self.test_checks
            ],
            "predecessor_definition_sha256": self.predecessor_definition_sha256,
            "change_set_sha256": self.change_set_sha256,
            "change_count": len(self.changes),
            "change_paths": [change.path for change in self.changes],
            "compile_verdict": self.compile_verdict,
            "compile_checks": [
                check.model_dump(mode="json") for check in self.compile_checks
            ],
        }


class DataProductBlueprintReleaseBinding(BaseModel):
    """Immutable publication evidence for one approved Blueprint change set."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_by_alias=True,
        validate_by_name=True,
        serialize_by_alias=True,
    )

    contract_schema: Literal["gda.data_product_blueprint_release.v1"] = Field(
        default=DATA_PRODUCT_BLUEPRINT_RELEASE_SCHEMA,
        alias="schema",
    )
    tenant_id: TenantId
    product_urn: str
    version_key: str = Field(pattern=r"^v[0-9]+\.[0-9]+\.[0-9]+$")
    definition_urn: str
    definition_version_id: UUID
    blueprint_sha256: Sha256
    definition_sha256: Sha256
    change_set_sha256: Sha256
    test_report_sha256: Sha256
    approval_case_ref: str
    test_run_id: UUID | None = None
    test_success_evidence_sha256: Sha256 | None = None

    @field_validator("product_urn", "definition_urn", "approval_case_ref")
    @classmethod
    def _valid_release_urns(cls, value: str) -> str:
        parse_resource_urn(value)
        return value

    @model_validator(mode="after")
    def _consistent_release(self) -> DataProductBlueprintReleaseBinding:
        product = parse_resource_urn(self.product_urn)
        definition = parse_resource_urn(self.definition_urn)
        approval = parse_resource_urn(self.approval_case_ref)
        if (
            product["tenant_id"] != self.tenant_id
            or product["resource_kind"] != "data_product"
        ):
            raise ValueError("Blueprint release product must be a tenant DataProduct")
        if (
            definition["tenant_id"] != self.tenant_id
            or definition["resource_kind"] != "definition"
        ):
            raise ValueError("Blueprint release definition must be tenant-scoped")
        if (
            approval["tenant_id"] != self.tenant_id
            or approval["resource_kind"] != "approval_case"
        ):
            raise ValueError("Blueprint release approval must be tenant-scoped")
        if (self.test_run_id is None) != (
            self.test_success_evidence_sha256 is None
        ):
            raise ValueError(
                "test_run_id and test_success_evidence_sha256 must be supplied together"
            )
        return self


class DataProductBlueprintReview(BaseModel):
    """One compiled change set admitted to the shared ApprovalCase authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    preview: DataProductBlueprintPreview
    approval_case: ApprovalCase

    @model_validator(mode="after")
    def _consistent_review(self) -> DataProductBlueprintReview:
        if self.approval_case.tenant_id != self.preview.tenant_id:
            raise ValueError("Blueprint review tenant must match ApprovalCase")
        if self.approval_case.target_resource_urn != self.preview.definition_urn:
            raise ValueError("ApprovalCase must target the Blueprint definition")
        if self.approval_case.target_fingerprint != self.preview.change_set_sha256:
            raise ValueError("ApprovalCase must bind the Blueprint change set")
        if self.approval_case.action != DATA_PRODUCT_BLUEPRINT_REVIEW_ACTION:
            raise ValueError("ApprovalCase action must be Blueprint change review")
        context = self.approval_case.request_context
        if (
            context.get("schema") != DATA_PRODUCT_BLUEPRINT_CHANGE_SET_SCHEMA
            or context.get("product_urn") != self.preview.product_urn
            or context.get("version_key") != self.preview.version_key
            or context.get("test_report_sha256") != self.preview.test_report_sha256
            or context.get("test_verdict") != self.preview.test_verdict
        ):
            raise ValueError("ApprovalCase context must bind Blueprint test evidence")
        return self


class DataProductBlueprint(BaseModel):
    """Immutable build intent for one versioned DataProduct definition.

    The blueprint is a typed input contract, not a second registry. Its
    compiled output is stored by the existing definition authority.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    definition_urn: str
    definition_version_id: UUID
    predecessor_definition_version_id: UUID | None = None
    version_key: str = Field(pattern=r"^v[0-9]+\.[0-9]+\.[0-9]+$")
    product_urn: str
    domain: NonEmptyText
    owner_ref: NonEmptyText
    source_refs: tuple[str, ...] = Field(min_length=1)
    storage_placement: dict[str, Any]
    model_contract: dict[str, Any]
    quality_contract: dict[str, Any]
    security_policy: dict[str, Any]
    slo_contract: dict[str, Any]
    pipeline: dict[str, Any]
    projections: tuple[dict[str, Any], ...] = ()
    retention_policy: dict[str, Any]
    cost_policy: dict[str, Any]
    created_by: NonEmptyText
    created_at: datetime
    blueprint_sha256: Sha256

    @field_validator("definition_urn", "product_urn")
    @classmethod
    def _valid_urns(cls, value: str) -> str:
        parse_resource_urn(value)
        return value

    @field_validator("source_refs")
    @classmethod
    def _valid_source_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("source_refs must not contain duplicates")
        for source_ref in value:
            parse_resource_urn(source_ref)
        return value

    @field_validator("created_at")
    @classmethod
    def _created_at_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _consistent_blueprint(self) -> DataProductBlueprint:
        definition = parse_resource_urn(self.definition_urn)
        product = parse_resource_urn(self.product_urn)
        if definition["tenant_id"] != self.tenant_id or definition["resource_kind"] != "definition":
            raise ValueError("definition_urn must identify a tenant definition Resource")
        if product["tenant_id"] != self.tenant_id or product["resource_kind"] != "data_product":
            raise ValueError("product_urn must identify a tenant DataProduct")
        if self.predecessor_definition_version_id == self.definition_version_id:
            raise ValueError("a blueprint definition cannot be its own predecessor")
        if any(
            parse_resource_urn(source_ref)["tenant_id"] != self.tenant_id
            for source_ref in self.source_refs
        ):
            raise ValueError("source_refs must identify Resources in the blueprint tenant")
        if any(not value for value in (
            self.storage_placement,
            self.model_contract,
            self.quality_contract,
            self.security_policy,
            self.slo_contract,
            self.pipeline,
            self.retention_policy,
            self.cost_policy,
        )):
            raise ValueError("blueprint contracts and policies must not be empty")
        if self.blueprint_sha256 != data_product_blueprint_fingerprint(self):
            raise ValueError("blueprint_sha256 does not match the blueprint")
        return self


class DataProductBlueprintTestRunRequest(BaseModel):
    """Explicit admission input for a real PlatformRun-backed test."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    blueprint: DataProductBlueprint
    run_id: UUID
    idempotency_key: NonEmptyText
    input_bindings: tuple[ResourceBinding, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_binding_names(self) -> DataProductBlueprintTestRunRequest:
        names = [binding.binding_name for binding in self.input_bindings]
        if len(names) != len(set(names)):
            raise ValueError("test run input binding names must be unique")
        return self


class DataProductBlueprintTestRunAdmission(BaseModel):
    """Durable admission result; provider execution remains a separate step."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    contract_schema: Literal[
        "gda.data_product_blueprint_test_admission.v1"
    ] = Field(
        default=DATA_PRODUCT_BLUEPRINT_TEST_ADMISSION_SCHEMA,
        alias="schema",
    )
    tenant_id: TenantId
    definition_version_id: UUID
    definition_sha256: Sha256
    test_report: DataProductBlueprintTestReport
    run: PlatformRun
    execution_plan: Artifact
    provider_command: PlatformCommand | None = None
    provider_execution_required: Literal[True] = True

    @model_validator(mode="after")
    def _consistent_admission(self) -> DataProductBlueprintTestRunAdmission:
        if self.run.tenant_id != self.tenant_id:
            raise ValueError("test admission Run tenant must match")
        if self.run.definition_version_id != self.definition_version_id:
            raise ValueError("test admission Run must bind the Blueprint definition")
        if self.execution_plan.run_id != self.run.run_id:
            raise ValueError("execution plan must bind the admitted Run")
        if self.execution_plan.artifact_role.value != "execution_plan":
            raise ValueError("test admission artifact must be an execution plan")
        if (
            self.execution_plan.manifest.get("test_report_sha256")
            != self.test_report.test_report_sha256
        ):
            raise ValueError("execution plan must bind contract-test evidence")
        provider = self.execution_plan.manifest.get("provider_contract") or {}
        if provider.get("engine") == "duckdb":
            command = self.provider_command
            if command is None:
                raise ValueError("DuckDB test admission must enqueue its provider command")
            if (
                command.tenant_id != self.tenant_id
                or command.run_id != self.run.run_id
                or command.command_type
                is not PlatformCommandType.BLUEPRINT_PROVIDER_EXECUTE
                or command.execution_plan_artifact_id
                != self.execution_plan.artifact_id
                or command.payload.get("execution_plan_sha256")
                != self.execution_plan.manifest.get("plan_sha256")
            ):
                raise ValueError("DuckDB provider command must bind the admitted plan")
        elif self.provider_command is not None:
            raise ValueError("non-DuckDB test admission cannot enqueue a DuckDB command")
        return self


class DataProductBlueprintTestExecutionRequest(BaseModel):
    """Request for the explicitly non-production deterministic local executor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    reason: NonEmptyText = "execute deterministic Blueprint contract test"


class DataProductBlueprintTestExecutionFailureRequest(BaseModel):
    """Failure receipt input for the explicitly non-production local executor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    error_code: NonEmptyText = Field(
        default="deterministic_executor_failed",
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9_.:-]{0,127}$",
    )
    reason: NonEmptyText = "deterministic Blueprint test executor failed"


class DataProductBlueprintTestCancellationRequest(BaseModel):
    """Executor convergence input after governed cancellation admission."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    external_cancel_ref: NonEmptyText = Field(
        default="deterministic-local-cancel",
        max_length=512,
    )
    reason: NonEmptyText = "deterministic Blueprint test cancellation converged"


class DataProductBlueprintProviderReconcileRequest(BaseModel):
    """Content-bound provider receipt for a Blueprint Run in reconciliation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    run_id: UUID
    execution_plan_artifact_id: UUID
    provider_state: Literal["running", "failed", "cancelled"]
    attempt_observation: FrameworkAttemptObservation
    reason: NonEmptyText
    reconcile_receipt_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_receipt(self) -> DataProductBlueprintProviderReconcileRequest:
        observation = self.attempt_observation
        if observation.tenant_id != self.tenant_id or observation.run_id != self.run_id:
            raise ValueError("provider observation must bind the reconciled tenant and Run")
        if observation.framework_kind in {
            FrameworkKind.DOLPHINSCHEDULER,
            FrameworkKind.TEMPORAL,
            FrameworkKind.LEGACY,
        }:
            raise ValueError("Blueprint provider receipt requires an execution provider")
        if observation.observed_state != self.provider_state:
            raise ValueError("provider observation state must match provider_state")
        evidence = observation.evidence
        observed_at = observation.observed_at.astimezone(UTC).isoformat().replace(
            "+00:00", "Z"
        )
        if (
            evidence.get("schema")
            != DATA_PRODUCT_BLUEPRINT_PROVIDER_OBSERVATION_SCHEMA
            or evidence.get("execution_plan_artifact_id")
            != str(self.execution_plan_artifact_id)
            or evidence.get("provider_state") != self.provider_state
            or evidence.get("observation_id") != str(observation.observation_id)
            or evidence.get("attempt_no") != observation.attempt_no
            or evidence.get("framework_kind") != observation.framework_kind.value
            or evidence.get("external_namespace") != observation.external_namespace
            or evidence.get("external_run_id") != observation.external_run_id
            or evidence.get("external_attempt_id") != observation.external_attempt_id
            or evidence.get("observed_at") != observed_at
        ):
            raise ValueError("provider observation evidence does not bind its receipt")
        if observation.observation_sha256 != canonical_json_fingerprint(evidence):
            raise ValueError("provider observation fingerprint does not match evidence")
        if (
            self.reconcile_receipt_sha256
            != data_product_blueprint_provider_reconcile_fingerprint(self)
        ):
            raise ValueError("provider reconcile receipt fingerprint does not match")
        return self


class DataProductBlueprintProviderReconciliation(BaseModel):
    """Durable result of applying one provider receipt to PlatformRun authority."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    contract_schema: Literal[
        "gda.data_product_blueprint_provider_reconcile.v1"
    ] = Field(
        default=DATA_PRODUCT_BLUEPRINT_PROVIDER_RECONCILE_SCHEMA,
        alias="schema",
    )
    tenant_id: TenantId
    run: PlatformRun
    execution_plan: Artifact
    attempt_observation: FrameworkAttemptObservation
    provider_state: Literal["running", "failed", "cancelled"]
    converged_status: RunStatus
    reconcile_receipt_sha256: Sha256
    observation_created: bool
    transitioned: bool

    @model_validator(mode="after")
    def _consistent_reconciliation(
        self,
    ) -> DataProductBlueprintProviderReconciliation:
        expected_status = RunStatus(self.provider_state)
        if self.converged_status != expected_status:
            raise ValueError("provider state and converged Run status must match")
        if self.run.tenant_id != self.tenant_id:
            raise ValueError("reconciled Run tenant must match")
        if self.execution_plan.run_id != self.run.run_id:
            raise ValueError("reconciliation execution plan must bind the Run")
        if self.execution_plan.artifact_role.value != "execution_plan":
            raise ValueError("reconciliation requires an execution plan Artifact")
        if self.attempt_observation.run_id != self.run.run_id:
            raise ValueError("reconciliation observation must bind the Run")
        if self.transitioned and self.run.status != expected_status:
            raise ValueError("new reconciliation must return the converged Run status")
        return self


class DataProductBlueprintProviderCancellationTimeoutRequest(BaseModel):
    """Content-bound timeout receipt after provider cancellation retries exhaust."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    run_id: UUID
    execution_plan_artifact_id: UUID
    provider_state: NonEmptyText
    reconcile_attempt: int = Field(ge=1, le=100)
    max_reconcile_attempts: int = Field(ge=1, le=100)
    attempt_observation: FrameworkAttemptObservation
    reason: NonEmptyText
    timeout_receipt_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_timeout_receipt(
        self,
    ) -> DataProductBlueprintProviderCancellationTimeoutRequest:
        observation = self.attempt_observation
        if observation.tenant_id != self.tenant_id or observation.run_id != self.run_id:
            raise ValueError("provider observation must bind the timeout tenant and Run")
        if observation.framework_kind in {
            FrameworkKind.DOLPHINSCHEDULER,
            FrameworkKind.TEMPORAL,
            FrameworkKind.LEGACY,
        }:
            raise ValueError("Blueprint timeout receipt requires an execution provider")
        if observation.observed_state != self.provider_state:
            raise ValueError("provider observation state must match provider_state")
        if self.reconcile_attempt < self.max_reconcile_attempts:
            raise ValueError("cancellation timeout requires exhausted reconcile attempts")
        if self.provider_state.lower() in {
            "cancelled",
            "canceled",
            "stopped",
            "stop",
            "success",
            "succeeded",
        }:
            raise ValueError("cancellation timeout requires a non-cancelled provider state")
        evidence = observation.evidence
        observed_at = observation.observed_at.astimezone(UTC).isoformat().replace(
            "+00:00", "Z"
        )
        if (
            evidence.get("schema")
            != DATA_PRODUCT_BLUEPRINT_PROVIDER_CANCELLATION_TIMEOUT_SCHEMA
            or evidence.get("execution_plan_artifact_id")
            != str(self.execution_plan_artifact_id)
            or evidence.get("provider_state") != self.provider_state
            or evidence.get("observation_id") != str(observation.observation_id)
            or evidence.get("attempt_no") != observation.attempt_no
            or evidence.get("framework_kind") != observation.framework_kind.value
            or evidence.get("external_namespace") != observation.external_namespace
            or evidence.get("external_run_id") != observation.external_run_id
            or evidence.get("external_attempt_id") != observation.external_attempt_id
            or evidence.get("observed_at") != observed_at
            or evidence.get("reconcile_attempt") != self.reconcile_attempt
            or evidence.get("max_reconcile_attempts") != self.max_reconcile_attempts
        ):
            raise ValueError("provider timeout observation evidence does not bind its receipt")
        if observation.observation_sha256 != canonical_json_fingerprint(evidence):
            raise ValueError("provider timeout observation fingerprint does not match evidence")
        if (
            self.timeout_receipt_sha256
            != data_product_blueprint_provider_cancellation_timeout_fingerprint(self)
        ):
            raise ValueError("provider timeout receipt fingerprint does not match")
        return self


class DataProductBlueprintProviderCancellationTimeout(BaseModel):
    """Durable incident and failed Run produced by an exhausted provider cancel retry."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    contract_schema: Literal[
        "gda.data_product_blueprint_provider_cancellation_timeout.v1"
    ] = Field(
        default=DATA_PRODUCT_BLUEPRINT_PROVIDER_CANCELLATION_TIMEOUT_SCHEMA,
        alias="schema",
    )
    tenant_id: TenantId
    run: PlatformRun
    execution_plan: Artifact
    attempt_observation: FrameworkAttemptObservation
    provider_state: NonEmptyText
    reconcile_attempt: int = Field(ge=1, le=100)
    max_reconcile_attempts: int = Field(ge=1, le=100)
    incident: DataIncident
    timeout_receipt_sha256: Sha256
    observation_created: bool
    incident_created: bool
    transitioned: bool

    @model_validator(mode="after")
    def _consistent_timeout(
        self,
    ) -> DataProductBlueprintProviderCancellationTimeout:
        if self.run.tenant_id != self.tenant_id:
            raise ValueError("timeout Run tenant must match")
        if self.execution_plan.run_id != self.run.run_id:
            raise ValueError("timeout execution plan must bind the Run")
        if self.execution_plan.artifact_role.value != "execution_plan":
            raise ValueError("timeout requires an execution plan Artifact")
        if self.attempt_observation.run_id != self.run.run_id:
            raise ValueError("timeout observation must bind the Run")
        if self.incident.tenant_id != self.tenant_id or self.incident.run_id != self.run.run_id:
            raise ValueError("timeout incident must bind the Run")
        if self.provider_state != self.attempt_observation.observed_state:
            raise ValueError("timeout provider state must match observation")
        if self.reconcile_attempt < self.max_reconcile_attempts:
            raise ValueError("timeout result requires exhausted reconcile attempts")
        if self.transitioned and self.run.status.value != "failed":
            raise ValueError("new timeout must return a failed Run")
        return self


class DataProductBlueprintProviderRetryRequest(BaseModel):
    """Content-bound retry receipt for a transient provider failure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    run_id: UUID
    execution_plan_artifact_id: UUID
    provider_state: NonEmptyText
    retry_attempt: int = Field(ge=1, le=100)
    max_retry_attempts: int = Field(ge=1, le=100)
    attempt_observation: FrameworkAttemptObservation
    reason: NonEmptyText
    retry_receipt_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_retry_receipt(
        self,
    ) -> DataProductBlueprintProviderRetryRequest:
        observation = self.attempt_observation
        if observation.tenant_id != self.tenant_id or observation.run_id != self.run_id:
            raise ValueError("provider observation must bind the retry tenant and Run")
        if observation.framework_kind in {
            FrameworkKind.DOLPHINSCHEDULER,
            FrameworkKind.TEMPORAL,
            FrameworkKind.LEGACY,
        }:
            raise ValueError("Blueprint retry receipt requires an execution provider")
        if observation.observed_state != self.provider_state:
            raise ValueError("provider observation state must match provider_state")
        if self.provider_state.lower() not in {
            "failed",
            "error",
            "timeout",
            "retryable",
            "retryable_failed",
        }:
            raise ValueError("provider retry requires a transient failure state")
        if self.retry_attempt >= self.max_retry_attempts:
            raise ValueError(
                "provider retry attempts are exhausted; submit a terminal reconcile"
            )
        evidence = observation.evidence
        observed_at = observation.observed_at.astimezone(UTC).isoformat().replace(
            "+00:00", "Z"
        )
        if (
            evidence.get("schema") != DATA_PRODUCT_BLUEPRINT_PROVIDER_RETRY_SCHEMA
            or evidence.get("execution_plan_artifact_id")
            != str(self.execution_plan_artifact_id)
            or evidence.get("provider_state") != self.provider_state
            or evidence.get("observation_id") != str(observation.observation_id)
            or evidence.get("attempt_no") != observation.attempt_no
            or evidence.get("framework_kind") != observation.framework_kind.value
            or evidence.get("external_namespace") != observation.external_namespace
            or evidence.get("external_run_id") != observation.external_run_id
            or evidence.get("external_attempt_id") != observation.external_attempt_id
            or evidence.get("observed_at") != observed_at
            or evidence.get("retry_attempt") != self.retry_attempt
            or evidence.get("max_retry_attempts") != self.max_retry_attempts
        ):
            raise ValueError("provider retry observation evidence does not bind its receipt")
        if observation.observation_sha256 != canonical_json_fingerprint(evidence):
            raise ValueError("provider retry observation fingerprint does not match evidence")
        if self.retry_receipt_sha256 != data_product_blueprint_provider_retry_fingerprint(self):
            raise ValueError("provider retry receipt fingerprint does not match")
        return self


class DataProductBlueprintProviderRetry(BaseModel):
    """Durable retry/backoff decision returned by the shared Run authority."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    contract_schema: Literal["gda.data_product_blueprint_provider_retry.v1"] = Field(
        default=DATA_PRODUCT_BLUEPRINT_PROVIDER_RETRY_SCHEMA,
        alias="schema",
    )
    tenant_id: TenantId
    run: PlatformRun
    execution_plan: Artifact
    attempt_observation: FrameworkAttemptObservation
    provider_state: NonEmptyText
    retry_attempt: int = Field(ge=1, le=100)
    max_retry_attempts: int = Field(ge=1, le=100)
    backoff_seconds: int = Field(ge=1, le=300)
    retry_after: datetime
    retry_command: PlatformCommand
    retry_receipt_sha256: Sha256
    observation_created: bool
    command_created: bool
    transitioned: bool

    @field_validator("retry_after")
    @classmethod
    def _utc_retry_after(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retry_after must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _consistent_retry(self) -> DataProductBlueprintProviderRetry:
        if self.run.tenant_id != self.tenant_id:
            raise ValueError("retry Run tenant must match")
        if self.execution_plan.run_id != self.run.run_id:
            raise ValueError("retry execution plan must bind the Run")
        if self.execution_plan.artifact_role.value != "execution_plan":
            raise ValueError("retry requires an execution plan Artifact")
        if self.attempt_observation.run_id != self.run.run_id:
            raise ValueError("retry observation must bind the Run")
        if self.retry_command.run_id != self.run.run_id:
            raise ValueError("retry command must bind the Run")
        if self.retry_command.execution_plan_artifact_id != self.execution_plan.artifact_id:
            raise ValueError("retry command must bind the execution plan")
        if self.retry_command.trigger_observation_id != self.attempt_observation.observation_id:
            raise ValueError("retry command must bind the provider observation")
        if self.retry_command.available_at != self.retry_after:
            raise ValueError("retry command must enforce retry_after")
        if self.provider_state != self.attempt_observation.observed_state:
            raise ValueError("retry provider state must match observation")
        if self.retry_attempt >= self.max_retry_attempts:
            raise ValueError("retry result cannot exceed the retry budget")
        expected_backoff = data_product_blueprint_provider_retry_backoff_seconds(
            self.retry_attempt
        )
        if self.backoff_seconds != expected_backoff:
            raise ValueError("retry backoff does not match the platform policy")
        expected_after = self.attempt_observation.observed_at + timedelta(
            seconds=expected_backoff
        )
        if self.retry_after != expected_after:
            raise ValueError("retry_after does not match the observation and backoff")
        if self.transitioned and self.run.status.value != "dispatching":
            raise ValueError("new retry must return a dispatching Run")
        return self


class DataProductBlueprintTestExecution(BaseModel):
    """Immutable receipt set produced by the deterministic local executor."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    contract_schema: Literal["gda.data_product_blueprint_test_execution.v1"] = Field(
        default="gda.data_product_blueprint_test_execution.v1",
        alias="schema",
    )
    tenant_id: TenantId
    run: PlatformRun
    output_resource_version: ResourceVersion
    attempt_observation: FrameworkAttemptObservation
    output_artifact: Artifact
    quality_evidence_artifact: Artifact
    quality_result: QualityResult
    lineage_events: tuple[LineageEvent, ...] = Field(min_length=1)
    success_evidence: RunSuccessEvidence
    executor_mode: Literal["deterministic_local", "duckdb_provider"] = (
        "deterministic_local"
    )

    @model_validator(mode="after")
    def _consistent_execution(self) -> DataProductBlueprintTestExecution:
        run_id = self.run.run_id
        if self.run.tenant_id != self.tenant_id:
            raise ValueError("test execution Run tenant must match")
        if self.attempt_observation.run_id != run_id:
            raise ValueError("attempt observation must bind the executed Run")
        if self.output_artifact.run_id != run_id:
            raise ValueError("output Artifact must bind the executed Run")
        if (
            self.output_artifact.resource_version_id
            != self.output_resource_version.resource_version_id
        ):
            raise ValueError("output Artifact must bind the output ResourceVersion")
        if self.quality_evidence_artifact.run_id != run_id:
            raise ValueError("quality evidence Artifact must bind the executed Run")
        if (
            self.quality_evidence_artifact.resource_version_id
            != self.output_resource_version.resource_version_id
        ):
            raise ValueError("quality evidence must bind the output ResourceVersion")
        if self.quality_result.run_id != run_id:
            raise ValueError("QualityResult must bind the executed Run")
        if self.quality_result.evidence_artifact_id != self.quality_evidence_artifact.artifact_id:
            raise ValueError("QualityResult must bind its evidence Artifact")
        if (
            self.quality_result.resource_version_id
            != self.output_resource_version.resource_version_id
        ):
            raise ValueError("QualityResult must bind the output ResourceVersion")
        if any(
            event.run_id != run_id
            or event.target_resource_version_id
            != self.output_resource_version.resource_version_id
            or event.artifact_id != self.output_artifact.artifact_id
            for event in self.lineage_events
        ):
            raise ValueError("LineageEvents must bind the executed output")
        if self.success_evidence.run_id != run_id:
            raise ValueError("RunSuccessEvidence must bind the executed Run")
        if self.success_evidence.attempt_observation_id != self.attempt_observation.observation_id:
            raise ValueError("RunSuccessEvidence must bind the attempt observation")
        if self.success_evidence.output_artifact_id != self.output_artifact.artifact_id:
            raise ValueError("RunSuccessEvidence must bind the output Artifact")
        if self.success_evidence.quality_result_id != self.quality_result.quality_result_id:
            raise ValueError("RunSuccessEvidence must bind the QualityResult")
        if self.success_evidence.lineage_event_id != self.lineage_events[0].lineage_event_id:
            raise ValueError("RunSuccessEvidence must bind the first LineageEvent")
        return self


def data_product_blueprint_fingerprint(
    blueprint: DataProductBlueprint | dict[str, Any],
) -> str:
    """Return a stable hash for the blueprint payload, excluding its hash."""
    if isinstance(blueprint, BaseModel):
        payload = blueprint.model_dump(mode="python", exclude={"blueprint_sha256"})
    else:
        payload = {
            key: value for key, value in blueprint.items() if key != "blueprint_sha256"
        }
        payload.setdefault("predecessor_definition_version_id", None)
        created_at = payload.get("created_at")
        if isinstance(created_at, str):
            try:
                parsed_created_at = datetime.fromisoformat(
                    created_at.replace("Z", "+00:00")
                )
            except ValueError:
                pass
            else:
                if (
                    parsed_created_at.tzinfo is not None
                    and parsed_created_at.utcoffset() is not None
                ):
                    payload["created_at"] = parsed_created_at
    return canonical_json_fingerprint(
        {"schema": DATA_PRODUCT_BLUEPRINT_SCHEMA, **_canonical_blueprint_value(payload)}
    )


def _canonical_blueprint_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _canonical_blueprint_value(value.model_dump(mode="python"))
    if isinstance(value, dict):
        return {
            str(key): _canonical_blueprint_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_blueprint_value(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return value


def data_product_blueprint_change_set_fingerprint(
    preview: DataProductBlueprintPreview | dict[str, Any],
) -> str:
    """Return the immutable identity of one compiled Blueprint change set."""
    if isinstance(preview, BaseModel):
        payload = preview.model_dump(
            mode="python",
            exclude={
                "change_set_sha256",
                "review_target_fingerprint",
            },
        )
    else:
        payload = {
            key: value
            for key, value in preview.items()
            if key not in {"change_set_sha256", "review_target_fingerprint"}
        }
    return canonical_json_fingerprint(
        {
            "schema": DATA_PRODUCT_BLUEPRINT_CHANGE_SET_SCHEMA,
            **_canonical_blueprint_value(payload),
        }
    )


def data_product_blueprint_test_report_fingerprint(
    report: DataProductBlueprintTestReport | dict[str, Any],
) -> str:
    """Return the stable hash of contract-test evidence, excluding its hash."""
    if isinstance(report, BaseModel):
        payload = report.model_dump(mode="python", exclude={"test_report_sha256"})
    else:
        payload = {
            key: value for key, value in report.items() if key != "test_report_sha256"
        }
    return canonical_json_fingerprint(
        {
            "schema": DATA_PRODUCT_BLUEPRINT_TEST_SCHEMA,
            **_canonical_blueprint_value(payload),
        }
    )


def data_product_blueprint_provider_reconcile_fingerprint(
    receipt: DataProductBlueprintProviderReconcileRequest | dict[str, Any],
) -> str:
    """Return the immutable identity of one provider reconciliation receipt."""
    if isinstance(receipt, BaseModel):
        payload = receipt.model_dump(
            mode="python",
            exclude={"reconcile_receipt_sha256"},
        )
    else:
        payload = {
            key: value
            for key, value in receipt.items()
            if key != "reconcile_receipt_sha256"
        }
    return canonical_json_fingerprint(
        {
            "schema": DATA_PRODUCT_BLUEPRINT_PROVIDER_RECONCILE_SCHEMA,
            **_canonical_blueprint_value(payload),
        }
    )


def data_product_blueprint_provider_cancellation_timeout_fingerprint(
    receipt: DataProductBlueprintProviderCancellationTimeoutRequest | dict[str, Any],
) -> str:
    """Return the stable hash of one exhausted provider cancellation receipt."""
    if isinstance(receipt, BaseModel):
        payload = receipt.model_dump(mode="python", exclude={"timeout_receipt_sha256"})
    else:
        payload = {
            key: value for key, value in receipt.items() if key != "timeout_receipt_sha256"
        }
    return canonical_json_fingerprint(
        {
            "schema": DATA_PRODUCT_BLUEPRINT_PROVIDER_CANCELLATION_TIMEOUT_SCHEMA,
            **_canonical_blueprint_value(payload),
        }
    )


def data_product_blueprint_provider_retry_backoff_seconds(retry_attempt: int) -> int:
    """Return the bounded exponential backoff for one provider retry attempt."""
    if not 1 <= retry_attempt <= 100:
        raise ValueError("retry_attempt must be between 1 and 100")
    return min(300, 5 * (2 ** min(retry_attempt - 1, 6)))


def data_product_blueprint_provider_retry_fingerprint(
    receipt: DataProductBlueprintProviderRetryRequest | dict[str, Any],
) -> str:
    """Return the stable hash of one provider retry receipt."""
    if isinstance(receipt, BaseModel):
        payload = receipt.model_dump(mode="python", exclude={"retry_receipt_sha256"})
    else:
        payload = {
            key: value for key, value in receipt.items() if key != "retry_receipt_sha256"
        }
    return canonical_json_fingerprint(
        {
            "schema": DATA_PRODUCT_BLUEPRINT_PROVIDER_RETRY_SCHEMA,
            **_canonical_blueprint_value(payload),
        }
    )


def _logical_definition(definition: PlatformDefinitionVersion) -> dict[str, Any]:
    return {
        "orchestration_class": definition.orchestration_class.value,
        "capability_id": definition.capability_id,
        "portability_class": definition.portability_class.value,
        "definition_document": definition.definition_document,
        "input_contract": definition.input_contract,
        "output_contract": definition.output_contract,
    }


_MISSING = object()


def _definition_changes(
    before: Any,
    after: Any,
    *,
    path: str = "",
) -> tuple[DataProductBlueprintChange, ...]:
    changes: list[DataProductBlueprintChange] = []
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(before.keys() | after.keys(), key=str):
            child_path = f"{path}.{key}" if path else str(key)
            before_value = before.get(key, _MISSING)
            after_value = after.get(key, _MISSING)
            if before_value is _MISSING:
                changes.append(
                    DataProductBlueprintChange(
                        path=child_path,
                        operation="add",
                        after_value=after_value,
                    )
                )
            elif after_value is _MISSING:
                changes.append(
                    DataProductBlueprintChange(
                        path=child_path,
                        operation="remove",
                        before_value=before_value,
                    )
                )
            else:
                changes.extend(
                    _definition_changes(
                        before_value,
                        after_value,
                        path=child_path,
                    )
                )
        return tuple(changes)
    if before != after:
        changes.append(
            DataProductBlueprintChange(
                path=path,
                operation="replace",
                before_value=before,
                after_value=after,
            )
        )
    return tuple(changes)


def _compile_check(check_id: str, evidence: dict[str, Any]) -> DataProductBlueprintCompileCheck:
    return DataProductBlueprintCompileCheck(
        check_id=check_id,
        evidence_sha256=canonical_json_fingerprint(
            {
                "schema": _PRODUCT_BLUEPRINT_COMPILE_CHECK_SCHEMA,
                "check_id": check_id,
                "evidence": _canonical_blueprint_value(evidence),
            }
        ),
    )


def _test_check(check_id: str, evidence: dict[str, Any]) -> DataProductBlueprintTestCheck:
    return DataProductBlueprintTestCheck(
        check_id=check_id,
        evidence_sha256=canonical_json_fingerprint(
            {
                "schema": DATA_PRODUCT_BLUEPRINT_TEST_SCHEMA,
                "check_id": check_id,
                "evidence": _canonical_blueprint_value(evidence),
            }
        ),
    )


def build_data_product_blueprint_test_report(
    blueprint: DataProductBlueprint,
    *,
    definition: PlatformDefinitionVersion | None = None,
) -> DataProductBlueprintTestReport:
    """Build deterministic contract-test evidence without provider execution."""
    registration = compile_data_product_blueprint(blueprint)
    expected_definition = definition or registration.definition
    if expected_definition != registration.definition:
        raise ValueError("Blueprint definition differs from contract-test definition")
    checks = (
        _test_check(
            "blueprint_integrity",
            {"blueprint_sha256": blueprint.blueprint_sha256},
        ),
        _test_check(
            "definition_integrity",
            {
                "definition_sha256": registration.definition.definition_sha256,
                "definition_urn": blueprint.definition_urn,
                "definition_version_id": str(blueprint.definition_version_id),
            },
        ),
        _test_check(
            "source_contract",
            {
                "source_count": len(blueprint.source_refs),
                "source_refs": list(blueprint.source_refs),
            },
        ),
        _test_check(
            "storage_contract",
            {"storage_placement": blueprint.storage_placement},
        ),
        _test_check(
            "pipeline_contract",
            {"pipeline": blueprint.pipeline},
        ),
        _test_check(
            "quality_security_slo_contract",
            {
                "quality_contract": blueprint.quality_contract,
                "security_policy": blueprint.security_policy,
                "slo_contract": blueprint.slo_contract,
            },
        ),
        _test_check(
            "projection_contract",
            {"projection_count": len(blueprint.projections)},
        ),
    )
    values = {
        "tenant_id": blueprint.tenant_id,
        "product_urn": blueprint.product_urn,
        "version_key": blueprint.version_key,
        "definition_urn": blueprint.definition_urn,
        "definition_version_id": blueprint.definition_version_id,
        "blueprint_sha256": blueprint.blueprint_sha256,
        "definition_sha256": registration.definition.definition_sha256,
        "checks": checks,
        "verdict": "passed",
    }
    return DataProductBlueprintTestReport(
        **values,
        test_report_sha256=data_product_blueprint_test_report_fingerprint(values),
    )


def compile_data_product_blueprint(
    blueprint: DataProductBlueprint,
):
    """Compile a blueprint into the existing definition registration contract."""
    from .platform_gateway import DefinitionRegistration

    definition_document = {
        "schema": DATA_PRODUCT_BLUEPRINT_SCHEMA,
        "blueprint_sha256": blueprint.blueprint_sha256,
        "version_key": blueprint.version_key,
        "product_urn": blueprint.product_urn,
        "domain": blueprint.domain,
        "owner_ref": blueprint.owner_ref,
        "sources": list(blueprint.source_refs),
        "storage_placement": blueprint.storage_placement,
        "model_contract": blueprint.model_contract,
        "quality_contract": blueprint.quality_contract,
        "security_policy": blueprint.security_policy,
        "slo_contract": blueprint.slo_contract,
        "pipeline": blueprint.pipeline,
        "projections": list(blueprint.projections),
        "retention_policy": blueprint.retention_policy,
        "cost_policy": blueprint.cost_policy,
    }
    input_contract = {
        "schema": "gda.data_product_blueprint.input.v1",
        "sources": list(blueprint.source_refs),
        "model": blueprint.model_contract,
    }
    output_contract = {
        "schema": "gda.data_product_blueprint.output.v1",
        "product_urn": blueprint.product_urn,
        "storage_placement": blueprint.storage_placement,
        "projections": list(blueprint.projections),
    }
    definition = PlatformDefinitionVersion(
        tenant_id=blueprint.tenant_id,
        definition_urn=blueprint.definition_urn,
        definition_version_id=blueprint.definition_version_id,
        orchestration_class=OrchestrationClass.DATAOPS,
        capability_id="data-product-build",
        portability_class=PortabilityClass.PORTABLE,
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
        definition_sha256=platform_definition_fingerprint(
            orchestration_class=OrchestrationClass.DATAOPS,
            capability_id="data-product-build",
            portability_class=PortabilityClass.PORTABLE,
            definition_document=definition_document,
            input_contract=input_contract,
            output_contract=output_contract,
        ),
    )
    resource = Resource(
        tenant_id=blueprint.tenant_id,
        resource_urn=blueprint.definition_urn,
        resource_kind="definition",
        authority_system="gda",
        authority_locator=f"data-product-blueprint:{blueprint.product_urn}",
        owner_ref=blueprint.owner_ref,
        governance_ref={
            "schema": DATA_PRODUCT_BLUEPRINT_SCHEMA,
            "domain": blueprint.domain,
            "product_urn": blueprint.product_urn,
        },
        technical_refs=(
            {
                "schema": DATA_PRODUCT_BLUEPRINT_SCHEMA,
            },
        ),
    )
    resource_version = ResourceVersion(
        tenant_id=blueprint.tenant_id,
        resource_urn=blueprint.definition_urn,
        resource_version_id=blueprint.definition_version_id,
        version_key=blueprint.version_key,
        predecessor_version_id=blueprint.predecessor_definition_version_id,
        content_sha256=definition.definition_sha256,
        authority_version_ref={
            "schema": DATA_PRODUCT_BLUEPRINT_SCHEMA,
            "blueprint_sha256": blueprint.blueprint_sha256,
        },
        created_by=blueprint.created_by,
        created_at=blueprint.created_at,
    )
    return DefinitionRegistration(
        resource=resource,
        resource_version=resource_version,
        definition=definition,
    )


def build_data_product_blueprint_preview(
    blueprint: DataProductBlueprint,
    *,
    predecessor: PlatformDefinitionVersion | None = None,
) -> DataProductBlueprintPreview:
    """Compile without writes and produce a deterministic reviewable change set."""
    registration = compile_data_product_blueprint(blueprint)
    expected_predecessor_id = blueprint.predecessor_definition_version_id
    if expected_predecessor_id is None and predecessor is not None:
        raise ValueError("initial blueprint preview must not supply a predecessor")
    if expected_predecessor_id is not None and predecessor is None:
        raise ValueError("successor blueprint preview requires its predecessor")
    if predecessor is not None:
        if predecessor.tenant_id != blueprint.tenant_id:
            raise ValueError("predecessor definition tenant does not match blueprint")
        if predecessor.definition_urn != blueprint.definition_urn:
            raise ValueError("predecessor must belong to the same definition Resource")
        if predecessor.definition_version_id != expected_predecessor_id:
            raise ValueError("predecessor definition identity does not match blueprint")

    before = _logical_definition(predecessor) if predecessor is not None else {}
    after = _logical_definition(registration.definition)
    changes = _definition_changes(before, after)
    if not changes:
        raise ValueError("successor blueprint must change the logical definition")

    predecessor_sha256 = (
        predecessor.definition_sha256 if predecessor is not None else None
    )
    test_report = build_data_product_blueprint_test_report(
        blueprint,
        definition=registration.definition,
    )
    checks = (
        _compile_check(
            "blueprint_integrity",
            {"blueprint_sha256": blueprint.blueprint_sha256},
        ),
        _compile_check(
            "tenant_boundary",
            {
                "tenant_id": blueprint.tenant_id,
                "definition_urn": blueprint.definition_urn,
                "product_urn": blueprint.product_urn,
                "source_refs": list(blueprint.source_refs),
            },
        ),
        _compile_check(
            "definition_integrity",
            {"definition_sha256": registration.definition.definition_sha256},
        ),
        _compile_check(
            "predecessor_binding",
            {
                "predecessor_definition_version_id": expected_predecessor_id,
                "predecessor_definition_sha256": predecessor_sha256,
            },
        ),
    )
    values = {
        "tenant_id": blueprint.tenant_id,
        "product_urn": blueprint.product_urn,
        "version_key": blueprint.version_key,
        "definition_urn": blueprint.definition_urn,
        "definition_version_id": blueprint.definition_version_id,
        "predecessor_definition_version_id": expected_predecessor_id,
        "blueprint_sha256": blueprint.blueprint_sha256,
        "definition_sha256": registration.definition.definition_sha256,
        "predecessor_definition_sha256": predecessor_sha256,
        "test_checks": test_report.checks,
        "test_verdict": test_report.verdict,
        "test_report_sha256": test_report.test_report_sha256,
        "changes": changes,
        "compile_checks": checks,
        "compile_verdict": "passed",
        "review_action": DATA_PRODUCT_BLUEPRINT_REVIEW_ACTION,
        "review_target_resource_urn": blueprint.definition_urn,
    }
    change_set_sha256 = data_product_blueprint_change_set_fingerprint(values)
    return DataProductBlueprintPreview(
        **values,
        change_set_sha256=change_set_sha256,
        review_target_fingerprint=change_set_sha256,
    )


def build_data_product_blueprint_release_binding(
    preview: DataProductBlueprintPreview,
    *,
    approval_case_ref: str,
    test_execution: DataProductBlueprintTestExecution | None = None,
) -> DataProductBlueprintReleaseBinding:
    """Bind an approved preview to one immutable DataProductVersion manifest."""
    if test_execution is not None:
        if test_execution.tenant_id != preview.tenant_id:
            raise ValueError("Blueprint test execution tenant must match the preview")
        if test_execution.run.definition_version_id != preview.definition_version_id:
            raise ValueError(
                "Blueprint test execution must bind the preview definition version"
            )
    return DataProductBlueprintReleaseBinding(
        tenant_id=preview.tenant_id,
        product_urn=preview.product_urn,
        version_key=preview.version_key,
        definition_urn=preview.definition_urn,
        definition_version_id=preview.definition_version_id,
        blueprint_sha256=preview.blueprint_sha256,
        definition_sha256=preview.definition_sha256,
        change_set_sha256=preview.change_set_sha256,
        test_report_sha256=preview.test_report_sha256,
        approval_case_ref=approval_case_ref,
        test_run_id=(test_execution.run.run_id if test_execution else None),
        test_success_evidence_sha256=(
            test_execution.success_evidence.evidence_sha256
            if test_execution
            else None
        ),
    )


def build_data_product_blueprint_approval_case(
    preview: DataProductBlueprintPreview,
    *,
    requester_subject: str,
    request_reason: str,
    requested_at: datetime,
    expires_at: datetime,
) -> ApprovalCase:
    """Build one deterministic ApprovalCase for an exact definition version."""
    case_id = f"data-product-blueprint-{preview.definition_version_id.hex}"
    return ApprovalCase(
        tenant_id=preview.tenant_id,
        approval_case_ref=build_resource_urn(
            preview.tenant_id,
            "approval_case",
            case_id,
        ),
        target_resource_urn=preview.review_target_resource_urn,
        target_fingerprint=preview.review_target_fingerprint,
        action=preview.review_action,
        requester_subject=requester_subject,
        request_reason=request_reason,
        request_context=preview.approval_context(),
        requested_at=requested_at,
        expires_at=expires_at,
    )
