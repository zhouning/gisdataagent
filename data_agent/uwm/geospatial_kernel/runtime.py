"""Domain-neutral execution contract for bounded geospatial kernels.

The runtime owns orchestration and audit semantics only. Domain adapters keep
their native state, action, transition and constraint representations.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Generic, Literal, Protocol, TypeVar, runtime_checkable

GEOSPATIAL_KERNEL_RUNTIME_SCHEMA = "gwm.geospatial_kernel.runtime.v1"
GEOSPATIAL_KERNEL_STEP_SCHEMA = "gwm.geospatial_kernel.step.v1"
GEOSPATIAL_KERNEL_ROLLOUT_SCHEMA = "gwm.geospatial_kernel.rollout.v1"
GEOSPATIAL_KERNEL_CAPABILITY_SCHEMA = "gwm.geospatial_kernel.capabilities.v1"
GEOSPATIAL_KERNEL_EXECUTION_SUMMARY_SCHEMA = (
    "gwm.geospatial_kernel.execution_summary.v1"
)

StateT = TypeVar("StateT")
ActionT = TypeVar("ActionT")
ContextT = TypeVar("ContextT")
CandidateT = TypeVar("CandidateT")


def _required(value: str, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name}_required")
    return normalized


@dataclass(frozen=True)
class KernelEvidenceRef:
    """Reference to evidence without forcing the runtime to load its payload."""

    uri: str
    role: str
    sha256: str | None = None

    def __post_init__(self) -> None:
        _required(self.uri, "evidence_uri")
        _required(self.role, "evidence_role")
        if self.sha256 is not None:
            digest = self.sha256.lower()
            if len(digest) != 64 or any(value not in "0123456789abcdef" for value in digest):
                raise ValueError("evidence_sha256_invalid")

    def as_dict(self) -> dict[str, str]:
        result = {"uri": self.uri, "role": self.role}
        if self.sha256 is not None:
            result["sha256"] = self.sha256
        return result


@dataclass(frozen=True)
class KernelProvenance:
    """Model and evidence identity attached to an executed transition."""

    model_id: str
    model_version: str
    parameter_ref: str
    evidence: tuple[KernelEvidenceRef, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _required(self.model_id, "provenance_model_id")
        _required(self.model_version, "provenance_model_version")
        _required(self.parameter_ref, "provenance_parameter_ref")

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "parameter_ref": self.parameter_ref,
            "evidence": [value.as_dict() for value in self.evidence],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class KernelAdapterDescriptor:
    """Stable identity and claim boundary for one domain adapter."""

    adapter_id: str
    adapter_version: str
    domain: str
    state_semantics: str
    action_semantics: str
    transition_semantics: str
    constraint_semantics: str

    def __post_init__(self) -> None:
        for field_name in (
            "adapter_id",
            "adapter_version",
            "domain",
            "state_semantics",
            "action_semantics",
            "transition_semantics",
            "constraint_semantics",
        ):
            _required(getattr(self, field_name), field_name)

    def as_dict(self) -> dict[str, str]:
        return {
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "domain": self.domain,
            "state_semantics": self.state_semantics,
            "action_semantics": self.action_semantics,
            "transition_semantics": self.transition_semantics,
            "constraint_semantics": self.constraint_semantics,
        }


@dataclass(frozen=True)
class KernelState(Generic[StateT]):
    domain: str
    time_id: str
    state_ref: str
    payload: StateT
    evidence: tuple[KernelEvidenceRef, ...] = ()

    def __post_init__(self) -> None:
        _required(self.domain, "state_domain")
        _required(self.time_id, "state_time_id")
        _required(self.state_ref, "state_ref")


@dataclass(frozen=True)
class KernelAction(Generic[ActionT]):
    action_id: str
    domain: str
    source_time: str
    target_time: str
    payload: ActionT
    evidence: tuple[KernelEvidenceRef, ...] = ()

    def __post_init__(self) -> None:
        _required(self.action_id, "action_id")
        _required(self.domain, "action_domain")
        _required(self.source_time, "action_source_time")
        _required(self.target_time, "action_target_time")
        if self.source_time == self.target_time:
            raise ValueError("action_must_advance_time")


@dataclass(frozen=True)
class KernelTransitionCandidate(Generic[CandidateT]):
    payload: CandidateT
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KernelConstraintProjection(Generic[StateT]):
    state_payload: StateT | None
    status: Literal["admitted", "projected", "rejected"]
    state_ref: str
    provenance: KernelProvenance
    violations: tuple[str, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _required(self.state_ref, "projected_state_ref")
        if self.status not in {"admitted", "projected", "rejected"}:
            raise ValueError("unsupported_constraint_projection_status")
        if self.status != "rejected" and self.state_payload is None:
            raise ValueError("projected_state_payload_required")


@runtime_checkable
class GeospatialKernelAdapter(Protocol[StateT, ActionT, ContextT, CandidateT]):
    """Common executable boundary implemented by each bounded domain."""

    descriptor: KernelAdapterDescriptor

    def propose_transition(
        self,
        *,
        state: KernelState[StateT],
        action: KernelAction[ActionT],
        context: ContextT,
    ) -> KernelTransitionCandidate[CandidateT]: ...

    def project_constraints(
        self,
        *,
        state: KernelState[StateT],
        action: KernelAction[ActionT],
        candidate: KernelTransitionCandidate[CandidateT],
        context: ContextT,
    ) -> KernelConstraintProjection[StateT]: ...


@dataclass(frozen=True)
class KernelStepResult(Generic[StateT, ActionT, CandidateT]):
    adapter: KernelAdapterDescriptor
    source_state: KernelState[StateT]
    action: KernelAction[ActionT]
    candidate: KernelTransitionCandidate[CandidateT]
    projection: KernelConstraintProjection[StateT]
    next_state: KernelState[StateT]

    def audit(self) -> dict[str, Any]:
        return {
            "schema": GEOSPATIAL_KERNEL_STEP_SCHEMA,
            "adapter": self.adapter.as_dict(),
            "source": {
                "domain": self.source_state.domain,
                "time_id": self.source_state.time_id,
                "state_ref": self.source_state.state_ref,
                "evidence": [value.as_dict() for value in self.source_state.evidence],
            },
            "action": {
                "action_id": self.action.action_id,
                "source_time": self.action.source_time,
                "target_time": self.action.target_time,
                "evidence": [value.as_dict() for value in self.action.evidence],
            },
            "transition_diagnostics": dict(self.candidate.diagnostics),
            "constraint_projection": {
                "status": self.projection.status,
                "violations": list(self.projection.violations),
                "diagnostics": dict(self.projection.diagnostics),
            },
            "result": {
                "time_id": self.next_state.time_id,
                "state_ref": self.next_state.state_ref,
                "provenance": self.projection.provenance.as_dict(),
            },
        }


@dataclass(frozen=True)
class KernelRolloutTrace(Generic[StateT, ActionT, CandidateT]):
    initial_state: KernelState[StateT]
    steps: tuple[KernelStepResult[StateT, ActionT, CandidateT], ...]

    @property
    def final_state(self) -> KernelState[StateT]:
        return self.steps[-1].next_state if self.steps else self.initial_state

    def audit(self) -> dict[str, Any]:
        return {
            "schema": GEOSPATIAL_KERNEL_ROLLOUT_SCHEMA,
            "step_count": len(self.steps),
            "initial_state_ref": self.initial_state.state_ref,
            "final_state_ref": self.final_state.state_ref,
            "steps": [step.audit() for step in self.steps],
        }


class KernelConstraintRejected(RuntimeError):
    def __init__(self, projection: KernelConstraintProjection[Any]) -> None:
        self.projection = projection
        reasons = ",".join(projection.violations) or "unspecified"
        super().__init__(f"geospatial_kernel_constraint_rejected:{reasons}")


class GeospatialKernelRuntime(Generic[StateT, ActionT, ContextT, CandidateT]):
    """Execute domain adapters under one fail-closed step and rollout contract."""

    def __init__(
        self,
        adapter: GeospatialKernelAdapter[StateT, ActionT, ContextT, CandidateT],
    ) -> None:
        if not isinstance(adapter.descriptor, KernelAdapterDescriptor):
            raise TypeError("geospatial_kernel_adapter_descriptor_required")
        self.adapter = adapter

    def step(
        self,
        *,
        state: KernelState[StateT],
        action: KernelAction[ActionT],
        context: ContextT,
    ) -> KernelStepResult[StateT, ActionT, CandidateT]:
        descriptor = self.adapter.descriptor
        if state.domain != descriptor.domain or action.domain != descriptor.domain:
            raise ValueError("geospatial_kernel_domain_mismatch")
        if action.source_time != state.time_id:
            raise ValueError("geospatial_kernel_action_source_time_mismatch")
        candidate = self.adapter.propose_transition(
            state=state,
            action=action,
            context=context,
        )
        projection = self.adapter.project_constraints(
            state=state,
            action=action,
            candidate=candidate,
            context=context,
        )
        if projection.status == "rejected":
            raise KernelConstraintRejected(projection)
        next_state = KernelState(
            domain=descriptor.domain,
            time_id=action.target_time,
            state_ref=projection.state_ref,
            payload=projection.state_payload,
            evidence=projection.provenance.evidence,
        )
        return KernelStepResult(
            adapter=descriptor,
            source_state=state,
            action=action,
            candidate=candidate,
            projection=projection,
            next_state=next_state,
        )

    def rollout(
        self,
        *,
        initial_state: KernelState[StateT],
        steps: Iterable[tuple[KernelAction[ActionT], ContextT]],
    ) -> KernelRolloutTrace[StateT, ActionT, CandidateT]:
        state = initial_state
        results = []
        for action, context in steps:
            result = self.step(state=state, action=action, context=context)
            results.append(result)
            state = result.next_state
        return KernelRolloutTrace(initial_state=initial_state, steps=tuple(results))


def build_kernel_capability_report(
    descriptors: Iterable[KernelAdapterDescriptor],
) -> dict[str, Any]:
    """Report adapter conformance without claiming shared algorithms or parameters."""

    values = tuple(descriptors)
    adapter_ids = [value.adapter_id for value in values]
    if len(adapter_ids) != len(set(adapter_ids)):
        raise ValueError("duplicate_geospatial_kernel_adapter_id")
    return {
        "schema": GEOSPATIAL_KERNEL_CAPABILITY_SCHEMA,
        "runtime_schema": GEOSPATIAL_KERNEL_RUNTIME_SCHEMA,
        "adapter_count": len(values),
        "domains": sorted({value.domain for value in values}),
        "adapters": [value.as_dict() for value in values],
        "shared_contract": [
            "typed_state",
            "typed_action",
            "transition_proposal",
            "constraint_projection",
            "state_writeback",
            "rollout_trace",
            "evidence_provenance",
        ],
        "claim_boundary": {
            "shared_execution_semantics": True,
            "shared_learning_algorithm": False,
            "shared_parameters": False,
            "cross_domain_skill_transfer_proven": False,
        },
    }


def summarize_kernel_steps(
    *,
    adapter: KernelAdapterDescriptor,
    expected_step_count: int,
    steps: Iterable[KernelStepResult[Any, Any, Any]],
) -> dict[str, Any]:
    """Summarize completed runtime steps without upgrading domain claims."""

    if not isinstance(adapter, KernelAdapterDescriptor):
        raise TypeError("geospatial_kernel_summary_adapter_required")
    if (
        not isinstance(expected_step_count, int)
        or isinstance(expected_step_count, bool)
        or expected_step_count < 0
    ):
        raise ValueError("geospatial_kernel_expected_step_count_invalid")
    values = tuple(steps)
    if any(not isinstance(step, KernelStepResult) for step in values):
        raise TypeError("geospatial_kernel_summary_step_invalid")
    if any(step.adapter != adapter for step in values):
        raise ValueError("geospatial_kernel_summary_mixed_adapters")
    status_counts = {
        status: sum(step.projection.status == status for step in values)
        for status in ("admitted", "projected", "rejected")
    }
    completed_step_count = len(values)
    all_steps_accounted = sum(status_counts.values()) == completed_step_count
    return {
        "schema": GEOSPATIAL_KERNEL_EXECUTION_SUMMARY_SCHEMA,
        "runtime_schema": GEOSPATIAL_KERNEL_RUNTIME_SCHEMA,
        "adapter_id": adapter.adapter_id,
        "adapter_version": adapter.adapter_version,
        "domain": adapter.domain,
        "expected_step_count": expected_step_count,
        "completed_step_count": completed_step_count,
        "status_counts": status_counts,
        "all_completed_steps_accounted": all_steps_accounted,
        "all_expected_steps_completed": (
            completed_step_count == expected_step_count
            and status_counts["rejected"] == 0
            and all_steps_accounted
        ),
        "all_steps_admitted": (
            completed_step_count == expected_step_count
            and status_counts["admitted"] == completed_step_count
        ),
        "claim_boundary": {
            "execution_completed_does_not_imply_domain_validation": True,
            "projected_steps_are_not_admitted": True,
        },
    }
