"""Seal customer-supplied Chongqing scenario source-role selection profiles.

The customer demo identifies two scenarios but does not itself authorize a
production decision.  This module turns those supplied scenario boundaries into
technical-baseline source-role profiles.  A profile controls which catalog
source roles may appear in a run and requires all of its roles to be covered;
it does not infer a legal, expert, or customer approval decision.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cross_store_projection_compensation_chongqing_deployment import (
    ChongqingFederatedCompensationDeploymentBinding,
    ChongqingFederatedCompensationSourceCatalog,
)
from .cross_store_projection_compensation_chongqing_internal_execution import (
    ChongqingFederatedCompensationInternalExecutionPermitError,
    _ChongqingFederatedCompensationInternalExecutionPermit,
    _validate_chongqing_federated_compensation_internal_execution_permit,
)
from .cross_store_projection_compensation_chongqing_source_lineage import (
    ChongqingFederatedCompensationSourceLineageSet,
)
from .cross_store_projection_compensation_chongqing_source_lineage_execution import (
    ChongqingFederatedCompensationSourceLineageExecutionResult,
    execute_chongqing_federated_compensation_source_lineage_with_receipt_set,
)
from .cross_store_projection_compensation_dispatch import (
    FederatedProjectionCompensationDispatchIntent,
)
from .cross_store_projection_compensation_federated_run import (
    FederatedCompensationProviderInvokerRegistry,
)
from .cross_store_projection_compensation_provider_materialization import (
    FederatedProjectionCompensationProviderMaterializationSet,
)
from .cross_store_projection_compensation_provider_plan import (
    FederatedProjectionCompensationProviderPlanSet,
)
from .natural_resource_ontology_demo import DemoBundleError, NaturalResourceOntologyDemo
from .platform_contracts import NonEmptyText, Sha256, TenantId, canonical_json_fingerprint


class ChongqingFederatedCompensationSourceSelectionProfileError(ValueError):
    """A Chongqing technical source-selection profile cannot be safely sealed."""


class ChongqingFederatedCompensationSourceSelectionProfileExecutionError(RuntimeError):
    """A profile-bound source-lineage execution cannot safely proceed."""


class ChongqingFederatedCompensationSourceSelectionProfileExecutionValidationError(
    ChongqingFederatedCompensationSourceSelectionProfileExecutionError,
):
    """A submitted profile or its binding differs from the current sealed inputs."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


ScenarioId = Literal["heping_review", "banzhu_adjustment"]
ProfileId = Literal[
    "chongqing-heping-review-source-selection-baseline-v1",
    "chongqing-banzhu-adjustment-source-selection-baseline-v1",
]

_PROFILE_ID_BY_SCENARIO: dict[ScenarioId, ProfileId] = {
    "heping_review": "chongqing-heping-review-source-selection-baseline-v1",
    "banzhu_adjustment": "chongqing-banzhu-adjustment-source-selection-baseline-v1",
}
_SOURCE_ROLES_BY_SCENARIO: dict[ScenarioId, tuple[str, ...]] = {
    "heping_review": tuple(
        sorted(
            (
                "和平村规划地类",
                "建设用地管制区",
                "和平村重点项目台账",
                "生态保护红线",
                "历史文化保护要素",
                "地质灾害影响范围",
                "郁闭度大于0.7的林地",
            )
        )
    ),
    "banzhu_adjustment": tuple(sorted(("斑竹村规划地类", "斑竹村土地利用结构调整"))),
}


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


class ChongqingFederatedCompensationSourceSelectionProfile(_FrozenModel):
    """A supplied-demo scenario expressed as a hash-only source-role baseline."""

    schema_id: ClassVar[str] = (
        "gda.chongqing-federated-compensation-source-selection-profile.v1"
    )
    profile_id: ProfileId
    scenario_id: ScenarioId
    scenario_evidence_sha256: Sha256
    source_catalog_sha256: Sha256
    required_source_roles: tuple[NonEmptyText, ...] = Field(min_length=1, max_length=16)
    profile_state: Literal["customer_scenario_technical_baseline_unreviewed"] = (
        "customer_scenario_technical_baseline_unreviewed"
    )
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    profile_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFederatedCompensationSourceSelectionProfile:
        if self.profile_id != _PROFILE_ID_BY_SCENARIO[self.scenario_id]:
            raise ValueError("customer source selection profile ID differs from scenario")
        if self.required_source_roles != _SOURCE_ROLES_BY_SCENARIO[self.scenario_id]:
            raise ValueError("customer source selection profile roles differ from scenario")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"profile_sha256"}),
            "profile_sha256",
        )
        if self.profile_sha256 != expected:
            raise ValueError("customer source selection profile fingerprint is invalid")
        return self


class ChongqingFederatedCompensationProfiledSourceLineageBinding(_FrozenModel):
    """One source-lineage set restricted to a sealed customer scenario profile."""

    schema_id: ClassVar[str] = (
        "gda.chongqing-federated-compensation-profiled-source-lineage-binding.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    deployment_binding_sha256: Sha256
    source_catalog_sha256: Sha256
    source_selection_profile_sha256: Sha256
    source_lineage_set_sha256: Sha256
    selected_source_roles: tuple[NonEmptyText, ...] = Field(min_length=1, max_length=16)
    binding_state: Literal["customer_source_profile_bound_pending_provider_execution"] = (
        "customer_source_profile_bound_pending_provider_execution"
    )
    provider_dispatch_performed: Literal[False] = False
    checkpoint_authority_write_performed: Literal[False] = False
    compensation_completion_recorded: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    profiled_source_lineage_binding_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFederatedCompensationProfiledSourceLineageBinding:
        if self.selected_source_roles != tuple(sorted(set(self.selected_source_roles))):
            raise ValueError("profiled source lineage roles must be unique and sorted")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"profiled_source_lineage_binding_sha256"}),
            "profiled_source_lineage_binding_sha256",
        )
        if self.profiled_source_lineage_binding_sha256 != expected:
            raise ValueError("profiled source lineage binding fingerprint is invalid")
        return self


class ChongqingFederatedCompensationProfiledSourceLineageExecutionResult(_FrozenModel):
    """Execution evidence after source-lineage and scenario-profile preflight."""

    schema_id: ClassVar[str] = (
        "gda.chongqing-federated-compensation-profiled-source-lineage-execution-result.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    source_selection_profile_sha256: Sha256
    profiled_source_lineage_binding_sha256: Sha256
    source_lineage_execution: ChongqingFederatedCompensationSourceLineageExecutionResult
    source_selection_profile_preflight_performed: Literal[True] = True
    authority_admission_performed: Literal[False] = False
    checkpoint_authority_write_performed: Literal[False] = False
    compensation_completion_recorded: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    result_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFederatedCompensationProfiledSourceLineageExecutionResult:
        execution = self.source_lineage_execution
        if self.tenant_id != execution.tenant_id or self.run_id != execution.run_id:
            raise ValueError("profiled source lineage execution differs from source lineage run")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"result_sha256"}),
            "result_sha256",
        )
        if self.result_sha256 != expected:
            raise ValueError("profiled source lineage execution fingerprint is invalid")
        return self


def _validated_catalog(
    source_catalog: ChongqingFederatedCompensationSourceCatalog,
) -> ChongqingFederatedCompensationSourceCatalog:
    try:
        return ChongqingFederatedCompensationSourceCatalog.model_validate(
            source_catalog.model_dump(mode="python")
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ChongqingFederatedCompensationSourceSelectionProfileError(
            "customer source selection catalog violates a sealed contract"
        ) from exc


def _scenario_evidence(
    scenario: Mapping[str, Any],
    scenario_id: ScenarioId,
) -> str:
    if (
        scenario.get("id") != scenario_id
        or not isinstance(scenario.get("label"), str)
        or not isinstance(scenario.get("layers"), list)
        or not all(isinstance(layer, str) and layer for layer in scenario["layers"])
    ):
        raise ChongqingFederatedCompensationSourceSelectionProfileError(
            "Chongqing customer scenario baseline is incomplete"
        )
    return canonical_json_fingerprint(
        {
            "schema": "gda.chongqing-customer-scenario-evidence.v1",
            "scenario_id": scenario_id,
            "label": scenario["label"],
            "layers": scenario["layers"],
        }
    )


def build_chongqing_federated_compensation_source_selection_profile(
    source_catalog: ChongqingFederatedCompensationSourceCatalog,
    scenario_id: ScenarioId,
    *,
    bundle_dir: str | Path | None = None,
) -> ChongqingFederatedCompensationSourceSelectionProfile:
    """Build a technical source-role profile from one supplied customer scenario."""

    source_catalog = _validated_catalog(source_catalog)
    try:
        demo = NaturalResourceOntologyDemo(bundle_dir=bundle_dir)
    except DemoBundleError as exc:
        raise ChongqingFederatedCompensationSourceSelectionProfileError(
            "Chongqing customer scenario bundle cannot be verified"
        ) from exc
    raw_scenarios = demo.demo.get("scenarios")
    if not isinstance(raw_scenarios, list) or any(
        not isinstance(scenario, Mapping) for scenario in raw_scenarios
    ):
        raise ChongqingFederatedCompensationSourceSelectionProfileError(
            "Chongqing customer scenario bundle is incomplete"
        )
    scenario = next(
        (
            item
            for item in raw_scenarios
            if isinstance(item, Mapping) and item.get("id") == scenario_id
        ),
        None,
    )
    if scenario is None:
        raise ChongqingFederatedCompensationSourceSelectionProfileError(
            "requested Chongqing customer scenario is absent from the bundle"
        )
    required_source_roles = _SOURCE_ROLES_BY_SCENARIO[scenario_id]
    source_roles = {item.source_role for item in source_catalog.sources}
    if not set(required_source_roles).issubset(source_roles):
        raise ChongqingFederatedCompensationSourceSelectionProfileError(
            "Chongqing customer scenario profile references an absent catalog source role"
        )
    values = {
        "profile_id": _PROFILE_ID_BY_SCENARIO[scenario_id],
        "scenario_id": scenario_id,
        "scenario_evidence_sha256": _scenario_evidence(scenario, scenario_id),
        "source_catalog_sha256": source_catalog.source_catalog_sha256,
        "required_source_roles": required_source_roles,
        "profile_state": "customer_scenario_technical_baseline_unreviewed",
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    return ChongqingFederatedCompensationSourceSelectionProfile(
        **values,
        profile_sha256=_fingerprint(
            ChongqingFederatedCompensationSourceSelectionProfile.schema_id,
            values,
            "profile_sha256",
        ),
    )


def _validated_binding_inputs(
    source_catalog: ChongqingFederatedCompensationSourceCatalog,
    deployment_binding: ChongqingFederatedCompensationDeploymentBinding,
    profile: ChongqingFederatedCompensationSourceSelectionProfile,
    source_lineage_set: ChongqingFederatedCompensationSourceLineageSet,
) -> tuple[
    ChongqingFederatedCompensationSourceCatalog,
    ChongqingFederatedCompensationDeploymentBinding,
    ChongqingFederatedCompensationSourceSelectionProfile,
    ChongqingFederatedCompensationSourceLineageSet,
]:
    try:
        return (
            ChongqingFederatedCompensationSourceCatalog.model_validate(
                source_catalog.model_dump(mode="python")
            ),
            ChongqingFederatedCompensationDeploymentBinding.model_validate(
                deployment_binding.model_dump(mode="python")
            ),
            ChongqingFederatedCompensationSourceSelectionProfile.model_validate(
                profile.model_dump(mode="python")
            ),
            ChongqingFederatedCompensationSourceLineageSet.model_validate(
                source_lineage_set.model_dump(mode="python")
            ),
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ChongqingFederatedCompensationSourceSelectionProfileError(
            "profiled source lineage input violates a sealed contract"
        ) from exc


def build_chongqing_federated_compensation_profiled_source_lineage_binding(
    source_catalog: ChongqingFederatedCompensationSourceCatalog,
    deployment_binding: ChongqingFederatedCompensationDeploymentBinding,
    profile: ChongqingFederatedCompensationSourceSelectionProfile,
    source_lineage_set: ChongqingFederatedCompensationSourceLineageSet,
) -> ChongqingFederatedCompensationProfiledSourceLineageBinding:
    """Require a lineage set to completely and exclusively cover one scenario profile."""

    (
        source_catalog,
        deployment_binding,
        profile,
        source_lineage_set,
    ) = _validated_binding_inputs(
        source_catalog,
        deployment_binding,
        profile,
        source_lineage_set,
    )
    if (
        profile.source_catalog_sha256 != source_catalog.source_catalog_sha256
        or source_lineage_set.tenant_id != deployment_binding.tenant_id
        or source_lineage_set.run_id != deployment_binding.run_id
        or source_lineage_set.deployment_binding_sha256
        != deployment_binding.deployment_binding_sha256
        or source_lineage_set.source_catalog_sha256 != source_catalog.source_catalog_sha256
    ):
        raise ChongqingFederatedCompensationSourceSelectionProfileError(
            "profiled source lineage identities differ from the Chongqing deployment"
        )
    selected_source_roles = tuple(
        sorted(
            {
                source.source_role
                for item in source_lineage_set.items
                for source in item.customer_sources
            }
        )
    )
    if selected_source_roles != profile.required_source_roles:
        raise ChongqingFederatedCompensationSourceSelectionProfileError(
            "source lineage roles must exactly cover the customer scenario profile"
        )
    values = {
        "tenant_id": deployment_binding.tenant_id,
        "run_id": deployment_binding.run_id,
        "deployment_binding_sha256": deployment_binding.deployment_binding_sha256,
        "source_catalog_sha256": source_catalog.source_catalog_sha256,
        "source_selection_profile_sha256": profile.profile_sha256,
        "source_lineage_set_sha256": source_lineage_set.source_lineage_set_sha256,
        "selected_source_roles": selected_source_roles,
        "binding_state": "customer_source_profile_bound_pending_provider_execution",
        "provider_dispatch_performed": False,
        "checkpoint_authority_write_performed": False,
        "compensation_completion_recorded": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    return ChongqingFederatedCompensationProfiledSourceLineageBinding(
        **values,
        profiled_source_lineage_binding_sha256=_fingerprint(
            ChongqingFederatedCompensationProfiledSourceLineageBinding.schema_id,
            values,
            "profiled_source_lineage_binding_sha256",
        ),
    )


def _validated_execution_inputs(
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    source_catalog: ChongqingFederatedCompensationSourceCatalog,
    deployment_binding: ChongqingFederatedCompensationDeploymentBinding,
    profile: ChongqingFederatedCompensationSourceSelectionProfile,
    source_lineage_set: ChongqingFederatedCompensationSourceLineageSet,
    profiled_source_lineage_binding: ChongqingFederatedCompensationProfiledSourceLineageBinding,
) -> tuple[
    FederatedProjectionCompensationDispatchIntent,
    FederatedProjectionCompensationProviderPlanSet,
    FederatedProjectionCompensationProviderMaterializationSet,
    ChongqingFederatedCompensationSourceCatalog,
    ChongqingFederatedCompensationDeploymentBinding,
    ChongqingFederatedCompensationSourceSelectionProfile,
    ChongqingFederatedCompensationSourceLineageSet,
    ChongqingFederatedCompensationProfiledSourceLineageBinding,
]:
    try:
        return (
            FederatedProjectionCompensationDispatchIntent.model_validate(
                intent.model_dump(mode="python")
            ),
            FederatedProjectionCompensationProviderPlanSet.model_validate(
                plan_set.model_dump(mode="python")
            ),
            FederatedProjectionCompensationProviderMaterializationSet.model_validate(
                materialization.model_dump(mode="python")
            ),
            ChongqingFederatedCompensationSourceCatalog.model_validate(
                source_catalog.model_dump(mode="python")
            ),
            ChongqingFederatedCompensationDeploymentBinding.model_validate(
                deployment_binding.model_dump(mode="python")
            ),
            ChongqingFederatedCompensationSourceSelectionProfile.model_validate(
                profile.model_dump(mode="python")
            ),
            ChongqingFederatedCompensationSourceLineageSet.model_validate(
                source_lineage_set.model_dump(mode="python")
            ),
            ChongqingFederatedCompensationProfiledSourceLineageBinding.model_validate(
                profiled_source_lineage_binding.model_dump(mode="python")
            ),
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ChongqingFederatedCompensationSourceSelectionProfileExecutionValidationError(
            "profiled source lineage execution input violates a sealed contract"
        ) from exc


def execute_chongqing_federated_compensation_profiled_source_lineage_with_receipt_set(
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    source_catalog: ChongqingFederatedCompensationSourceCatalog,
    deployment_binding: ChongqingFederatedCompensationDeploymentBinding,
    profile: ChongqingFederatedCompensationSourceSelectionProfile,
    source_lineage_set: ChongqingFederatedCompensationSourceLineageSet,
    profiled_source_lineage_binding: ChongqingFederatedCompensationProfiledSourceLineageBinding,
    registry: FederatedCompensationProviderInvokerRegistry,
    *,
    bundle_dir: str | Path | None = None,
    execution_permit: (
        _ChongqingFederatedCompensationInternalExecutionPermit | None
    ) = None,
) -> ChongqingFederatedCompensationProfiledSourceLineageExecutionResult:
    """Internal primitive; direct calls fail closed without an exact run permit."""

    try:
        _validate_chongqing_federated_compensation_internal_execution_permit(
            execution_permit,
            intent=intent,
            registry=registry,
        )
    except ChongqingFederatedCompensationInternalExecutionPermitError as exc:
        raise ChongqingFederatedCompensationSourceSelectionProfileExecutionValidationError(
            "profiled source lineage internal execution permit cannot pass preflight"
        ) from exc

    (
        intent,
        plan_set,
        materialization,
        source_catalog,
        deployment_binding,
        profile,
        source_lineage_set,
        profiled_source_lineage_binding,
    ) = _validated_execution_inputs(
        intent,
        plan_set,
        materialization,
        source_catalog,
        deployment_binding,
        profile,
        source_lineage_set,
        profiled_source_lineage_binding,
    )
    try:
        expected_profile = (
            build_chongqing_federated_compensation_source_selection_profile(
                source_catalog,
                profile.scenario_id,
                bundle_dir=bundle_dir,
            )
        )
        expected_binding = (
            build_chongqing_federated_compensation_profiled_source_lineage_binding(
                source_catalog,
                deployment_binding,
                expected_profile,
                source_lineage_set,
            )
        )
    except ChongqingFederatedCompensationSourceSelectionProfileError as exc:
        raise ChongqingFederatedCompensationSourceSelectionProfileExecutionValidationError(
            "customer source selection profile cannot pass execution preflight"
        ) from exc
    if profile != expected_profile or profiled_source_lineage_binding != expected_binding:
        raise ChongqingFederatedCompensationSourceSelectionProfileExecutionValidationError(
            "customer source selection profile differs from current sealed inputs"
        )
    source_lineage_execution = (
        execute_chongqing_federated_compensation_source_lineage_with_receipt_set(
            intent,
            plan_set,
            materialization,
            source_catalog,
            deployment_binding,
            source_lineage_set,
            registry,
            execution_permit=execution_permit,
        )
    )
    values = {
        "tenant_id": source_lineage_execution.tenant_id,
        "run_id": source_lineage_execution.run_id,
        "source_selection_profile_sha256": profile.profile_sha256,
        "profiled_source_lineage_binding_sha256": (
            profiled_source_lineage_binding.profiled_source_lineage_binding_sha256
        ),
        "source_lineage_execution": source_lineage_execution,
        "source_selection_profile_preflight_performed": True,
        "authority_admission_performed": False,
        "checkpoint_authority_write_performed": False,
        "compensation_completion_recorded": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    return ChongqingFederatedCompensationProfiledSourceLineageExecutionResult(
        **values,
        result_sha256=_fingerprint(
            ChongqingFederatedCompensationProfiledSourceLineageExecutionResult.schema_id,
            values,
            "result_sha256",
        ),
    )


__all__ = [
    "ChongqingFederatedCompensationProfiledSourceLineageBinding",
    "ChongqingFederatedCompensationProfiledSourceLineageExecutionResult",
    "ChongqingFederatedCompensationSourceSelectionProfile",
    "ChongqingFederatedCompensationSourceSelectionProfileError",
    "ChongqingFederatedCompensationSourceSelectionProfileExecutionError",
    "ChongqingFederatedCompensationSourceSelectionProfileExecutionValidationError",
    "build_chongqing_federated_compensation_profiled_source_lineage_binding",
    "build_chongqing_federated_compensation_source_selection_profile",
]
