"""Version and rollback governance for Chongqing source-selection profiles.

The existing scenario profile is an executable technical preflight input. This
module adds an immutable publication history around those sealed profiles. A
publication remains unreviewed and never grants customer or production
authorization.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cross_store_projection_compensation_chongqing_deployment import (
    ChongqingFederatedCompensationDeploymentBinding,
)
from .cross_store_projection_compensation_chongqing_source_selection_profile import (
    ChongqingFederatedCompensationProfiledSourceLineageBinding,
    ChongqingFederatedCompensationSourceSelectionProfile,
)
from .platform_contracts import NonEmptyText, Sha256, TenantId, canonical_json_fingerprint


class ChongqingSourceSelectionProfileReleaseError(ValueError):
    """A profile release history cannot be safely published."""


class ChongqingSourceSelectionProfileReleaseCurrentReader(Protocol):
    """Tenant-scoped release-history read port used before Provider callbacks."""

    tenant_id: str

    def release_history_current(
        self,
        profile_id: str,
        scenario_id: str,
    ) -> ChongqingSourceSelectionProfileReleaseHistory | None:
        ...


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": _json_ready(payload)})


class ChongqingSourceSelectionProfileRelease(_FrozenModel):
    """One immutable technical publication in a scenario-profile history."""

    schema_id: ClassVar[str] = "gda.chongqing-source-selection-profile-release.v1"
    release_id: NonEmptyText
    tenant_id: TenantId
    profile_id: NonEmptyText
    scenario_id: Literal["heping_review", "banzhu_adjustment"]
    release_version: int = Field(ge=1, le=1024)
    source_selection_profile_sha256: Sha256
    source_catalog_sha256: Sha256
    scenario_evidence_sha256: Sha256
    required_source_roles: tuple[NonEmptyText, ...] = Field(min_length=1, max_length=16)
    event_kind: Literal["initial_publication", "profile_change", "rollback"]
    predecessor_release_sha256: Sha256 | None = None
    ancestor_release_sha256s: tuple[Sha256, ...] = Field(max_length=1023)
    rollback_target_release_sha256: Sha256 | None = None
    change_reason: NonEmptyText
    publication_state: Literal["technical_candidate_published_unreviewed"] = (
        "technical_candidate_published_unreviewed"
    )
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    customer_approval_present: Literal[False] = False
    production_execution_authorized: Literal[False] = False
    authority_write_performed: Literal[False] = False
    release_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingSourceSelectionProfileRelease:
        expected_release_id = f"{self.profile_id}-release-{self.release_version}"
        if self.release_id != expected_release_id:
            raise ValueError("source-selection profile release ID is inconsistent")
        if self.required_source_roles != tuple(sorted(set(self.required_source_roles))):
            raise ValueError("source-selection profile release roles must be unique and sorted")
        if len(set(self.ancestor_release_sha256s)) != len(self.ancestor_release_sha256s):
            raise ValueError("source-selection profile release ancestors must be unique")
        if self.release_version == 1:
            if (
                self.event_kind != "initial_publication"
                or self.predecessor_release_sha256 is not None
                or self.ancestor_release_sha256s
                or self.rollback_target_release_sha256 is not None
            ):
                raise ValueError("initial source-selection profile release is invalid")
        else:
            if (
                self.event_kind == "initial_publication"
                or self.predecessor_release_sha256 is None
                or len(self.ancestor_release_sha256s) != self.release_version - 1
                or self.ancestor_release_sha256s[-1] != self.predecessor_release_sha256
            ):
                raise ValueError("source-selection profile release predecessor is invalid")
            if self.event_kind == "rollback":
                if self.rollback_target_release_sha256 not in set(self.ancestor_release_sha256s):
                    raise ValueError("rollback target is not an ancestor release")
            elif self.rollback_target_release_sha256 is not None:
                raise ValueError("only rollback releases may name a rollback target")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"release_sha256"}),
            "release_sha256",
        )
        if self.release_sha256 != expected:
            raise ValueError("source-selection profile release fingerprint is invalid")
        return self


class ChongqingSourceSelectionProfileReleaseHistory(_FrozenModel):
    """Ordered, append-only technical publication history for one scenario."""

    schema_id: ClassVar[str] = "gda.chongqing-source-selection-profile-release-history.v1"
    tenant_id: TenantId
    profile_id: NonEmptyText
    scenario_id: Literal["heping_review", "banzhu_adjustment"]
    releases: tuple[ChongqingSourceSelectionProfileRelease, ...] = Field(
        min_length=1,
        max_length=1024,
    )
    active_release_sha256: Sha256
    history_state: Literal["technical_history_active_unreviewed"] = (
        "technical_history_active_unreviewed"
    )
    customer_approval_present: Literal[False] = False
    production_execution_authorized: Literal[False] = False
    authority_write_performed: Literal[False] = False
    history_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingSourceSelectionProfileReleaseHistory:
        expected_versions = tuple(range(1, len(self.releases) + 1))
        if tuple(item.release_version for item in self.releases) != expected_versions:
            raise ValueError("source-selection profile releases must be contiguous")
        release_hashes = tuple(item.release_sha256 for item in self.releases)
        if len(set(release_hashes)) != len(release_hashes):
            raise ValueError("source-selection profile releases must be unique")
        for index, release in enumerate(self.releases):
            if (
                release.tenant_id != self.tenant_id
                or release.profile_id != self.profile_id
                or release.scenario_id != self.scenario_id
                or release.ancestor_release_sha256s != release_hashes[:index]
                or (index > 0 and release.predecessor_release_sha256 != release_hashes[index - 1])
            ):
                raise ValueError("source-selection profile release history is inconsistent")
        if self.active_release_sha256 != release_hashes[-1]:
            raise ValueError("active source-selection profile release is not history tail")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"history_sha256"}),
            "history_sha256",
        )
        if self.history_sha256 != expected:
            raise ValueError("source-selection profile release history fingerprint is invalid")
        return self

    @property
    def active_release(self) -> ChongqingSourceSelectionProfileRelease:
        return self.releases[-1]


class ChongqingSourceSelectionProfileExecutionReleaseBinding(_FrozenModel):
    """Bind one execution preflight to the active sealed profile release."""

    schema_id: ClassVar[str] = "gda.chongqing-source-selection-profile-execution-release-binding.v1"
    tenant_id: TenantId
    run_id: NonEmptyText
    deployment_binding_sha256: Sha256
    source_catalog_sha256: Sha256
    source_selection_profile_sha256: Sha256
    profiled_source_lineage_binding_sha256: Sha256
    active_release_version: int = Field(ge=1, le=1024)
    active_release_sha256: Sha256
    release_history_sha256: Sha256
    binding_state: Literal["active_technical_release_bound_pending_provider_execution"] = (
        "active_technical_release_bound_pending_provider_execution"
    )
    customer_approval_present: Literal[False] = False
    production_execution_authorized: Literal[False] = False
    provider_dispatch_performed: Literal[False] = False
    authority_write_performed: Literal[False] = False
    execution_release_binding_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingSourceSelectionProfileExecutionReleaseBinding:
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(
                mode="json",
                exclude={"execution_release_binding_sha256"},
            ),
            "execution_release_binding_sha256",
        )
        if self.execution_release_binding_sha256 != expected:
            raise ValueError("source-selection execution release binding is invalid")
        return self


def _validated_profile(
    profile: ChongqingFederatedCompensationSourceSelectionProfile,
) -> ChongqingFederatedCompensationSourceSelectionProfile:
    try:
        return ChongqingFederatedCompensationSourceSelectionProfile.model_validate(
            profile.model_dump(mode="python")
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ChongqingSourceSelectionProfileReleaseError(
            "source-selection profile violates its sealed contract"
        ) from exc


def _validated_history(
    history: ChongqingSourceSelectionProfileReleaseHistory,
) -> ChongqingSourceSelectionProfileReleaseHistory:
    try:
        return ChongqingSourceSelectionProfileReleaseHistory.model_validate(
            history.model_dump(mode="python")
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ChongqingSourceSelectionProfileReleaseError(
            "source-selection profile release history violates its sealed contract"
        ) from exc


def build_chongqing_source_selection_profile_execution_release_binding(
    history: ChongqingSourceSelectionProfileReleaseHistory,
    profile: ChongqingFederatedCompensationSourceSelectionProfile,
    deployment_binding: ChongqingFederatedCompensationDeploymentBinding,
    profiled_source_lineage_binding: ChongqingFederatedCompensationProfiledSourceLineageBinding,
) -> ChongqingSourceSelectionProfileExecutionReleaseBinding:
    """Require the execution profile to equal the history's active release."""

    history = _validated_history(history)
    profile = _validated_profile(profile)
    try:
        deployment_binding = ChongqingFederatedCompensationDeploymentBinding.model_validate(
            deployment_binding.model_dump(mode="python")
        )
        profiled_source_lineage_binding = (
            ChongqingFederatedCompensationProfiledSourceLineageBinding.model_validate(
                profiled_source_lineage_binding.model_dump(mode="python")
            )
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ChongqingSourceSelectionProfileReleaseError(
            "source-selection execution release input violates a sealed contract"
        ) from exc

    active = history.active_release
    if (
        history.tenant_id != deployment_binding.tenant_id
        or history.profile_id != profile.profile_id
        or history.scenario_id != profile.scenario_id
        or active.source_selection_profile_sha256 != profile.profile_sha256
        or active.source_catalog_sha256 != profile.source_catalog_sha256
        or active.source_catalog_sha256 != deployment_binding.source_catalog_sha256
        or active.scenario_evidence_sha256 != profile.scenario_evidence_sha256
        or active.required_source_roles != profile.required_source_roles
        or profiled_source_lineage_binding.tenant_id != deployment_binding.tenant_id
        or profiled_source_lineage_binding.run_id != deployment_binding.run_id
        or profiled_source_lineage_binding.deployment_binding_sha256
        != deployment_binding.deployment_binding_sha256
        or profiled_source_lineage_binding.source_catalog_sha256
        != deployment_binding.source_catalog_sha256
        or profiled_source_lineage_binding.source_selection_profile_sha256 != profile.profile_sha256
    ):
        raise ChongqingSourceSelectionProfileReleaseError(
            "active source-selection profile release differs from execution inputs"
        )

    values = {
        "tenant_id": deployment_binding.tenant_id,
        "run_id": deployment_binding.run_id,
        "deployment_binding_sha256": deployment_binding.deployment_binding_sha256,
        "source_catalog_sha256": deployment_binding.source_catalog_sha256,
        "source_selection_profile_sha256": profile.profile_sha256,
        "profiled_source_lineage_binding_sha256": (
            profiled_source_lineage_binding.profiled_source_lineage_binding_sha256
        ),
        "active_release_version": active.release_version,
        "active_release_sha256": active.release_sha256,
        "release_history_sha256": history.history_sha256,
        "binding_state": "active_technical_release_bound_pending_provider_execution",
        "customer_approval_present": False,
        "production_execution_authorized": False,
        "provider_dispatch_performed": False,
        "authority_write_performed": False,
    }
    return ChongqingSourceSelectionProfileExecutionReleaseBinding(
        **values,
        execution_release_binding_sha256=_fingerprint(
            ChongqingSourceSelectionProfileExecutionReleaseBinding.schema_id,
            values,
            "execution_release_binding_sha256",
        ),
    )


def _release_values(
    profile: ChongqingFederatedCompensationSourceSelectionProfile,
    *,
    tenant_id: str,
    release_version: int,
    event_kind: Literal["initial_publication", "profile_change", "rollback"],
    predecessor_release_sha256: str | None,
    ancestor_release_sha256s: tuple[str, ...],
    rollback_target_release_sha256: str | None,
    change_reason: str,
) -> dict[str, Any]:
    return {
        "release_id": f"{profile.profile_id}-release-{release_version}",
        "tenant_id": tenant_id,
        "profile_id": profile.profile_id,
        "scenario_id": profile.scenario_id,
        "release_version": release_version,
        "source_selection_profile_sha256": profile.profile_sha256,
        "source_catalog_sha256": profile.source_catalog_sha256,
        "scenario_evidence_sha256": profile.scenario_evidence_sha256,
        "required_source_roles": profile.required_source_roles,
        "event_kind": event_kind,
        "predecessor_release_sha256": predecessor_release_sha256,
        "ancestor_release_sha256s": ancestor_release_sha256s,
        "rollback_target_release_sha256": rollback_target_release_sha256,
        "change_reason": change_reason,
        "publication_state": "technical_candidate_published_unreviewed",
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
        "customer_approval_present": False,
        "production_execution_authorized": False,
        "authority_write_performed": False,
    }


def _seal_release(values: dict[str, Any]) -> ChongqingSourceSelectionProfileRelease:
    try:
        return ChongqingSourceSelectionProfileRelease(
            **values,
            release_sha256=_fingerprint(
                ChongqingSourceSelectionProfileRelease.schema_id,
                values,
                "release_sha256",
            ),
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise ChongqingSourceSelectionProfileReleaseError(
            "source-selection profile release cannot be sealed"
        ) from exc


def _seal_history(
    releases: tuple[ChongqingSourceSelectionProfileRelease, ...],
) -> ChongqingSourceSelectionProfileReleaseHistory:
    active = releases[-1]
    values = {
        "tenant_id": active.tenant_id,
        "profile_id": active.profile_id,
        "scenario_id": active.scenario_id,
        "releases": releases,
        "active_release_sha256": active.release_sha256,
        "history_state": "technical_history_active_unreviewed",
        "customer_approval_present": False,
        "production_execution_authorized": False,
        "authority_write_performed": False,
    }
    try:
        return ChongqingSourceSelectionProfileReleaseHistory(
            **values,
            history_sha256=_fingerprint(
                ChongqingSourceSelectionProfileReleaseHistory.schema_id,
                values,
                "history_sha256",
            ),
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise ChongqingSourceSelectionProfileReleaseError(
            "source-selection profile release history cannot be sealed"
        ) from exc


def build_initial_chongqing_source_selection_profile_release_history(
    profile: ChongqingFederatedCompensationSourceSelectionProfile,
    *,
    tenant_id: str = "chongqing-customer",
    change_reason: str = "initial technical baseline publication",
) -> ChongqingSourceSelectionProfileReleaseHistory:
    """Publish version 1 without granting customer or production authorization."""

    profile = _validated_profile(profile)
    release = _seal_release(
        _release_values(
            profile,
            tenant_id=tenant_id,
            release_version=1,
            event_kind="initial_publication",
            predecessor_release_sha256=None,
            ancestor_release_sha256s=(),
            rollback_target_release_sha256=None,
            change_reason=change_reason,
        )
    )
    return _seal_history((release,))


def publish_chongqing_source_selection_profile_change(
    history: ChongqingSourceSelectionProfileReleaseHistory,
    profile: ChongqingFederatedCompensationSourceSelectionProfile,
    *,
    change_reason: str,
) -> ChongqingSourceSelectionProfileReleaseHistory:
    """Append a changed, sealed profile as the next technical publication."""

    history = _validated_history(history)
    profile = _validated_profile(profile)
    current = history.active_release
    if profile.profile_id != history.profile_id or profile.scenario_id != history.scenario_id:
        raise ChongqingSourceSelectionProfileReleaseError(
            "changed profile identity differs from release history"
        )
    if profile.profile_sha256 == current.source_selection_profile_sha256:
        raise ChongqingSourceSelectionProfileReleaseError(
            "unchanged profile cannot create a new release"
        )
    release = _seal_release(
        _release_values(
            profile,
            tenant_id=history.tenant_id,
            release_version=len(history.releases) + 1,
            event_kind="profile_change",
            predecessor_release_sha256=current.release_sha256,
            ancestor_release_sha256s=tuple(item.release_sha256 for item in history.releases),
            rollback_target_release_sha256=None,
            change_reason=change_reason,
        )
    )
    return _seal_history((*history.releases, release))


def rollback_chongqing_source_selection_profile_release(
    history: ChongqingSourceSelectionProfileReleaseHistory,
    target_release_sha256: str,
    target_profile: ChongqingFederatedCompensationSourceSelectionProfile,
    *,
    change_reason: str,
) -> ChongqingSourceSelectionProfileReleaseHistory:
    """Append a rollback publication that restores one earlier sealed profile."""

    history = _validated_history(history)
    target_profile = _validated_profile(target_profile)
    target = next(
        (item for item in history.releases[:-1] if item.release_sha256 == target_release_sha256),
        None,
    )
    if target is None:
        raise ChongqingSourceSelectionProfileReleaseError(
            "rollback target is not an earlier release in this history"
        )
    if (
        target_profile.profile_id != target.profile_id
        or target_profile.scenario_id != target.scenario_id
        or target_profile.profile_sha256 != target.source_selection_profile_sha256
        or target_profile.source_catalog_sha256 != target.source_catalog_sha256
        or target_profile.scenario_evidence_sha256 != target.scenario_evidence_sha256
        or target_profile.required_source_roles != target.required_source_roles
    ):
        raise ChongqingSourceSelectionProfileReleaseError(
            "rollback profile differs from target release"
        )
    if (
        target.source_selection_profile_sha256
        == history.active_release.source_selection_profile_sha256
    ):
        raise ChongqingSourceSelectionProfileReleaseError(
            "rollback target would not change the active profile"
        )
    current = history.active_release
    release = _seal_release(
        _release_values(
            target_profile,
            tenant_id=history.tenant_id,
            release_version=len(history.releases) + 1,
            event_kind="rollback",
            predecessor_release_sha256=current.release_sha256,
            ancestor_release_sha256s=tuple(item.release_sha256 for item in history.releases),
            rollback_target_release_sha256=target.release_sha256,
            change_reason=change_reason,
        )
    )
    return _seal_history((*history.releases, release))


__all__ = [
    "ChongqingSourceSelectionProfileExecutionReleaseBinding",
    "ChongqingSourceSelectionProfileRelease",
    "ChongqingSourceSelectionProfileReleaseCurrentReader",
    "ChongqingSourceSelectionProfileReleaseError",
    "ChongqingSourceSelectionProfileReleaseHistory",
    "build_chongqing_source_selection_profile_execution_release_binding",
    "build_initial_chongqing_source_selection_profile_release_history",
    "publish_chongqing_source_selection_profile_change",
    "rollback_chongqing_source_selection_profile_release",
]
