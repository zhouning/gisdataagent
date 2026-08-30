"""Provider-bound MMFE/GWM specialist executors for the Temporal runtime.

The Temporal workflow only carries immutable provider bindings and Artifact UUIDs.  This
module resolves those UUIDs through an injected artifact store and invokes the existing
MMFE/GWM runtime.  ``FilesystemSpecialistArtifactStore`` is deliberately bounded and is
useful for local/disposable rehearsals; production deployments should inject an adapter
backed by the PostgreSQL Artifact authority and the configured object/table provider.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import unquote, urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import model_validator

from .agentops_contracts import AgentSideEffect
from .agentops_provider_identity import derive_specialist_provider_receipt_ref
from .agentops_temporal_adapter import TemporalProviderActivityResult
from .agentops_temporal_contracts import (
    TemporalActivityOutcome,
    TemporalActivityRequest,
    TemporalProviderExecutionSpec,
    temporal_contract_fingerprint,
)
from .platform_contracts import Artifact, ArtifactRole, FrozenContract, Sha256, TenantId
from .platform_gateway import (
    GatewayConflictError,
    GatewayNotFoundError,
    GatewayWriteResult,
    PlatformGateway,
)

MMFE_PROVIDER_REF = "provider:mmfe.local"
MMFE_FUSION_OPERATION = "mmfe.execute_fusion.v1"
GWM_PROVIDER_REF = "provider:gwm.local"
GWM_RENDER_OPERATION = "gwm.render_canonical_observation.v1"


class SpecialistProviderError(RuntimeError):
    """A provider-bound specialist operation cannot be admitted or executed."""


SPECIALIST_OPERATION_RECEIPT_SCHEMA = "gda.specialist_operation_receipt.v1"
SPECIALIST_OPERATION_OBSERVATION_SCHEMA = "gda.specialist_operation_observation.v1"
SPECIALIST_ACTIVITY_RECONCILIATION_SCHEMA = "gda.specialist_activity_reconciliation.v1"
SPECIALIST_PROVIDER_CANCELLATION_OBSERVATION_SCHEMA = (
    "gda.specialist_provider_cancellation_observation.v1"
)


class SpecialistOperationStatus(StrEnum):
    """Provider-side operation state observed independently of Temporal activity state."""

    SUBMITTED = "submitted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class SpecialistProviderCancellationStatus(StrEnum):
    """Provider-native cancellation state, separate from Temporal cancellation."""

    ACCEPTED = "accepted"
    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"


class SpecialistUncertaintyType(StrEnum):
    """Stable operator-facing reason for a non-terminal provider observation."""

    FLINK_CANCELLATION_PERMISSION_DENIED = "FlinkCancellationPermissionDenied"
    FLINK_CANCELLATION_TRANSPORT_UNAVAILABLE = "FlinkCancellationTransportUnavailable"
    FLINK_JOB_NOT_FOUND = "FlinkJobNotFound"
    FLINK_CANCELLATION_REJECTED = "FlinkCancellationRejected"
    FLINK_RESPONSE_INVALID = "FlinkResponseInvalid"
    FLINK_JOB_NOT_CANCELLED = "FlinkJobNotCancelled"
    PROVIDER_CANCELLATION_ACCEPTED = "ProviderCancellationAccepted"
    PROVIDER_CANCELLATION_OBSERVATION_TIMEOUT = "ProviderCancellationObservationTimeout"
    PROVIDER_CANCELLATION_UNSUPPORTED = "ProviderCancellationUnsupported"


class SpecialistReconciliationVerdict(StrEnum):
    """Control-plane verdict after observing an uncertain provider operation."""

    MATCHED_SUCCEEDED = "matched_succeeded"
    DEFINITIVE_FAILED = "definitive_failed"
    UNKNOWN_PENDING = "unknown_pending"


class SpecialistOperationReceipt(FrozenContract):
    """Immutable provider operation receipt, separate from Temporal activity evidence."""

    schema_id = SPECIALIST_OPERATION_RECEIPT_SCHEMA
    tenant_id: TenantId
    workflow_id: str
    run_id: UUID
    step_id: UUID
    tool_call_id: UUID
    activity_id: UUID
    attempt_no: int
    request_sha256: Sha256
    provider_ref: str
    operation_ref: str
    provider_receipt_ref: str
    status: SpecialistOperationStatus
    output_artifact_id: UUID | None = None
    failure_type: str | None = None
    cancellation_requested: bool = False
    uncertainty_type: SpecialistUncertaintyType | None = None
    receipt_sha256: Sha256

    @classmethod
    def fingerprint(cls, values: dict[str, Any]) -> str:
        payload = dict(values)
        # Keep hashes of receipts written before migration 247 stable.  The field is
        # optional and a null value has no semantic meaning, so it is omitted from
        # the canonical payload when unset.
        if payload.get("uncertainty_type") is None:
            payload.pop("uncertainty_type", None)
        return temporal_contract_fingerprint(cls.schema_id, payload, "receipt_sha256")

    def model_post_init(self, __context: Any) -> None:
        expected = self.fingerprint(self.model_dump(mode="json"))
        if self.receipt_sha256 != expected:
            raise ValueError("receipt_sha256 does not match specialist operation receipt")
        if self.status is SpecialistOperationStatus.SUCCEEDED:
            if self.output_artifact_id is None or self.failure_type is not None:
                raise ValueError("successful operation receipt must bind only an output artifact")
        elif self.status in {
            SpecialistOperationStatus.FAILED,
            SpecialistOperationStatus.CANCELLED,
        }:
            if self.failure_type is None or self.output_artifact_id is not None:
                raise ValueError("failed or cancelled operation receipt is inconsistent")
        elif (
            self.status
            in {
                SpecialistOperationStatus.SUBMITTED,
                SpecialistOperationStatus.UNKNOWN,
            }
            and self.output_artifact_id is not None
        ):
            raise ValueError("pending operation receipt cannot claim an output artifact")
        if (
            self.status is not SpecialistOperationStatus.UNKNOWN
            and self.uncertainty_type is not None
        ):
            raise ValueError("uncertainty_type is only valid for unknown operation receipts")
        if self.attempt_no < 1:
            raise ValueError("operation receipt attempt_no must be positive")


class SpecialistOperationObservation(FrozenContract):
    """Read-only observation of an operation receipt used by reconciliation."""

    schema_id = SPECIALIST_OPERATION_OBSERVATION_SCHEMA
    tenant_id: TenantId
    workflow_id: str
    run_id: UUID
    step_id: UUID
    tool_call_id: UUID
    activity_id: UUID
    attempt_no: int
    request_sha256: Sha256
    provider_ref: str
    operation_ref: str
    provider_receipt_ref: str
    status: SpecialistOperationStatus
    output_artifact_id: UUID | None = None
    failure_type: str | None = None
    cancellation_requested: bool = False
    uncertainty_type: SpecialistUncertaintyType | None = None
    receipt_sha256: Sha256
    observed_at: datetime
    observation_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_observation(self) -> SpecialistOperationObservation:
        expected_receipt = SpecialistOperationReceipt.fingerprint(
            self.model_dump(mode="json", exclude={"observed_at", "observation_sha256"})
        )
        if self.receipt_sha256 != expected_receipt:
            raise ValueError("operation observation receipt hash differs from receipt")
        observation_values = self.model_dump(mode="json")
        if observation_values.get("uncertainty_type") is None:
            observation_values.pop("uncertainty_type", None)
        expected = temporal_contract_fingerprint(
            self.schema_id, observation_values, "observation_sha256"
        )
        if self.observation_sha256 != expected:
            raise ValueError("observation_sha256 does not match specialist operation observation")
        return self


class SpecialistActivityReconciliation(FrozenContract):
    """Immutable verdict for one unknown Temporal activity attempt."""

    schema_id = SPECIALIST_ACTIVITY_RECONCILIATION_SCHEMA
    tenant_id: TenantId
    workflow_id: str
    run_id: UUID
    activity_id: UUID
    tool_call_id: UUID
    attempt_no: int
    request_sha256: Sha256
    provider_operation_ref: str
    provider_receipt_ref: str
    observed_status: SpecialistOperationStatus
    verdict: SpecialistReconciliationVerdict
    output_artifact_id: UUID | None = None
    failure_type: str | None = None
    observation_sha256: Sha256 | None = None
    reconciliation_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_reconciliation(self) -> SpecialistActivityReconciliation:
        if self.verdict is SpecialistReconciliationVerdict.MATCHED_SUCCEEDED:
            if self.output_artifact_id is None or self.failure_type is not None:
                raise ValueError("matched success reconciliation requires an output artifact")
        elif self.verdict is SpecialistReconciliationVerdict.DEFINITIVE_FAILED:
            if self.failure_type is None or self.output_artifact_id is not None:
                raise ValueError("failed reconciliation requires a failure type only")
        elif self.verdict is SpecialistReconciliationVerdict.UNKNOWN_PENDING:
            if self.output_artifact_id is not None or self.failure_type is not None:
                raise ValueError("unknown pending reconciliation cannot claim a terminal result")
        expected = temporal_contract_fingerprint(
            self.schema_id, self.model_dump(mode="json"), "reconciliation_sha256"
        )
        if self.reconciliation_sha256 != expected:
            raise ValueError("reconciliation_sha256 does not match specialist reconciliation")
        return self


class SpecialistProviderCancellationObservation(FrozenContract):
    """Immutable observation returned by a provider cancellation adapter."""

    schema_id = SPECIALIST_PROVIDER_CANCELLATION_OBSERVATION_SCHEMA
    tenant_id: TenantId
    workflow_id: str
    run_id: UUID
    step_id: UUID
    tool_call_id: UUID
    activity_id: UUID
    attempt_no: int
    request_sha256: Sha256
    provider_ref: str
    operation_ref: str
    provider_receipt_ref: str
    status: SpecialistProviderCancellationStatus
    failure_type: str | None = None
    uncertainty_type: SpecialistUncertaintyType | None = None
    observed_at: datetime
    observation_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_observation(self) -> SpecialistProviderCancellationObservation:
        if self.status is SpecialistProviderCancellationStatus.CONFIRMED:
            if not self.failure_type:
                raise ValueError("confirmed provider cancellation requires failure_type")
            if self.uncertainty_type is not None:
                raise ValueError("confirmed provider cancellation cannot carry uncertainty_type")
        elif self.failure_type is not None:
            raise ValueError("only confirmed provider cancellation can carry failure_type")
        if self.attempt_no < 1:
            raise ValueError("provider cancellation attempt_no must be positive")
        observation_values = self.model_dump(mode="json")
        if observation_values.get("uncertainty_type") is None:
            observation_values.pop("uncertainty_type", None)
        expected = temporal_contract_fingerprint(
            self.schema_id, observation_values, "observation_sha256"
        )
        if self.observation_sha256 != expected:
            raise ValueError(
                "provider cancellation observation_sha256 does not match observation"
            )
        return self


class SpecialistOperationAuthority(Protocol):
    """Provider receipt authority used by the bounded executor and reconciler."""

    def observe(self, operation_ref: str) -> SpecialistOperationObservation | None: ...

    def submit(
        self,
        request: TemporalActivityRequest,
        *,
        provider_ref: str,
        operation_ref: str,
        provider_receipt_ref: str,
    ) -> SpecialistOperationReceipt: ...

    def succeed(
        self, operation_ref: str, output_artifact_id: UUID
    ) -> SpecialistOperationReceipt: ...

    def fail(self, operation_ref: str, failure_type: str) -> SpecialistOperationReceipt: ...

    def cancel(
        self, operation_ref: str, failure_type: str = "ProviderCancelled"
    ) -> SpecialistOperationReceipt: ...

    def request_cancellation(
        self,
        operation_ref: str,
        uncertainty_type: SpecialistUncertaintyType | None = None,
    ) -> SpecialistOperationReceipt: ...


class SpecialistProviderCancellationAdapter(Protocol):
    """Provider-native cancellation boundary used by a Temporal activity worker.

    Implementations call the provider's own cancel/abort endpoint or cooperative
    cancellation primitive. They must return ``accepted``/``unknown`` until the
    provider itself reports a terminal cancellation; Temporal history is not enough.
    """

    def request_cancellation(
        self,
        request: TemporalActivityRequest,
        *,
        operation_ref: str,
        provider_receipt_ref: str,
    ) -> SpecialistProviderCancellationObservation: ...

    def observe_cancellation(
        self,
        request: TemporalActivityRequest,
        *,
        operation_ref: str,
        provider_receipt_ref: str,
    ) -> SpecialistProviderCancellationObservation | None: ...


def _provider_cancellation_observation(
    request: TemporalActivityRequest,
    *,
    operation_ref: str,
    provider_receipt_ref: str,
    status: SpecialistProviderCancellationStatus,
    failure_type: str | None = None,
    uncertainty_type: SpecialistUncertaintyType | None = None,
) -> SpecialistProviderCancellationObservation:
    spec = request.provider_spec
    if spec is None:
        raise SpecialistProviderError("provider cancellation requires a provider binding")
    values: dict[str, Any] = {
        "tenant_id": request.tenant_id,
        "workflow_id": request.workflow_id,
        "run_id": request.run_id,
        "step_id": request.step_id,
        "tool_call_id": request.tool_call_id,
        "activity_id": request.activity_id,
        "attempt_no": request.attempt_no,
        "request_sha256": request.request_sha256,
        "provider_ref": spec.provider_ref,
        "operation_ref": operation_ref,
        "provider_receipt_ref": provider_receipt_ref,
        "status": status,
        "failure_type": failure_type,
        "uncertainty_type": uncertainty_type,
        "observed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    fingerprint_values = dict(values)
    if fingerprint_values.get("uncertainty_type") is None:
        fingerprint_values.pop("uncertainty_type", None)
    values["observation_sha256"] = temporal_contract_fingerprint(
        SPECIALIST_PROVIDER_CANCELLATION_OBSERVATION_SCHEMA,
        fingerprint_values,
        "observation_sha256",
    )
    return SpecialistProviderCancellationObservation(**values)


class UnsupportedSpecialistCancellationAdapter:
    """Explicit fail-closed adapter for providers without a cancellation API."""

    def request_cancellation(
        self,
        request: TemporalActivityRequest,
        *,
        operation_ref: str,
        provider_receipt_ref: str,
    ) -> SpecialistProviderCancellationObservation:
        return _provider_cancellation_observation(
            request,
            operation_ref=operation_ref,
            provider_receipt_ref=provider_receipt_ref,
            status=SpecialistProviderCancellationStatus.UNSUPPORTED,
            uncertainty_type=SpecialistUncertaintyType.PROVIDER_CANCELLATION_UNSUPPORTED,
        )

    def observe_cancellation(
        self,
        request: TemporalActivityRequest,
        *,
        operation_ref: str,
        provider_receipt_ref: str,
    ) -> SpecialistProviderCancellationObservation | None:
        return None


class InMemorySpecialistCancellationAdapter:
    """Deterministic adapter for cancellation contract tests and rehearsals only."""

    def __init__(self, *, confirm_on_request: bool = False) -> None:
        self.confirm_on_request = confirm_on_request
        self._observations: dict[str, SpecialistProviderCancellationObservation] = {}

    def request_cancellation(
        self,
        request: TemporalActivityRequest,
        *,
        operation_ref: str,
        provider_receipt_ref: str,
    ) -> SpecialistProviderCancellationObservation:
        existing = self._observations.get(operation_ref)
        if existing is not None:
            if (
                existing.request_sha256 != request.request_sha256
                or existing.provider_receipt_ref != provider_receipt_ref
            ):
                raise SpecialistProviderError(
                    "provider cancellation operation identity is already bound differently"
                )
            return existing
        status = (
            SpecialistProviderCancellationStatus.CONFIRMED
            if self.confirm_on_request
            else SpecialistProviderCancellationStatus.ACCEPTED
        )
        observation = _provider_cancellation_observation(
            request,
            operation_ref=operation_ref,
            provider_receipt_ref=provider_receipt_ref,
            status=status,
            failure_type=(
                "ProviderCancellationConfirmed"
                if status is SpecialistProviderCancellationStatus.CONFIRMED
                else None
            ),
            uncertainty_type=(
                None
                if status is SpecialistProviderCancellationStatus.CONFIRMED
                else SpecialistUncertaintyType.PROVIDER_CANCELLATION_ACCEPTED
            ),
        )
        self._observations[operation_ref] = observation
        return observation

    def observe_cancellation(
        self,
        request: TemporalActivityRequest,
        *,
        operation_ref: str,
        provider_receipt_ref: str,
    ) -> SpecialistProviderCancellationObservation | None:
        observation = self._observations.get(operation_ref)
        if observation is not None and (
            observation.request_sha256 != request.request_sha256
            or observation.provider_receipt_ref != provider_receipt_ref
        ):
            raise SpecialistProviderError(
                "provider cancellation observation differs from request"
            )
        return observation

    def confirm(
        self,
        request: TemporalActivityRequest,
        *,
        operation_ref: str,
        provider_receipt_ref: str,
        failure_type: str = "ProviderCancellationConfirmed",
    ) -> SpecialistProviderCancellationObservation:
        observation = _provider_cancellation_observation(
            request,
            operation_ref=operation_ref,
            provider_receipt_ref=provider_receipt_ref,
            status=SpecialistProviderCancellationStatus.CONFIRMED,
            failure_type=failure_type,
        )
        self._observations[operation_ref] = observation
        return observation


class InMemorySpecialistOperationAuthority:
    """Append-only bounded receipt authority for local/provider contract rehearsals."""

    def __init__(self) -> None:
        self._receipts: dict[str, SpecialistOperationReceipt] = {}
        self.history: list[SpecialistOperationReceipt] = []

    def submit(
        self,
        request: TemporalActivityRequest,
        *,
        provider_ref: str,
        operation_ref: str,
        provider_receipt_ref: str,
    ) -> SpecialistOperationReceipt:
        values: dict[str, Any] = {
            "tenant_id": request.tenant_id,
            "workflow_id": request.workflow_id,
            "run_id": request.run_id,
            "step_id": request.step_id,
            "tool_call_id": request.tool_call_id,
            "activity_id": request.activity_id,
            "attempt_no": request.attempt_no,
            "request_sha256": request.request_sha256,
            "provider_ref": provider_ref,
            "operation_ref": operation_ref,
            "provider_receipt_ref": provider_receipt_ref,
            "status": SpecialistOperationStatus.SUBMITTED,
            "output_artifact_id": None,
            "failure_type": None,
            "cancellation_requested": False,
        }
        values["receipt_sha256"] = SpecialistOperationReceipt.fingerprint(values)
        candidate = SpecialistOperationReceipt(**values)
        existing = self._receipts.get(operation_ref)
        if existing is not None:
            if existing != candidate and not self._same_identity(existing, candidate):
                raise SpecialistProviderError(
                    "provider operation identity is already bound differently"
                )
            return existing
        self._receipts[operation_ref] = candidate
        self.history.append(candidate)
        return candidate

    def succeed(self, operation_ref: str, output_artifact_id: UUID) -> SpecialistOperationReceipt:
        return self._transition(
            operation_ref,
            SpecialistOperationStatus.SUCCEEDED,
            output_artifact_id=output_artifact_id,
        )

    def fail(self, operation_ref: str, failure_type: str) -> SpecialistOperationReceipt:
        return self._transition(
            operation_ref,
            SpecialistOperationStatus.FAILED,
            failure_type=failure_type,
        )

    def cancel(
        self, operation_ref: str, failure_type: str = "ProviderCancelled"
    ) -> SpecialistOperationReceipt:
        return self._transition(
            operation_ref,
            SpecialistOperationStatus.CANCELLED,
            failure_type=failure_type,
        )

    def request_cancellation(
        self,
        operation_ref: str,
        uncertainty_type: SpecialistUncertaintyType | None = None,
    ) -> SpecialistOperationReceipt:
        return self._transition(
            operation_ref,
            SpecialistOperationStatus.UNKNOWN,
            cancellation_requested=True,
            uncertainty_type=uncertainty_type,
        )

    def observe(self, operation_ref: str) -> SpecialistOperationObservation | None:
        receipt = self._receipts.get(operation_ref)
        if receipt is None:
            return None
        values = receipt.model_dump(mode="json")
        values["observed_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        observation_values = dict(values)
        if observation_values.get("uncertainty_type") is None:
            observation_values.pop("uncertainty_type", None)
        values["observation_sha256"] = temporal_contract_fingerprint(
            SPECIALIST_OPERATION_OBSERVATION_SCHEMA, observation_values, "observation_sha256"
        )
        return SpecialistOperationObservation(**values)

    @staticmethod
    def _same_identity(left: SpecialistOperationReceipt, right: SpecialistOperationReceipt) -> bool:
        return (
            left.tenant_id == right.tenant_id
            and left.workflow_id == right.workflow_id
            and left.run_id == right.run_id
            and left.step_id == right.step_id
            and left.tool_call_id == right.tool_call_id
            and left.activity_id == right.activity_id
            and left.attempt_no == right.attempt_no
            and left.request_sha256 == right.request_sha256
            and left.provider_ref == right.provider_ref
            and left.provider_receipt_ref == right.provider_receipt_ref
        )

    def _transition(
        self,
        operation_ref: str,
        status: SpecialistOperationStatus,
        *,
        output_artifact_id: UUID | None = None,
        failure_type: str | None = None,
        cancellation_requested: bool | None = None,
        uncertainty_type: SpecialistUncertaintyType | None = None,
    ) -> SpecialistOperationReceipt:
        current = self._receipts.get(operation_ref)
        if current is None:
            raise SpecialistProviderError("provider operation receipt is not registered")
        if current.status in {
            SpecialistOperationStatus.SUCCEEDED,
            SpecialistOperationStatus.FAILED,
            SpecialistOperationStatus.CANCELLED,
        }:
            if (
                current.status is not status
                or current.output_artifact_id != output_artifact_id
                or current.failure_type != failure_type
            ):
                raise SpecialistProviderError("provider operation terminal receipt conflicts")
            return current
        values = current.model_dump(mode="python")
        values.update(
            {
                "status": status,
                "output_artifact_id": output_artifact_id,
                "failure_type": failure_type,
                "uncertainty_type": (
                    None
                    if status
                    in {
                        SpecialistOperationStatus.SUCCEEDED,
                        SpecialistOperationStatus.FAILED,
                        SpecialistOperationStatus.CANCELLED,
                    }
                    else (
                        current.uncertainty_type
                        if uncertainty_type is None
                        else uncertainty_type
                    )
                ),
                "cancellation_requested": (
                    current.cancellation_requested
                    if cancellation_requested is None
                    else cancellation_requested
                ),
            }
        )
        values["receipt_sha256"] = SpecialistOperationReceipt.fingerprint(values)
        updated = SpecialistOperationReceipt(**values)
        self._receipts[operation_ref] = updated
        self.history.append(updated)
        return updated


def _write_operation_receipt_artifact(
    artifact_store: SpecialistArtifactStore,
    receipt: SpecialistOperationReceipt | SpecialistOperationObservation,
) -> LocalArtifact:
    values = receipt.model_dump(mode="json")
    if isinstance(receipt, SpecialistOperationObservation):
        values.pop("observed_at", None)
        values.pop("observation_sha256", None)
    content = json.dumps(values, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    artifact_id = uuid5(
        NAMESPACE_URL,
        f"gda-specialist-operation-receipt:{receipt.tenant_id}:{receipt.receipt_sha256}",
    )
    manifest = {
        "schema": "gda.specialist_operation_receipt_artifact_manifest.v1",
        "provider_ref": receipt.provider_ref,
        "operation_ref": receipt.operation_ref,
        "request_sha256": receipt.request_sha256,
        "receipt_sha256": receipt.receipt_sha256,
        "operation_status": receipt.status.value,
        "content_sha256": _sha256(content),
    }
    return artifact_store.write_output(
        tenant_id=receipt.tenant_id,
        artifact_id=artifact_id,
        content=content,
        media_type="application/json",
        manifest=manifest,
        run_id=receipt.run_id,
        artifact_key=f"agentops-operation-receipt-{receipt.receipt_sha256[:24]}",
        created_by=f"workload:agentops:{receipt.provider_ref}",
        artifact_role=ArtifactRole.EVIDENCE,
    )


@dataclass(frozen=True)
class LocalArtifact:
    """Resolved artifact metadata used by the bounded local provider store."""

    tenant_id: str
    artifact_id: UUID
    storage_path: Path
    media_type: str
    content_sha256: str
    manifest: dict[str, Any]


class SpecialistArtifactStore(Protocol):
    """Minimal artifact authority surface required by a specialist provider."""

    def resolve_input(self, tenant_id: str, artifact_id: UUID) -> LocalArtifact: ...

    def write_output(
        self,
        *,
        tenant_id: str,
        artifact_id: UUID,
        content: bytes,
        media_type: str,
        manifest: dict[str, Any],
        run_id: UUID | None = None,
        artifact_key: str | None = None,
        created_by: str | None = None,
        artifact_role: ArtifactRole = ArtifactRole.OUTPUT,
    ) -> LocalArtifact: ...


class ArtifactContentBackend(Protocol):
    """Content plane used by the PostgreSQL Artifact authority adapter.

    The control plane stores only a stable URI, media type, checksum and manifest;
    this backend is responsible for bytes.  Implementations must make writes
    idempotent for a stable URI and must never put credentials in the URI.
    """

    def uri_for(self, *, tenant_id: str, artifact_id: UUID, media_type: str) -> str: ...

    def read(self, artifact: Artifact) -> bytes: ...

    def write(self, *, storage_uri: str, content: bytes, media_type: str) -> dict[str, Any]: ...


class FilesystemArtifactContentBackend:
    """Filesystem content backend for a bounded PostgreSQL-authority rehearsal."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, path: Path) -> Path:
        resolved = path.expanduser().resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise SpecialistProviderError("artifact path escapes content backend root") from exc
        return resolved

    def uri_for(self, *, tenant_id: str, artifact_id: UUID, media_type: str) -> str:
        tenant = tenant_id.strip()
        if not tenant or any(
            char not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for char in tenant
        ):
            raise SpecialistProviderError("artifact tenant is invalid for filesystem backend")
        path = self._safe_path(
            self.root / tenant / f"{artifact_id}{_extension_for_media_type(media_type)}"
        )
        return path.as_uri()

    def read(self, artifact: Artifact) -> bytes:
        parsed = urlsplit(artifact.storage_uri)
        if parsed.scheme != "file" or parsed.netloc:
            raise SpecialistProviderError("filesystem backend only accepts absolute file URI")
        path = self._safe_path(Path(unquote(parsed.path)))
        if not path.is_file():
            raise SpecialistProviderError(f"artifact content is missing: {path}")
        return path.read_bytes()

    def write(self, *, storage_uri: str, content: bytes, media_type: str) -> dict[str, Any]:
        parsed = urlsplit(storage_uri)
        if parsed.scheme != "file" or parsed.netloc:
            raise SpecialistProviderError("filesystem backend only accepts absolute file URI")
        target = self._safe_path(Path(unquote(parsed.path)))
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != content:
                raise SpecialistProviderError("content URI is already bound to different bytes")
            return {}
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        temporary.write_bytes(content)
        os.replace(temporary, target)
        return {}


class S3ArtifactContentBackend:
    """S3/MinIO content backend with optional immutable VersionId reads.

    The client is injected so tests and deployments can use boto3, MinIO-compatible
    endpoints, or a credential-scoped adapter without changing the authority. Live
    specialist workers can additionally require a read-only Object Lock/default
    retention probe before they begin reconciliation.
    """

    def __init__(
        self,
        client: Any,
        *,
        bucket: str,
        prefix: str = "agentops-specialist/v1",
        require_version_id: bool = False,
        require_object_lock_retention: bool = False,
    ) -> None:
        if not bucket or "/" in bucket:
            raise SpecialistProviderError("S3 bucket is invalid")
        normalized_prefix = prefix.strip("/")
        if not normalized_prefix:
            raise SpecialistProviderError("S3 prefix is required")
        self.client = client
        self.bucket = bucket
        self.prefix = normalized_prefix
        self.require_version_id = require_version_id
        self.require_object_lock_retention = require_object_lock_retention

    def uri_for(self, *, tenant_id: str, artifact_id: UUID, media_type: str) -> str:
        tenant = tenant_id.strip()
        if not tenant or any(
            char not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for char in tenant
        ):
            raise SpecialistProviderError("artifact tenant is invalid for S3 backend")
        key = f"{self.prefix}/{tenant}/{artifact_id}{_extension_for_media_type(media_type)}"
        return f"s3://{self.bucket}/{key}"

    @staticmethod
    def _location(storage_uri: str) -> tuple[str, str]:
        parsed = urlsplit(storage_uri)
        if parsed.scheme not in {"s3", "obs"} or not parsed.netloc or not parsed.path.strip("/"):
            raise SpecialistProviderError("S3 backend requires s3://bucket/key URI")
        return parsed.netloc, parsed.path.lstrip("/")

    @staticmethod
    def _version_id(artifact: Artifact) -> str | None:
        storage = artifact.manifest.get("storage")
        if isinstance(storage, dict) and storage.get("version_id"):
            return str(storage["version_id"])
        if artifact.manifest.get("version_id"):
            return str(artifact.manifest["version_id"])
        return None

    def read(self, artifact: Artifact) -> bytes:
        bucket, key = self._location(artifact.storage_uri)
        version_id = self._version_id(artifact)
        if self.require_version_id and not version_id:
            raise SpecialistProviderError("S3 Artifact must bind an immutable VersionId")
        kwargs: dict[str, Any] = {"Bucket": bucket, "Key": key}
        if version_id:
            kwargs["VersionId"] = version_id
        try:
            return self.client.get_object(**kwargs)["Body"].read()
        except Exception as exc:
            raise SpecialistProviderError("S3 artifact content read failed") from exc

    def probe(self) -> dict[str, Any]:
        """Verify the bucket contract before a worker starts polling.

        Versioned reads protect Artifact identity.  Production specialist workers
        additionally require Object Lock with a positive default retention so a
        later worker, operator, or cleanup job cannot silently remove the exact
        bytes that a receipt points at.  The probe is deliberately read-only and
        fails closed when the provider does not expose the required controls.
        """

        try:
            versioning = self.client.get_bucket_versioning(Bucket=self.bucket)
        except Exception as exc:
            raise SpecialistProviderError(
                "specialist S3 bucket versioning could not be verified"
            ) from exc
        if (versioning or {}).get("Status") != "Enabled":
            raise SpecialistProviderError(
                "specialist S3 bucket must have versioning enabled"
            )
        result: dict[str, Any] = {"versioning": "Enabled"}
        if not self.require_object_lock_retention:
            return result
        try:
            response = self.client.get_object_lock_configuration(Bucket=self.bucket)
        except Exception as exc:
            raise SpecialistProviderError(
                "specialist S3 object lock configuration could not be verified"
            ) from exc
        configuration = (response or {}).get("ObjectLockConfiguration") or response or {}
        retention = (configuration.get("Rule") or {}).get("DefaultRetention") or {}
        duration = retention.get("Days") or retention.get("Years")
        if configuration.get("ObjectLockEnabled") != "Enabled":
            raise SpecialistProviderError(
                "specialist S3 bucket must have object lock enabled"
            )
        if (
            retention.get("Mode") not in {"GOVERNANCE", "COMPLIANCE"}
            or not isinstance(duration, int)
            or isinstance(duration, bool)
            or duration <= 0
        ):
            raise SpecialistProviderError(
                "specialist S3 bucket must have positive default object lock retention"
            )
        result.update(
            {
                "object_lock": "Enabled",
                "retention_mode": retention["Mode"],
                "retention_unit": "Days" if retention.get("Days") else "Years",
                "retention_duration": duration,
            }
        )
        return result

    def write(self, *, storage_uri: str, content: bytes, media_type: str) -> dict[str, Any]:
        bucket, key = self._location(storage_uri)
        try:
            response = self.client.put_object(
                Bucket=bucket,
                Key=key,
                Body=content,
                ContentType=media_type,
            )
        except Exception as exc:
            raise SpecialistProviderError("S3 artifact content write failed") from exc
        version_id = response.get("VersionId") if isinstance(response, dict) else None
        return {"version_id": version_id} if version_id else {}


class PostgresArtifactAuthoritySpecialistStore:
    """Specialist store backed by PostgreSQL Artifact authority plus a content backend.

    PostgreSQL is authoritative for tenant, identity, media type, checksum and
    lineage manifest.  The content backend is deliberately injected; this keeps the
    provider contract stable while allowing a disposable filesystem rehearsal and a
    MinIO/S3 deployment to share the same adapter.
    """

    def __init__(
        self,
        tenant_id: str,
        *,
        gateway: PlatformGateway,
        content_backend: ArtifactContentBackend,
        materialization_root: str | Path,
    ) -> None:
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise SpecialistProviderError("artifact authority tenant is required")
        self.tenant_id = tenant_id.strip()
        self.gateway = gateway
        self.content_backend = content_backend
        self.materialization_root = Path(materialization_root).expanduser().resolve()
        self.materialization_root.mkdir(parents=True, exist_ok=True)

    def _materialize(self, artifact: Artifact, content: bytes) -> LocalArtifact:
        digest = _sha256(content)
        if digest != artifact.content_sha256:
            raise SpecialistProviderError(
                f"artifact {artifact.artifact_id} content checksum does not match authority"
            )
        target = (
            self.materialization_root
            / artifact.tenant_id
            / (f"{artifact.artifact_id}{_extension_for_media_type(artifact.media_type)}")
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() != content:
            raise SpecialistProviderError("materialized artifact path is bound to different bytes")
        if not target.exists():
            temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
            temporary.write_bytes(content)
            os.replace(temporary, target)
        return LocalArtifact(
            tenant_id=artifact.tenant_id,
            artifact_id=artifact.artifact_id,
            storage_path=target,
            media_type=artifact.media_type,
            content_sha256=artifact.content_sha256,
            manifest=dict(artifact.manifest),
        )

    def resolve_input(self, tenant_id: str, artifact_id: UUID) -> LocalArtifact:
        if tenant_id != self.tenant_id:
            raise SpecialistProviderError("artifact tenant differs from authority tenant")
        try:
            artifact = self.gateway.get_artifact(tenant_id, artifact_id)
        except GatewayNotFoundError as exc:
            raise SpecialistProviderError(
                f"artifact {artifact_id} was not found in authority"
            ) from exc
        except Exception as exc:
            raise SpecialistProviderError("artifact authority read failed") from exc
        try:
            content = self.content_backend.read(artifact)
        except SpecialistProviderError:
            raise
        except Exception as exc:
            raise SpecialistProviderError("artifact content read failed") from exc
        return self._materialize(artifact, content)

    def write_output(
        self,
        *,
        tenant_id: str,
        artifact_id: UUID,
        content: bytes,
        media_type: str,
        manifest: dict[str, Any],
        run_id: UUID | None = None,
        artifact_key: str | None = None,
        created_by: str | None = None,
        artifact_role: ArtifactRole = ArtifactRole.OUTPUT,
    ) -> LocalArtifact:
        if tenant_id != self.tenant_id:
            raise SpecialistProviderError("artifact tenant differs from authority tenant")
        digest = _sha256(content)
        provider_manifest = dict(manifest)
        provider_manifest.pop("storage", None)
        try:
            existing = self.gateway.get_artifact(tenant_id, artifact_id)
        except GatewayNotFoundError:
            existing = None
        except Exception as exc:
            raise SpecialistProviderError("artifact authority read failed") from exc
        if existing is not None:
            existing_provider_manifest = dict(existing.manifest)
            existing_provider_manifest.pop("storage", None)
            if (
                existing.content_sha256 != digest
                or existing.media_type != media_type
                or existing.artifact_role is not artifact_role
                or existing_provider_manifest != provider_manifest
            ):
                raise SpecialistProviderError(
                    "output Artifact identity is already bound to different content"
                )
            return self._materialize(existing, self.content_backend.read(existing))

        storage_uri = self.content_backend.uri_for(
            tenant_id=tenant_id, artifact_id=artifact_id, media_type=media_type
        )
        storage_metadata = self.content_backend.write(
            storage_uri=storage_uri, content=content, media_type=media_type
        )
        authority_manifest = dict(provider_manifest)
        if storage_metadata:
            authority_manifest["storage"] = dict(storage_metadata)
        artifact = Artifact(
            tenant_id=tenant_id,
            artifact_id=artifact_id,
            artifact_key=artifact_key or f"agentops-specialist-{artifact_id.hex[:24]}",
            artifact_role=artifact_role,
            storage_uri=storage_uri,
            media_type=media_type,
            content_sha256=digest,
            size_bytes=len(content),
            run_id=run_id,
            resource_version_id=None,
            manifest=authority_manifest,
            created_by=created_by or "workload:agentops-specialist",
            created_at=datetime.now(UTC),
        )
        try:
            written: GatewayWriteResult = self.gateway.record_artifact(artifact)
            stored = written.value
        except GatewayConflictError:
            try:
                stored = self.gateway.get_artifact(tenant_id, artifact_id)
            except Exception as exc:
                raise SpecialistProviderError(
                    "output Artifact conflict could not be reconciled"
                ) from exc
            if stored is None:
                raise SpecialistProviderError(
                    "output Artifact disappeared after conflict"
                ) from None
        except Exception as exc:
            raise SpecialistProviderError("artifact authority write failed") from exc
        if not isinstance(stored, Artifact):
            raise SpecialistProviderError("artifact authority returned an invalid Artifact")
        if (
            stored.content_sha256 != digest
            or stored.media_type != media_type
            or stored.artifact_role is not artifact_role
            or stored.manifest != authority_manifest
        ):
            raise SpecialistProviderError("artifact authority returned a different output Artifact")
        return self._materialize(stored, self.content_backend.read(stored))


class FilesystemSpecialistArtifactStore:
    """Content-addressed local store for disposable provider rehearsals.

    Inputs are explicitly registered by UUID. Outputs use a deterministic UUID/path and
    are idempotent: replaying the same activity verifies the bytes and reuses the output.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.input_root = self.root / "inputs"
        self.output_root = self.root / "outputs"
        self.input_root.mkdir(parents=True, exist_ok=True)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self._artifacts: dict[tuple[str, UUID], LocalArtifact] = {}

    def register_input(
        self,
        *,
        tenant_id: str,
        artifact_id: UUID,
        source_path: str | Path,
        media_type: str,
        manifest: dict[str, Any] | None = None,
    ) -> LocalArtifact:
        source = Path(source_path).expanduser().resolve()
        if not source.is_file():
            raise SpecialistProviderError(f"input artifact path is not a file: {source}")
        content = source.read_bytes()
        target = self.input_root / f"{artifact_id}{source.suffix}"
        if target.exists() and target.read_bytes() != content:
            raise SpecialistProviderError("input artifact UUID is already bound to different bytes")
        if not target.exists():
            shutil.copyfile(source, target)
        artifact = LocalArtifact(
            tenant_id=tenant_id,
            artifact_id=artifact_id,
            storage_path=target,
            media_type=media_type,
            content_sha256=_sha256(content),
            manifest=dict(manifest or {}),
        )
        self._artifacts[(tenant_id, artifact_id)] = artifact
        return artifact

    def resolve_input(self, tenant_id: str, artifact_id: UUID) -> LocalArtifact:
        try:
            return self._artifacts[(tenant_id, artifact_id)]
        except KeyError:
            # A replacement worker may receive the same filesystem-backed content
            # directory with a fresh process-local index. Rehydrate only an output
            # whose immutable manifest and bytes already exist; the database-backed
            # store remains the production recovery path.
            matches = tuple(
                path
                for path in self.output_root.glob(f"{artifact_id}.*")
                if not path.name.endswith(".manifest.json") and path.is_file()
            )
            if len(matches) != 1:
                raise SpecialistProviderError(
                    f"artifact {artifact_id} is not available in the injected artifact authority"
                ) from None
            content_path = matches[0]
            manifest_path = content_path.with_suffix(".manifest.json")
            if not manifest_path.is_file():
                raise SpecialistProviderError(
                    f"artifact {artifact_id} is missing its immutable output manifest"
                ) from None
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise SpecialistProviderError(
                    f"artifact {artifact_id} output manifest is invalid"
                ) from exc
            media_type = (
                "application/json"
                if content_path.suffix == ".json"
                else "application/geo+json"
            )
            artifact = LocalArtifact(
                tenant_id=tenant_id,
                artifact_id=artifact_id,
                storage_path=content_path,
                media_type=media_type,
                content_sha256=_sha256(content_path.read_bytes()),
                manifest=manifest,
            )
            self._artifacts[(tenant_id, artifact_id)] = artifact
            return artifact

    def write_output(
        self,
        *,
        tenant_id: str,
        artifact_id: UUID,
        content: bytes,
        media_type: str,
        manifest: dict[str, Any],
        run_id: UUID | None = None,
        artifact_key: str | None = None,
        created_by: str | None = None,
        artifact_role: ArtifactRole = ArtifactRole.OUTPUT,
    ) -> LocalArtifact:
        target = self.output_root / f"{artifact_id}{_extension_for_media_type(media_type)}"
        digest = _sha256(content)
        existing = self._artifacts.get((tenant_id, artifact_id))
        if existing is not None:
            if existing.content_sha256 != digest or existing.storage_path.read_bytes() != content:
                raise SpecialistProviderError(
                    "output artifact UUID is already bound to different bytes"
                )
            return existing
        target.write_bytes(content)
        manifest_path = target.with_suffix(".manifest.json")
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        artifact = LocalArtifact(
            tenant_id=tenant_id,
            artifact_id=artifact_id,
            storage_path=target,
            media_type=media_type,
            content_sha256=digest,
            manifest=dict(manifest),
        )
        self._artifacts[(tenant_id, artifact_id)] = artifact
        return artifact


def build_mmfe_provider_spec(
    *,
    input_artifact_ids: tuple[UUID, ...] = (),
    strategy: str = "auto",
    params: dict[str, Any] | None = None,
    semantic_config: dict[str, Any] | None = None,
) -> TemporalProviderExecutionSpec:
    """Build a hash-bound MMFE execution binding."""

    values: dict[str, Any] = {
        "provider_ref": MMFE_PROVIDER_REF,
        "operation_ref": MMFE_FUSION_OPERATION,
        "parameters": {
            "strategy": strategy,
            "params": dict(params or {}),
            "semantic_config": dict(semantic_config or {}),
        },
        "input_artifact_ids": tuple(sorted(input_artifact_ids, key=str)),
        "output_media_type": "application/geo+json",
    }
    values["spec_sha256"] = temporal_contract_fingerprint(
        TemporalProviderExecutionSpec.schema_id, values, "spec_sha256"
    )
    return TemporalProviderExecutionSpec(**values)


def build_gwm_provider_spec(
    *, input_artifact_ids: tuple[UUID, ...] = (), observation_id: str | None = None
) -> TemporalProviderExecutionSpec:
    """Build a hash-bound read-only GWM observation rendering binding."""

    values: dict[str, Any] = {
        "provider_ref": GWM_PROVIDER_REF,
        "operation_ref": GWM_RENDER_OPERATION,
        "parameters": {"observation_id": observation_id} if observation_id else {},
        "input_artifact_ids": tuple(sorted(input_artifact_ids, key=str)),
        "output_media_type": "application/json",
    }
    values["spec_sha256"] = temporal_contract_fingerprint(
        TemporalProviderExecutionSpec.schema_id, values, "spec_sha256"
    )
    return TemporalProviderExecutionSpec(**values)


class BoundSpecialistExecutor:
    """Async Temporal activity executor for the bounded MMFE/GWM provider slice."""

    def __init__(
        self,
        artifact_store: SpecialistArtifactStore,
        *,
        operation_authority: SpecialistOperationAuthority | None = None,
        retry_budget_authority: Any | None = None,
        retry_budget_max_attempts: int = 3,
        worker_id: str = "workload:agentops-specialist",
        cancellation_adapter: SpecialistProviderCancellationAdapter | None = None,
        unknown_after_commit: bool = False,
        cancellation_timeout_before_execution: bool = False,
    ) -> None:
        self._artifact_store = artifact_store
        self._operation_authority = operation_authority
        self._retry_budget_authority = retry_budget_authority
        self._retry_budget_max_attempts = retry_budget_max_attempts
        self._worker_id = worker_id
        self._cancellation_adapter = (
            cancellation_adapter or UnsupportedSpecialistCancellationAdapter()
        )
        # These switches are deliberately bounded fault-injection controls. They model
        # transport loss after a provider commit and cancellation timeout before the
        # provider can return a definitive result; production callers leave them false.
        self._unknown_after_commit = unknown_after_commit
        self._cancellation_timeout_before_execution = cancellation_timeout_before_execution

    async def __call__(self, request: TemporalActivityRequest) -> TemporalProviderActivityResult:
        try:
            return await asyncio.to_thread(self._execute, request)
        except asyncio.CancelledError:
            # Temporal cancellation is an observation at this boundary. Ask the provider
            # to cancel, but let Temporal record the cancellation; reconciliation owns the
            # eventual terminal result when the provider has not confirmed it yet.
            await asyncio.to_thread(self._request_provider_cancellation, request)
            raise

    def _request_provider_cancellation(self, request: TemporalActivityRequest) -> None:
        spec = request.provider_spec
        if spec is None or self._operation_authority is None:
            return
        operation_ref = f"{spec.operation_ref}://{request.activity_id}"
        receipt_ref = derive_specialist_provider_receipt_ref(request)
        existing = self._operation_authority.observe(operation_ref)
        if existing is None or existing.status in {
            SpecialistOperationStatus.SUCCEEDED,
            SpecialistOperationStatus.FAILED,
            SpecialistOperationStatus.CANCELLED,
        }:
            return
        provider_observation = None
        if self._cancellation_adapter is not None:
            try:
                provider_observation = self._cancellation_adapter.request_cancellation(
                    request,
                    operation_ref=operation_ref,
                    provider_receipt_ref=receipt_ref,
                )
            except Exception:
                # A transport/adapter error cannot be interpreted as provider failure.
                provider_observation = None
        try:
            if (
                provider_observation is not None
                and provider_observation.status
                is SpecialistProviderCancellationStatus.CONFIRMED
            ):
                self._operation_authority.cancel(
                    operation_ref,
                    provider_observation.failure_type or "ProviderCancellationConfirmed",
                )
            else:
                self._operation_authority.request_cancellation(
                    operation_ref,
                    uncertainty_type=(
                        provider_observation.uncertainty_type
                        if provider_observation is not None
                        else SpecialistUncertaintyType.PROVIDER_CANCELLATION_OBSERVATION_TIMEOUT
                    ),
                )
        except SpecialistProviderError:
            # A concurrent terminal provider receipt remains authoritative.
            return

    def _observe_provider_cancellation(
        self,
        request: TemporalActivityRequest,
        *,
        operation_ref: str,
        provider_receipt_ref: str,
    ) -> SpecialistProviderCancellationObservation | None:
        if self._cancellation_adapter is None:
            return None
        try:
            return self._cancellation_adapter.observe_cancellation(
                request,
                operation_ref=operation_ref,
                provider_receipt_ref=provider_receipt_ref,
            )
        except Exception:
            return None

    def _execute(self, request: TemporalActivityRequest) -> TemporalProviderActivityResult:
        spec = request.provider_spec
        receipt_ref = derive_specialist_provider_receipt_ref(request)
        operation_ref = f"{spec.operation_ref if spec else 'unbound'}://{request.activity_id}"
        if spec is None:
            return _failed_result(request, receipt_ref, operation_ref, "ProviderBindingMissing")
        if spec.input_artifact_ids and not set(spec.input_artifact_ids).issubset(
            set(request.input_artifact_ids)
        ):
            return _failed_result(
                request, receipt_ref, operation_ref, "InputArtifactBindingMismatch"
            )
        if self._operation_authority is not None:
            existing = self._operation_authority.observe(operation_ref)
            if existing is not None:
                if not _operation_observation_matches_request(existing, request, spec):
                    return _failed_result(
                        request,
                        receipt_ref,
                        operation_ref,
                        "ProviderOperationIdentityConflict",
                    )
                if existing.status is SpecialistOperationStatus.SUCCEEDED:
                    if existing.output_artifact_id is None:
                        return _failed_result(
                            request,
                            receipt_ref,
                            operation_ref,
                            "ProviderOperationReceiptMissingOutput",
                        )
                    try:
                        artifact = self._artifact_store.resolve_input(
                            request.tenant_id, existing.output_artifact_id
                        )
                        _validate_output_artifact_binding(request, spec, artifact)
                    except Exception as exc:
                        return _failed_result(
                            request,
                            receipt_ref,
                            operation_ref,
                            exc.__class__.__name__ or "ProviderOutputConflict",
                        )
                    return _success_result(request, receipt_ref, operation_ref, artifact)
                if existing.status is SpecialistOperationStatus.FAILED:
                    return _failed_result(
                        request,
                        receipt_ref,
                        operation_ref,
                        existing.failure_type or "ProviderFailed",
                    )
                if existing.status is SpecialistOperationStatus.CANCELLED:
                    return _failed_result(
                        request,
                        receipt_ref,
                        operation_ref,
                        existing.failure_type or "ProviderCancelled",
                    )
                provider_cancellation = self._observe_provider_cancellation(
                    request,
                    operation_ref=operation_ref,
                    provider_receipt_ref=receipt_ref,
                )
                if (
                    provider_cancellation is not None
                    and provider_cancellation.status
                    is SpecialistProviderCancellationStatus.CONFIRMED
                ):
                    try:
                        cancelled = self._operation_authority.cancel(
                            operation_ref,
                            provider_cancellation.failure_type
                            or "ProviderCancellationConfirmed",
                        )
                    except SpecialistProviderError:
                        cancelled = self._operation_authority.observe(operation_ref)
                    if (
                        cancelled is not None
                        and cancelled.status is SpecialistOperationStatus.CANCELLED
                    ):
                        return _failed_result(
                            request,
                            receipt_ref,
                            operation_ref,
                            cancelled.failure_type or "ProviderCancelled",
                        )
                # A previously submitted/unknown operation is intentionally not retried.
                receipt_artifact_id = None
                if request.side_effect is not AgentSideEffect.NONE:
                    receipt_artifact_id = _write_operation_receipt_artifact(
                        self._artifact_store, existing
                    ).artifact_id
                return _unknown_result(
                    request,
                    receipt_ref,
                    operation_ref,
                    external_receipt_artifact_id=receipt_artifact_id,
                )
            if self._retry_budget_authority is not None:
                from .agentops_specialist_retry_budget import (
                    SpecialistRetryBudgetError,
                    provider_operation_family_key,
                )

                try:
                    admission = self._retry_budget_authority.admit(
                        request,
                        operation_key=provider_operation_family_key(request),
                        max_attempts=self._retry_budget_max_attempts,
                        worker_id=self._worker_id,
                    )
                except SpecialistRetryBudgetError:
                    return _failed_result(
                        request,
                        receipt_ref,
                        operation_ref,
                        "RetryBudgetAuthorityUnavailable",
                    )
                if not admission.admitted:
                    return _failed_result(
                        request,
                        receipt_ref,
                        operation_ref,
                        "RetryBudgetExhausted",
                    )
            self._operation_authority.submit(
                request,
                provider_ref=spec.provider_ref,
                operation_ref=operation_ref,
                provider_receipt_ref=receipt_ref,
            )
            if self._cancellation_timeout_before_execution:
                cancelled = self._operation_authority.request_cancellation(
                    operation_ref,
                    uncertainty_type=SpecialistUncertaintyType.PROVIDER_CANCELLATION_OBSERVATION_TIMEOUT,
                )
                receipt_artifact_id = None
                if request.side_effect is not AgentSideEffect.NONE:
                    receipt_artifact_id = _write_operation_receipt_artifact(
                        self._artifact_store, cancelled
                    ).artifact_id
                return _unknown_result(
                    request,
                    receipt_ref,
                    operation_ref,
                    external_receipt_artifact_id=receipt_artifact_id,
                )
        try:
            selected_input_ids = spec.input_artifact_ids or request.input_artifact_ids
            inputs = tuple(
                self._artifact_store.resolve_input(request.tenant_id, artifact_id)
                for artifact_id in selected_input_ids
            )
            if (
                spec.provider_ref == MMFE_PROVIDER_REF
                and spec.operation_ref == MMFE_FUSION_OPERATION
            ):
                output, manifest = self._execute_mmfe(request, spec, inputs)
            elif (
                spec.provider_ref == GWM_PROVIDER_REF and spec.operation_ref == GWM_RENDER_OPERATION
            ):
                output, manifest = self._execute_gwm(request, spec, inputs)
            else:
                return _failed_result(
                    request, receipt_ref, operation_ref, "UnsupportedProviderOperation"
                )
            output_id = _output_artifact_id(request)
            artifact = self._artifact_store.write_output(
                tenant_id=request.tenant_id,
                artifact_id=output_id,
                content=output,
                media_type=spec.output_media_type,
                manifest=manifest,
                run_id=None,
                artifact_key=f"agentops-specialist:{request.tool_call_id}:{request.attempt_no}",
                created_by=f"workload:agentops:{spec.provider_ref}",
            )
            if self._operation_authority is not None:
                succeeded = self._operation_authority.succeed(operation_ref, artifact.artifact_id)
                if self._unknown_after_commit:
                    # The bytes and provider receipt are durable, but the activity
                    # response is lost. The control plane must reconcile this later.
                    receipt_artifact_id = None
                    if request.side_effect is not AgentSideEffect.NONE:
                        receipt_artifact_id = _write_operation_receipt_artifact(
                            self._artifact_store, succeeded
                        ).artifact_id
                    return _unknown_result(
                        request,
                        receipt_ref,
                        operation_ref,
                        external_receipt_artifact_id=receipt_artifact_id,
                    )
            return _success_result(
                request,
                receipt_ref,
                operation_ref,
                artifact,
            )
        except Exception as exc:  # typed failure keeps Temporal history deterministic
            if self._operation_authority is not None:
                try:
                    self._operation_authority.fail(
                        operation_ref,
                        exc.__class__.__name__ or "SpecialistProviderError",
                    )
                except SpecialistProviderError:
                    return _failed_result(
                        request,
                        receipt_ref,
                        operation_ref,
                        "ProviderOperationReceiptConflict",
                    )
            return _failed_result(
                request,
                receipt_ref,
                operation_ref,
                exc.__class__.__name__ or "SpecialistProviderError",
            )

    def _execute_mmfe(
        self,
        request: TemporalActivityRequest,
        spec: TemporalProviderExecutionSpec,
        inputs: tuple[LocalArtifact, ...],
    ) -> tuple[bytes, dict[str, Any]]:
        if len(inputs) < 2:
            raise SpecialistProviderError("MMFE fusion requires at least two input artifacts")
        from .fusion import align_sources, assess_compatibility, execute_fusion, profile_source

        sources = [profile_source(str(artifact.storage_path)) for artifact in inputs]
        report = assess_compatibility(sources)
        aligned, alignment_log = align_sources(sources, report)
        parameters = spec.parameters or {}
        result = execute_fusion(
            aligned,
            str(parameters.get("strategy") or "auto"),
            sources,
            params=dict(parameters.get("params") or {}),
            report=report,
            semantic_config=parameters.get("semantic_config") or None,
        )
        output_path = Path(result.output_path)
        if not output_path.is_file():
            raise SpecialistProviderError("MMFE provider did not produce an output artifact")
        content = output_path.read_bytes()
        manifest = {
            "schema": "gda.specialist_provider_output_manifest.v1",
            "provider_ref": spec.provider_ref,
            "operation_ref": spec.operation_ref,
            "request_sha256": request.request_sha256,
            "input_artifact_ids": [str(item.artifact_id) for item in inputs],
            "lineage": {"source_artifact_ids": [str(item.artifact_id) for item in inputs]},
            "quality": {
                "score": result.quality_score,
                "warnings": list(result.quality_warnings),
            },
            "mmfe": {
                "strategy_used": result.strategy_used,
                "row_count": result.row_count,
                "column_count": result.column_count,
                "alignment_log": list(alignment_log) + list(result.alignment_log),
                "semantic_product_path": result.semantic_product_path or None,
            },
            "content_sha256": _sha256(content),
        }
        return content, manifest

    def _execute_gwm(
        self,
        request: TemporalActivityRequest,
        spec: TemporalProviderExecutionSpec,
        inputs: tuple[LocalArtifact, ...],
    ) -> tuple[bytes, dict[str, Any]]:
        if len(inputs) != 1:
            raise SpecialistProviderError("GWM observation rendering requires one MMFE state input")
        from .uwm.renderer import build_canonical_observation_from_state_input

        payload = json.loads(inputs[0].storage_path.read_text(encoding="utf-8"))
        parameters = spec.parameters or {}
        observation = build_canonical_observation_from_state_input(
            payload,
            observation_id=parameters.get("observation_id"),
        )
        content = json.dumps(observation, ensure_ascii=False, sort_keys=True, indent=2).encode(
            "utf-8"
        )
        manifest = {
            "schema": "gda.specialist_provider_output_manifest.v1",
            "provider_ref": spec.provider_ref,
            "operation_ref": spec.operation_ref,
            "request_sha256": request.request_sha256,
            "input_artifact_ids": [str(inputs[0].artifact_id)],
            "lineage": {"source_artifact_ids": [str(inputs[0].artifact_id)]},
            "quality": {
                "valid": not any(
                    flag.get("level") == "error"
                    for flag in observation.get("quality_flags") or []
                    if isinstance(flag, dict)
                )
            },
            "gwm": {
                "observation_id": observation.get("observation_id"),
                "claim_level": (observation.get("claim_boundary") or {}).get("max_claim_level"),
            },
            "content_sha256": _sha256(content),
        }
        return content, manifest


class TemporalProviderCancellationProbeExecutor:
    """Hold a provider-bound activity until Temporal cancellation is delivered.

    This executor is intentionally small and provider-neutral. It is used by live
    Temporal cancellation rehearsals where the provider operation already exists
    (for example, a Flink job submitted by an external controller). The executor
    registers the deterministic operation identity, waits without issuing a second
    provider submission, and invokes the provider-native cancellation adapter only
    after Temporal cancels the activity. A provider acknowledgement is recorded as
    ``unknown``; only an adapter observation of ``confirmed`` advances the receipt to
    ``cancelled``.
    """

    def __init__(
        self,
        operation_authority: SpecialistOperationAuthority,
        cancellation_adapter: SpecialistProviderCancellationAdapter,
        *,
        hold_seconds: float = 3_600.0,
        poll_seconds: float = 0.1,
        cancellation_timeout_seconds: float = 30.0,
        cancellation_poll_seconds: float = 0.25,
        on_submitted: Any | None = None,
    ) -> None:
        if hold_seconds <= 0:
            raise ValueError("cancellation probe hold_seconds must be positive")
        if poll_seconds <= 0:
            raise ValueError("cancellation probe poll_seconds must be positive")
        if cancellation_timeout_seconds <= 0:
            raise ValueError("cancellation probe cancellation_timeout_seconds must be positive")
        if cancellation_poll_seconds <= 0:
            raise ValueError("cancellation probe cancellation_poll_seconds must be positive")
        if not callable(getattr(operation_authority, "submit", None)):
            raise TypeError("cancellation probe requires an operation authority")
        if not callable(getattr(cancellation_adapter, "request_cancellation", None)):
            raise TypeError("cancellation probe requires a provider cancellation adapter")
        self._operation_authority = operation_authority
        self._cancellation_adapter = cancellation_adapter
        self._hold_seconds = float(hold_seconds)
        self._poll_seconds = float(poll_seconds)
        self._cancellation_timeout_seconds = float(cancellation_timeout_seconds)
        self._cancellation_poll_seconds = float(cancellation_poll_seconds)
        self._on_submitted = on_submitted

    async def __call__(self, request: TemporalActivityRequest) -> TemporalProviderActivityResult:
        spec = request.provider_spec
        if spec is None:
            raise SpecialistProviderError("cancellation probe requires a provider binding")
        operation_ref = f"{spec.operation_ref}://{request.activity_id}"
        provider_receipt_ref = derive_specialist_provider_receipt_ref(request)
        existing = await asyncio.to_thread(self._operation_authority.observe, operation_ref)
        if existing is None:
            await asyncio.to_thread(
                self._operation_authority.submit,
                request,
                provider_ref=spec.provider_ref,
                operation_ref=operation_ref,
                provider_receipt_ref=provider_receipt_ref,
            )
        elif not _operation_observation_matches_request(existing, request, spec):
            raise SpecialistProviderError(
                "cancellation probe operation identity is already bound differently"
            )
        elif existing.status in {
            SpecialistOperationStatus.SUCCEEDED,
            SpecialistOperationStatus.FAILED,
            SpecialistOperationStatus.CANCELLED,
        }:
            raise SpecialistProviderError(
                "cancellation probe cannot dispatch a terminal provider operation"
            )
        if callable(self._on_submitted):
            self._on_submitted(request, operation_ref, provider_receipt_ref)

        deadline = asyncio.get_running_loop().time() + self._hold_seconds
        try:
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(self._poll_seconds)
        except asyncio.CancelledError:
            await asyncio.to_thread(
                self._settle_cancellation,
                request,
                operation_ref,
                provider_receipt_ref,
            )
            raise
        raise SpecialistProviderError("cancellation probe hold window elapsed")

    def _settle_cancellation(
        self,
        request: TemporalActivityRequest,
        operation_ref: str,
        provider_receipt_ref: str,
    ) -> None:
        try:
            observation = self._cancellation_adapter.request_cancellation(
                request,
                operation_ref=operation_ref,
                provider_receipt_ref=provider_receipt_ref,
            )
        except Exception:
            observation = None
        latest_observation = observation
        observation_timed_out = False
        if (
            observation is not None
            and observation.status is SpecialistProviderCancellationStatus.ACCEPTED
        ):
            deadline = time.monotonic() + self._cancellation_timeout_seconds
            while time.monotonic() < deadline:
                try:
                    observed = self._cancellation_adapter.observe_cancellation(
                        request,
                        operation_ref=operation_ref,
                        provider_receipt_ref=provider_receipt_ref,
                    )
                except Exception:
                    observed = None
                if observed is not None:
                    latest_observation = observed
                if (
                    observed is not None
                    and observed.status is SpecialistProviderCancellationStatus.CONFIRMED
                ):
                    observation = observed
                    break
                time.sleep(self._cancellation_poll_seconds)
            observation_timed_out = (
                latest_observation is None
                or latest_observation.status
                is SpecialistProviderCancellationStatus.ACCEPTED
            )
        try:
            if (
                observation is not None
                and observation.status
                is SpecialistProviderCancellationStatus.CONFIRMED
            ):
                self._operation_authority.cancel(
                    operation_ref,
                    observation.failure_type or "ProviderCancellationConfirmed",
                )
            else:
                self._operation_authority.request_cancellation(
                    operation_ref,
                    uncertainty_type=(
                        SpecialistUncertaintyType.PROVIDER_CANCELLATION_OBSERVATION_TIMEOUT
                        if observation_timed_out
                        else latest_observation.uncertainty_type
                        if latest_observation is not None
                        and latest_observation.uncertainty_type is not None
                        else SpecialistUncertaintyType.PROVIDER_CANCELLATION_OBSERVATION_TIMEOUT
                    ),
                )
        except SpecialistProviderError:
            # A concurrent terminal receipt remains authoritative.
            return


def reconcile_unknown_specialist_activity(
    request: TemporalActivityRequest,
    unknown_result: TemporalProviderActivityResult,
    *,
    artifact_store: SpecialistArtifactStore,
    operation_authority: SpecialistOperationAuthority | None = None,
) -> tuple[SpecialistActivityReconciliation, TemporalProviderActivityResult]:
    """Resolve an unknown provider result without submitting a second operation.

    The reconciler first observes the provider receipt, then verifies the deterministic
    output Artifact through the same authority used by the provider. A matching output
    settles success; a definitive provider failure settles failed; otherwise the result
    remains unknown and no retry or success evidence is emitted.
    """

    if unknown_result.outcome is not TemporalActivityOutcome.UNKNOWN:
        raise SpecialistProviderError(
            "specialist reconciliation requires an unknown activity result"
        )
    spec = request.provider_spec
    if spec is None:
        raise SpecialistProviderError("unknown specialist activity has no provider binding")
    operation_ref = unknown_result.provider_operation_ref
    if operation_ref is None:
        raise SpecialistProviderError("unknown specialist activity has no provider operation ref")
    observation = (
        operation_authority.observe(operation_ref) if operation_authority is not None else None
    )
    if observation is not None and not _operation_observation_matches_request(
        observation, request, spec
    ):
        raise SpecialistProviderError("provider operation observation differs from request")

    expected_output_id = _output_artifact_id(request)
    observed_output_id = observation.output_artifact_id if observation is not None else None
    if observed_output_id is not None and observed_output_id != expected_output_id:
        raise SpecialistProviderError(
            "provider operation output Artifact identity conflicts with request"
        )

    artifact: LocalArtifact | None = None
    try:
        artifact = artifact_store.resolve_input(request.tenant_id, expected_output_id)
    except Exception:
        artifact = None

    if artifact is not None:
        _validate_output_artifact_binding(request, spec, artifact)

    status = observation.status if observation is not None else SpecialistOperationStatus.UNKNOWN
    if status is SpecialistOperationStatus.SUCCEEDED:
        if artifact is None:
            raise SpecialistProviderError(
                "provider receipt claims success but output Artifact is unavailable"
            )
        result = _success_result(
            request,
            unknown_result.provider_receipt_ref,
            operation_ref,
            artifact,
        )
        verdict = SpecialistReconciliationVerdict.MATCHED_SUCCEEDED
        output_artifact_id = artifact.artifact_id
        failure_type = None
    elif status in {
        SpecialistOperationStatus.FAILED,
        SpecialistOperationStatus.CANCELLED,
    }:
        failure_type = (
            observation.failure_type
            if observation is not None and observation.failure_type
            else "ProviderCancelled"
            if status is SpecialistOperationStatus.CANCELLED
            else "ProviderFailed"
        )
        result = _failed_result(
            request,
            unknown_result.provider_receipt_ref,
            operation_ref,
            failure_type,
        )
        verdict = SpecialistReconciliationVerdict.DEFINITIVE_FAILED
        output_artifact_id = None
    else:
        # A matching output is sufficient to settle an operation whose response was
        # lost, but a merely pending receipt cannot claim success without that output.
        if artifact is not None:
            result = _success_result(
                request,
                unknown_result.provider_receipt_ref,
                operation_ref,
                artifact,
            )
            verdict = SpecialistReconciliationVerdict.MATCHED_SUCCEEDED
            output_artifact_id = artifact.artifact_id
            failure_type = None
        else:
            result = _unknown_result(
                request,
                unknown_result.provider_receipt_ref,
                operation_ref,
            )
            verdict = SpecialistReconciliationVerdict.UNKNOWN_PENDING
            output_artifact_id = None
            failure_type = None

    values: dict[str, Any] = {
        "tenant_id": request.tenant_id,
        "workflow_id": request.workflow_id,
        "run_id": request.run_id,
        "activity_id": request.activity_id,
        "tool_call_id": request.tool_call_id,
        "attempt_no": request.attempt_no,
        "request_sha256": request.request_sha256,
        "provider_operation_ref": operation_ref,
        "provider_receipt_ref": unknown_result.provider_receipt_ref,
        "observed_status": status,
        "verdict": verdict,
        "output_artifact_id": output_artifact_id,
        "failure_type": failure_type,
        "observation_sha256": observation.observation_sha256 if observation else None,
    }
    values["reconciliation_sha256"] = temporal_contract_fingerprint(
        SPECIALIST_ACTIVITY_RECONCILIATION_SCHEMA,
        values,
        "reconciliation_sha256",
    )
    return SpecialistActivityReconciliation(**values), result


def _operation_observation_matches_request(
    observation: SpecialistOperationObservation,
    request: TemporalActivityRequest,
    spec: TemporalProviderExecutionSpec,
) -> bool:
    return (
        observation.tenant_id == request.tenant_id
        and observation.workflow_id == request.workflow_id
        and observation.run_id == request.run_id
        and observation.step_id == request.step_id
        and observation.tool_call_id == request.tool_call_id
        and observation.activity_id == request.activity_id
        and observation.attempt_no == request.attempt_no
        and observation.request_sha256 == request.request_sha256
        and observation.provider_ref == spec.provider_ref
        and observation.operation_ref == f"{spec.operation_ref}://{request.activity_id}"
    )


def _validate_output_artifact_binding(
    request: TemporalActivityRequest,
    spec: TemporalProviderExecutionSpec,
    artifact: LocalArtifact,
) -> None:
    expected_id = _output_artifact_id(request)
    if artifact.artifact_id != expected_id:
        raise SpecialistProviderError("output Artifact identity differs from activity")
    if artifact.tenant_id != request.tenant_id:
        raise SpecialistProviderError("output Artifact tenant differs from activity")
    if artifact.media_type != spec.output_media_type:
        raise SpecialistProviderError("output Artifact media type differs from provider spec")
    manifest = artifact.manifest
    if manifest.get("request_sha256") != request.request_sha256:
        raise SpecialistProviderError("output Artifact manifest request hash differs from activity")
    if manifest.get("provider_ref") != spec.provider_ref:
        raise SpecialistProviderError(
            "output Artifact manifest provider differs from provider spec"
        )
    if manifest.get("operation_ref") != spec.operation_ref:
        raise SpecialistProviderError(
            "output Artifact manifest operation differs from provider spec"
        )
    expected_inputs = [
        str(item) for item in (spec.input_artifact_ids or request.input_artifact_ids)
    ]
    if manifest.get("input_artifact_ids") != expected_inputs:
        raise SpecialistProviderError("output Artifact manifest inputs differ from provider spec")
    lineage = manifest.get("lineage")
    if not isinstance(lineage, dict) or lineage.get("source_artifact_ids") != expected_inputs:
        raise SpecialistProviderError("output Artifact lineage differs from provider spec")
    if manifest.get("content_sha256") != artifact.content_sha256:
        raise SpecialistProviderError("output Artifact manifest checksum differs from authority")
    if (
        not artifact.storage_path.is_file()
        or _sha256(artifact.storage_path.read_bytes()) != artifact.content_sha256
    ):
        raise SpecialistProviderError("output Artifact bytes differ from authority checksum")


def _output_artifact_id(request: TemporalActivityRequest) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"gda-specialist-output:{request.tenant_id}:{request.activity_id}:{request.attempt_no}",
    )


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _extension_for_media_type(media_type: str) -> str:
    return {
        "application/geo+json": ".geojson",
        "application/json": ".json",
        "application/parquet": ".parquet",
        "image/tiff": ".tif",
    }.get(media_type, ".bin")


def _success_result(
    request: TemporalActivityRequest,
    receipt_ref: str,
    operation_ref: str,
    artifact: LocalArtifact,
) -> TemporalProviderActivityResult:
    values: dict[str, Any] = {
        "tenant_id": request.tenant_id,
        "workflow_id": request.workflow_id,
        "run_id": request.run_id,
        "step_id": request.step_id,
        "tool_call_id": request.tool_call_id,
        "activity_id": request.activity_id,
        "attempt_no": request.attempt_no,
        "request_sha256": request.request_sha256,
        "outcome": TemporalActivityOutcome.SUCCEEDED,
        "provider_receipt_ref": receipt_ref,
        "provider_operation_ref": operation_ref,
        "output_artifact_id": artifact.artifact_id,
        "external_receipt_artifact_id": None,
        "failure_type": None,
    }
    values["result_sha256"] = temporal_contract_fingerprint(
        TemporalProviderActivityResult.schema_id, values, "result_sha256"
    )
    return TemporalProviderActivityResult(**values)


def _failed_result(
    request: TemporalActivityRequest,
    receipt_ref: str,
    operation_ref: str,
    failure_type: str,
) -> TemporalProviderActivityResult:
    values: dict[str, Any] = {
        "tenant_id": request.tenant_id,
        "workflow_id": request.workflow_id,
        "run_id": request.run_id,
        "step_id": request.step_id,
        "tool_call_id": request.tool_call_id,
        "activity_id": request.activity_id,
        "attempt_no": request.attempt_no,
        "request_sha256": request.request_sha256,
        "outcome": TemporalActivityOutcome.FAILED,
        "provider_receipt_ref": receipt_ref,
        "provider_operation_ref": operation_ref,
        "output_artifact_id": None,
        "external_receipt_artifact_id": None,
        "failure_type": failure_type,
    }
    values["result_sha256"] = temporal_contract_fingerprint(
        TemporalProviderActivityResult.schema_id, values, "result_sha256"
    )
    return TemporalProviderActivityResult(**values)


def _unknown_result(
    request: TemporalActivityRequest,
    receipt_ref: str,
    operation_ref: str,
    *,
    external_receipt_artifact_id: UUID | None = None,
) -> TemporalProviderActivityResult:
    values: dict[str, Any] = {
        "tenant_id": request.tenant_id,
        "workflow_id": request.workflow_id,
        "run_id": request.run_id,
        "step_id": request.step_id,
        "tool_call_id": request.tool_call_id,
        "activity_id": request.activity_id,
        "attempt_no": request.attempt_no,
        "request_sha256": request.request_sha256,
        "outcome": TemporalActivityOutcome.UNKNOWN,
        "provider_receipt_ref": receipt_ref,
        "provider_operation_ref": operation_ref,
        "output_artifact_id": None,
        "external_receipt_artifact_id": external_receipt_artifact_id,
        "failure_type": None,
    }
    values["result_sha256"] = temporal_contract_fingerprint(
        TemporalProviderActivityResult.schema_id, values, "result_sha256"
    )
    return TemporalProviderActivityResult(**values)


__all__ = [
    "ArtifactContentBackend",
    "FilesystemArtifactContentBackend",
    "GWM_PROVIDER_REF",
    "GWM_RENDER_OPERATION",
    "MMFE_FUSION_OPERATION",
    "MMFE_PROVIDER_REF",
    "BoundSpecialistExecutor",
    "TemporalProviderCancellationProbeExecutor",
    "FilesystemSpecialistArtifactStore",
    "LocalArtifact",
    "PostgresArtifactAuthoritySpecialistStore",
    "S3ArtifactContentBackend",
    "SpecialistArtifactStore",
    "SPECIALIST_ACTIVITY_RECONCILIATION_SCHEMA",
    "SPECIALIST_PROVIDER_CANCELLATION_OBSERVATION_SCHEMA",
    "SPECIALIST_OPERATION_OBSERVATION_SCHEMA",
    "SPECIALIST_OPERATION_RECEIPT_SCHEMA",
    "InMemorySpecialistOperationAuthority",
    "SpecialistActivityReconciliation",
    "SpecialistOperationAuthority",
    "SpecialistOperationObservation",
    "SpecialistOperationReceipt",
    "SpecialistOperationStatus",
    "SpecialistUncertaintyType",
    "SpecialistProviderCancellationAdapter",
    "SpecialistProviderCancellationObservation",
    "SpecialistProviderCancellationStatus",
    "SpecialistReconciliationVerdict",
    "SpecialistProviderError",
    "UnsupportedSpecialistCancellationAdapter",
    "InMemorySpecialistCancellationAdapter",
    "build_gwm_provider_spec",
    "build_mmfe_provider_spec",
    "reconcile_unknown_specialist_activity",
]
