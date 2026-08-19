"""Explicit production admission for one sealed Chongqing five-Provider run.

Technical profile releases, customer-rule bindings, plans, and deployments do
not grant production authority. This module only seals a separately authorized,
time-bounded admission lifecycle and never invokes a Provider.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .cross_store_projection_compensation_chongqing_deployment import (
    ChongqingFederatedCompensationDeploymentBinding,
)
from .cross_store_projection_compensation_chongqing_source_selection_profile_release import (
    ChongqingSourceSelectionProfileExecutionReleaseBinding,
)
from .cross_store_projection_compensation_dispatch import (
    FederatedProjectionCompensationDispatchIntent,
    FederatedProjectionCompensationDispatchRuleCurrentBinding,
)
from .cross_store_projection_compensation_provider_materialization import (
    FederatedProjectionCompensationProviderMaterializationSet,
)
from .cross_store_projection_compensation_provider_plan import (
    FederatedProjectionCompensationProviderPlanSet,
)
from .platform_contracts import (
    NonEmptyText,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
)


class ChongqingFiveProviderProductionAdmissionError(ValueError):
    """A production admission lifecycle cannot be safely sealed."""


class ChongqingFiveProviderProductionAdmissionCurrentReader(Protocol):
    """Tenant-bound live reader used immediately before Provider callbacks."""

    tenant_id: str

    def admission_history_current(
        self,
        run_id: str,
    ) -> ChongqingFiveProviderProductionAdmissionHistory | None:
        ...


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": _json_ready(payload)})


class ChongqingFiveProviderProductionAdmissionTarget(_FrozenModel):
    """Exact run and live-authority identity covered by one explicit grant."""

    schema_id: ClassVar[str] = (
        "gda.chongqing-five-provider-production-admission-target.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    proposal_sha256: Sha256
    candidate_sha256: Sha256
    dispatch_intent_sha256: Sha256
    plan_set_sha256: Sha256
    materialization_set_sha256: Sha256
    deployment_binding_sha256: Sha256
    request_bundle_sha256: Sha256
    execution_release_binding_sha256: Sha256
    active_profile_release_sha256: Sha256
    profile_release_history_sha256: Sha256
    source_selection_profile_sha256: Sha256
    rule_current_binding_sha256: Sha256
    rule_authority_evidence_sha256: Sha256
    rule_assessment_sha256: Sha256
    approved_rule_contract_sha256s: tuple[Sha256, ...] = Field(
        min_length=1,
        max_length=8,
    )
    technical_review_state: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    technical_intended_use: Literal[
        "assisted_precheck_not_for_production_decision"
    ] = "assisted_precheck_not_for_production_decision"
    technical_baseline_grants_production_authority: Literal[False] = False
    target_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFiveProviderProductionAdmissionTarget:
        if tuple(sorted(set(self.approved_rule_contract_sha256s))) != (
            self.approved_rule_contract_sha256s
        ):
            raise ValueError("production admission rule hashes must be unique and sorted")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"target_sha256"}),
            "target_sha256",
        )
        if self.target_sha256 != expected:
            raise ValueError("production admission target fingerprint is invalid")
        return self


class ChongqingFiveProviderProductionAdmissionEvent(_FrozenModel):
    """One immutable promotion, revocation, or rollback decision."""

    schema_id: ClassVar[str] = (
        "gda.chongqing-five-provider-production-admission-event.v1"
    )
    event_id: NonEmptyText
    tenant_id: TenantId
    run_id: NonEmptyText
    event_version: int = Field(ge=1, le=1024)
    event_kind: Literal["promotion", "revocation", "rollback"]
    target: ChongqingFiveProviderProductionAdmissionTarget
    authorized_by: NonEmptyText
    authorization_evidence_sha256: Sha256
    trust_anchor_sha256: Sha256
    authorization_reason: NonEmptyText
    authorized_at: datetime
    expires_at: datetime
    predecessor_event_sha256: Sha256 | None = None
    ancestor_event_sha256s: tuple[Sha256, ...] = Field(max_length=1023)
    rollback_target_event_sha256: Sha256 | None = None
    admission_state: Literal["active", "revoked"]
    technical_review_state: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    technical_intended_use: Literal[
        "assisted_precheck_not_for_production_decision"
    ] = "assisted_precheck_not_for_production_decision"
    technical_baseline_grants_production_authority: Literal[False] = False
    production_execution_authorized: bool
    provider_dispatch_performed: Literal[False] = False
    event_sha256: Sha256

    @field_validator("authorized_at", "expires_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("production admission timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFiveProviderProductionAdmissionEvent:
        if not self.authorized_by.startswith("human:") or any(
            character.isspace() for character in self.authorized_by
        ):
            raise ValueError("production admission authority must use a human identity")
        if self.event_id != f"{self.run_id}-production-admission-{self.event_version}":
            raise ValueError("production admission event ID is inconsistent")
        if self.target.tenant_id != self.tenant_id or self.target.run_id != self.run_id:
            raise ValueError("production admission event target identity differs")
        if self.event_version == 1:
            if (
                self.event_kind != "promotion"
                or self.predecessor_event_sha256 is not None
                or self.ancestor_event_sha256s
                or self.rollback_target_event_sha256 is not None
            ):
                raise ValueError("initial production admission event is invalid")
        elif (
            self.predecessor_event_sha256 is None
            or len(self.ancestor_event_sha256s) != self.event_version - 1
            or self.ancestor_event_sha256s[-1] != self.predecessor_event_sha256
        ):
            raise ValueError("production admission predecessor is invalid")
        if self.event_kind == "revocation":
            if (
                self.admission_state != "revoked"
                or self.production_execution_authorized
                or self.rollback_target_event_sha256 is not None
            ):
                raise ValueError("production admission revocation is invalid")
        else:
            if (
                self.admission_state != "active"
                or not self.production_execution_authorized
                or self.expires_at <= self.authorized_at
            ):
                raise ValueError("production admission expiry must follow authorization time")
            if self.event_kind == "rollback":
                if self.rollback_target_event_sha256 not in set(
                    self.ancestor_event_sha256s
                ):
                    raise ValueError("production admission rollback target is not an ancestor")
            elif self.rollback_target_event_sha256 is not None:
                raise ValueError("only production rollback may name a rollback target")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"event_sha256"}),
            "event_sha256",
        )
        if self.event_sha256 != expected:
            raise ValueError("production admission event fingerprint is invalid")
        return self


class ChongqingFiveProviderProductionAdmissionHistory(_FrozenModel):
    """Append-only lifecycle current for one five-Provider run."""

    schema_id: ClassVar[str] = (
        "gda.chongqing-five-provider-production-admission-history.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    events: tuple[ChongqingFiveProviderProductionAdmissionEvent, ...] = Field(
        min_length=1,
        max_length=1024,
    )
    current_event_sha256: Sha256
    admission_state: Literal["active", "revoked"]
    technical_baseline_grants_production_authority: Literal[False] = False
    production_execution_authorized: bool
    provider_dispatch_performed: Literal[False] = False
    history_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFiveProviderProductionAdmissionHistory:
        versions = tuple(range(1, len(self.events) + 1))
        if tuple(event.event_version for event in self.events) != versions:
            raise ValueError("production admission event versions must be contiguous")
        event_hashes = tuple(event.event_sha256 for event in self.events)
        if len(set(event_hashes)) != len(event_hashes):
            raise ValueError("production admission events must be unique")
        for index, event in enumerate(self.events):
            if (
                event.tenant_id != self.tenant_id
                or event.run_id != self.run_id
                or event.ancestor_event_sha256s != event_hashes[:index]
                or (
                    index > 0
                    and event.predecessor_event_sha256 != event_hashes[index - 1]
                )
                or (
                    index > 0
                    and event.authorized_at < self.events[index - 1].authorized_at
                )
            ):
                raise ValueError("production admission history is inconsistent")
            if index == 0:
                continue
            previous = self.events[index - 1]
            if previous.admission_state == "active":
                if event.event_kind != "revocation" or event.target != previous.target:
                    raise ValueError("active production admission must be revoked first")
            elif event.event_kind not in {"promotion", "rollback"}:
                raise ValueError("revoked production admission requires a new grant")
            if event.event_kind == "rollback":
                target_event = next(
                    (
                        item
                        for item in self.events[:index]
                        if item.event_sha256 == event.rollback_target_event_sha256
                    ),
                    None,
                )
                if (
                    target_event is None
                    or target_event.admission_state != "active"
                    or event.target != target_event.target
                ):
                    raise ValueError("production admission rollback target is invalid")
        current = self.events[-1]
        if (
            self.current_event_sha256 != current.event_sha256
            or self.admission_state != current.admission_state
            or self.production_execution_authorized
            != current.production_execution_authorized
        ):
            raise ValueError("production admission history current event differs")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"history_sha256"}),
            "history_sha256",
        )
        if self.history_sha256 != expected:
            raise ValueError("production admission history fingerprint is invalid")
        return self

    @property
    def current_event(self) -> ChongqingFiveProviderProductionAdmissionEvent:
        return self.events[-1]

    def authorizes(
        self,
        target: ChongqingFiveProviderProductionAdmissionTarget,
        *,
        evaluated_at: datetime,
    ) -> bool:
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("production admission evaluation time must be timezone-aware")
        evaluated_at = evaluated_at.astimezone(UTC)
        current = self.current_event
        return (
            current.target == target
            and current.admission_state == "active"
            and current.production_execution_authorized
            and current.authorized_at <= evaluated_at < current.expires_at
        )


def build_chongqing_five_provider_production_admission_target(
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    deployment_binding: ChongqingFederatedCompensationDeploymentBinding,
    profile_release_binding: ChongqingSourceSelectionProfileExecutionReleaseBinding,
    rule_current_binding: FederatedProjectionCompensationDispatchRuleCurrentBinding,
    *,
    request_bundle_sha256: str,
) -> ChongqingFiveProviderProductionAdmissionTarget:
    """Seal one exact technical chain without deriving an authorization decision."""

    try:
        intent = FederatedProjectionCompensationDispatchIntent.model_validate(
            intent.model_dump(mode="python")
        )
        plan_set = FederatedProjectionCompensationProviderPlanSet.model_validate(
            plan_set.model_dump(mode="python")
        )
        materialization = FederatedProjectionCompensationProviderMaterializationSet.model_validate(
            materialization.model_dump(mode="python")
        )
        deployment_binding = ChongqingFederatedCompensationDeploymentBinding.model_validate(
            deployment_binding.model_dump(mode="python")
        )
        profile_release_binding = (
            ChongqingSourceSelectionProfileExecutionReleaseBinding.model_validate(
                profile_release_binding.model_dump(mode="python")
            )
        )
        rule_current_binding = (
            FederatedProjectionCompensationDispatchRuleCurrentBinding.model_validate(
                rule_current_binding.model_dump(mode="python")
            )
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ChongqingFiveProviderProductionAdmissionError(
            "production admission target input violates a sealed contract"
        ) from exc

    identities = (
        plan_set.tenant_id,
        materialization.tenant_id,
        deployment_binding.tenant_id,
        profile_release_binding.tenant_id,
        rule_current_binding.tenant_id,
    )
    runs = (
        plan_set.run_id,
        materialization.run_id,
        deployment_binding.run_id,
        profile_release_binding.run_id,
        rule_current_binding.run_id,
    )
    if (
        any(item != intent.tenant_id for item in identities)
        or any(item != intent.run_id for item in runs)
        or plan_set.dispatch_intent_sha256 != intent.dispatch_intent_sha256
        or materialization.plan_set_sha256 != plan_set.plan_set_sha256
        or deployment_binding.dispatch_intent_sha256 != intent.dispatch_intent_sha256
        or deployment_binding.plan_set_sha256 != plan_set.plan_set_sha256
        or deployment_binding.materialization_set_sha256
        != materialization.materialization_set_sha256
        or profile_release_binding.deployment_binding_sha256
        != deployment_binding.deployment_binding_sha256
        or rule_current_binding.dispatch_intent_sha256 != intent.dispatch_intent_sha256
        or rule_current_binding.proposal_sha256 != intent.proposal_sha256
        or rule_current_binding.candidate_sha256 != intent.candidate_sha256
        or rule_current_binding.production_execution_authorized
        or profile_release_binding.production_execution_authorized
    ):
        raise ChongqingFiveProviderProductionAdmissionError(
            "production admission target chain differs"
        )

    values = {
        "tenant_id": intent.tenant_id,
        "run_id": intent.run_id,
        "proposal_sha256": intent.proposal_sha256,
        "candidate_sha256": intent.candidate_sha256,
        "dispatch_intent_sha256": intent.dispatch_intent_sha256,
        "plan_set_sha256": plan_set.plan_set_sha256,
        "materialization_set_sha256": materialization.materialization_set_sha256,
        "deployment_binding_sha256": deployment_binding.deployment_binding_sha256,
        "request_bundle_sha256": request_bundle_sha256,
        "execution_release_binding_sha256": (
            profile_release_binding.execution_release_binding_sha256
        ),
        "active_profile_release_sha256": profile_release_binding.active_release_sha256,
        "profile_release_history_sha256": profile_release_binding.release_history_sha256,
        "source_selection_profile_sha256": (
            profile_release_binding.source_selection_profile_sha256
        ),
        "rule_current_binding_sha256": (
            rule_current_binding.rule_current_binding_sha256
        ),
        "rule_authority_evidence_sha256": (
            rule_current_binding.rule_authority_evidence_sha256
        ),
        "rule_assessment_sha256": rule_current_binding.rule_assessment_sha256,
        "approved_rule_contract_sha256s": tuple(
            sorted(rule.contract_sha256 for rule in rule_current_binding.approved_rules)
        ),
        "technical_review_state": "technical_baseline_unreviewed",
        "technical_intended_use": "assisted_precheck_not_for_production_decision",
        "technical_baseline_grants_production_authority": False,
    }
    try:
        return ChongqingFiveProviderProductionAdmissionTarget(
            **values,
            target_sha256=_fingerprint(
                ChongqingFiveProviderProductionAdmissionTarget.schema_id,
                values,
                "target_sha256",
            ),
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise ChongqingFiveProviderProductionAdmissionError(
            "production admission target cannot be sealed"
        ) from exc


def _event(
    *,
    history: ChongqingFiveProviderProductionAdmissionHistory | None,
    target: ChongqingFiveProviderProductionAdmissionTarget,
    event_kind: Literal["promotion", "revocation", "rollback"],
    authorized_by: str,
    authorization_evidence_sha256: str,
    trust_anchor_sha256: str,
    authorization_reason: str,
    authorized_at: datetime,
    expires_at: datetime,
    rollback_target_event_sha256: str | None = None,
) -> ChongqingFiveProviderProductionAdmissionEvent:
    events = () if history is None else history.events
    version = len(events) + 1
    values = {
        "event_id": f"{target.run_id}-production-admission-{version}",
        "tenant_id": target.tenant_id,
        "run_id": target.run_id,
        "event_version": version,
        "event_kind": event_kind,
        "target": target,
        "authorized_by": authorized_by,
        "authorization_evidence_sha256": authorization_evidence_sha256,
        "trust_anchor_sha256": trust_anchor_sha256,
        "authorization_reason": authorization_reason,
        "authorized_at": authorized_at,
        "expires_at": expires_at,
        "predecessor_event_sha256": None if not events else events[-1].event_sha256,
        "ancestor_event_sha256s": tuple(item.event_sha256 for item in events),
        "rollback_target_event_sha256": rollback_target_event_sha256,
        "admission_state": "revoked" if event_kind == "revocation" else "active",
        "technical_review_state": "technical_baseline_unreviewed",
        "technical_intended_use": "assisted_precheck_not_for_production_decision",
        "technical_baseline_grants_production_authority": False,
        "production_execution_authorized": event_kind != "revocation",
        "provider_dispatch_performed": False,
    }
    return ChongqingFiveProviderProductionAdmissionEvent(
        **values,
        event_sha256=_fingerprint(
            ChongqingFiveProviderProductionAdmissionEvent.schema_id,
            values,
            "event_sha256",
        ),
    )


def _history(
    events: tuple[ChongqingFiveProviderProductionAdmissionEvent, ...],
) -> ChongqingFiveProviderProductionAdmissionHistory:
    current = events[-1]
    values = {
        "tenant_id": current.tenant_id,
        "run_id": current.run_id,
        "events": events,
        "current_event_sha256": current.event_sha256,
        "admission_state": current.admission_state,
        "technical_baseline_grants_production_authority": False,
        "production_execution_authorized": current.production_execution_authorized,
        "provider_dispatch_performed": False,
    }
    return ChongqingFiveProviderProductionAdmissionHistory(
        **values,
        history_sha256=_fingerprint(
            ChongqingFiveProviderProductionAdmissionHistory.schema_id,
            values,
            "history_sha256",
        ),
    )


def build_initial_chongqing_five_provider_production_admission_history(
    target: ChongqingFiveProviderProductionAdmissionTarget,
    *,
    authorized_by: str,
    authorization_evidence_sha256: str,
    trust_anchor_sha256: str,
    authorization_reason: str,
    authorized_at: datetime,
    expires_at: datetime,
) -> ChongqingFiveProviderProductionAdmissionHistory:
    """Create v1 only from an explicit, bounded human promotion decision."""

    event = _event(
        history=None,
        target=target,
        event_kind="promotion",
        authorized_by=authorized_by,
        authorization_evidence_sha256=authorization_evidence_sha256,
        trust_anchor_sha256=trust_anchor_sha256,
        authorization_reason=authorization_reason,
        authorized_at=authorized_at,
        expires_at=expires_at,
    )
    return _history((event,))


def revoke_chongqing_five_provider_production_admission(
    history: ChongqingFiveProviderProductionAdmissionHistory,
    *,
    authorized_by: str,
    authorization_evidence_sha256: str,
    trust_anchor_sha256: str,
    authorization_reason: str,
    authorized_at: datetime,
) -> ChongqingFiveProviderProductionAdmissionHistory:
    """Append a fail-closed revocation without changing prior decisions."""

    history = ChongqingFiveProviderProductionAdmissionHistory.model_validate(
        history.model_dump(mode="python")
    )
    current = history.current_event
    if current.admission_state != "active":
        raise ChongqingFiveProviderProductionAdmissionError(
            "only an active production admission can be revoked"
        )
    event = _event(
        history=history,
        target=current.target,
        event_kind="revocation",
        authorized_by=authorized_by,
        authorization_evidence_sha256=authorization_evidence_sha256,
        trust_anchor_sha256=trust_anchor_sha256,
        authorization_reason=authorization_reason,
        authorized_at=authorized_at,
        expires_at=current.expires_at,
    )
    return _history((*history.events, event))


def promote_chongqing_five_provider_production_admission(
    history: ChongqingFiveProviderProductionAdmissionHistory,
    target: ChongqingFiveProviderProductionAdmissionTarget,
    *,
    authorized_by: str,
    authorization_evidence_sha256: str,
    trust_anchor_sha256: str,
    authorization_reason: str,
    authorized_at: datetime,
    expires_at: datetime,
) -> ChongqingFiveProviderProductionAdmissionHistory:
    """Append a new explicit grant after the previous grant was revoked."""

    history = ChongqingFiveProviderProductionAdmissionHistory.model_validate(
        history.model_dump(mode="python")
    )
    if (
        history.current_event.admission_state != "revoked"
        or target.tenant_id != history.tenant_id
        or target.run_id != history.run_id
    ):
        raise ChongqingFiveProviderProductionAdmissionError(
            "new production promotion requires a revoked same-run history"
        )
    event = _event(
        history=history,
        target=target,
        event_kind="promotion",
        authorized_by=authorized_by,
        authorization_evidence_sha256=authorization_evidence_sha256,
        trust_anchor_sha256=trust_anchor_sha256,
        authorization_reason=authorization_reason,
        authorized_at=authorized_at,
        expires_at=expires_at,
    )
    return _history((*history.events, event))


def rollback_chongqing_five_provider_production_admission(
    history: ChongqingFiveProviderProductionAdmissionHistory,
    target_event_sha256: str,
    *,
    authorized_by: str,
    authorization_evidence_sha256: str,
    trust_anchor_sha256: str,
    authorization_reason: str,
    authorized_at: datetime,
    expires_at: datetime,
) -> ChongqingFiveProviderProductionAdmissionHistory:
    """Append a new bounded grant for an earlier admitted target."""

    history = ChongqingFiveProviderProductionAdmissionHistory.model_validate(
        history.model_dump(mode="python")
    )
    target_event = next(
        (
            event
            for event in history.events
            if event.event_sha256 == target_event_sha256
        ),
        None,
    )
    if (
        history.current_event.admission_state != "revoked"
        or target_event is None
        or target_event.admission_state != "active"
    ):
        raise ChongqingFiveProviderProductionAdmissionError(
            "production rollback requires a revoked history and prior active grant"
        )
    event = _event(
        history=history,
        target=target_event.target,
        event_kind="rollback",
        authorized_by=authorized_by,
        authorization_evidence_sha256=authorization_evidence_sha256,
        trust_anchor_sha256=trust_anchor_sha256,
        authorization_reason=authorization_reason,
        authorized_at=authorized_at,
        expires_at=expires_at,
        rollback_target_event_sha256=target_event.event_sha256,
    )
    return _history((*history.events, event))


__all__ = [
    "ChongqingFiveProviderProductionAdmissionCurrentReader",
    "ChongqingFiveProviderProductionAdmissionError",
    "ChongqingFiveProviderProductionAdmissionEvent",
    "ChongqingFiveProviderProductionAdmissionHistory",
    "ChongqingFiveProviderProductionAdmissionTarget",
    "build_chongqing_five_provider_production_admission_target",
    "build_initial_chongqing_five_provider_production_admission_history",
    "promote_chongqing_five_provider_production_admission",
    "revoke_chongqing_five_provider_production_admission",
    "rollback_chongqing_five_provider_production_admission",
]
