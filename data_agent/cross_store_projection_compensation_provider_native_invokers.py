"""Build sealed native Provider callbacks for one federated compensation run.

Each callback captures exactly one already-authorized mutation request and its
governed executor.  Before any adapter can reach a Provider, the callback
revalidates both the request and its supplied run binding.  This makes the
deployment wiring explicit without exposing provider configuration or writing
checkpoint/completion authority state.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .cross_store_projection_compensation_federated_run import (
    FederatedCompensationProviderInvokerRegistry,
    FederatedCompensationRunBinding,
    FederatedCompensationRunConfigurationError,
    FederatedCompensationRunValidationError,
)
from .cross_store_projection_compensation_lakehouse_adapter import (
    FederatedProjectionCompensationLakehouseMutationRequest,
    execute_federated_compensation_lakehouse_mutation,
)
from .cross_store_projection_compensation_object_adapter import (
    FederatedProjectionCompensationObjectMutationRequest,
    execute_federated_compensation_object_mutation,
)
from .cross_store_projection_compensation_postgis_adapter import (
    FederatedProjectionCompensationPostGISMutationRequest,
    execute_federated_compensation_postgis_mutation,
)
from .cross_store_projection_compensation_rdf_adapter import (
    FederatedProjectionCompensationRDFMutationRequest,
    execute_federated_compensation_rdf_mutation,
)
from .cross_store_projection_compensation_vector_adapter import (
    FederatedProjectionCompensationVectorMutationRequest,
    execute_federated_compensation_vector_mutation,
)
from .cross_store_projection_consistency import ProjectionEngine
from .lakehouse_projection_executor import LakehouseProjectionRepairExecutor
from .object_projection_executor import ObjectProjectionRepairExecutor
from .postgis_projection_executor import PostGISProjectionRepairExecutor
from .rdf_projection_executor import RDFProjectionRepairExecutor
from .vector_projection_executor import VectorProjectionRepairExecutor


class FederatedCompensationNativeInvokerError(RuntimeError):
    """A deployment-wired native Provider callback cannot safely proceed."""


class FederatedCompensationNativeInvokerConfigurationError(
    FederatedCompensationRunConfigurationError,
    FederatedCompensationNativeInvokerError,
):
    """A callback was not supplied the executor required for its Provider."""


class FederatedCompensationNativeInvokerValidationError(
    FederatedCompensationRunValidationError,
    FederatedCompensationNativeInvokerError,
):
    """A callback request or run binding differs from the sealed chain."""


RequestT = TypeVar("RequestT", bound=BaseModel)
ExecutorT = TypeVar("ExecutorT")


def _validated_request(
    request: RequestT,
    request_type: type[RequestT],
    *,
    provider_name: str,
) -> RequestT:
    if not isinstance(request, request_type):
        raise FederatedCompensationNativeInvokerValidationError(
            f"{provider_name} native invoker requires its sealed mutation request"
        )
    try:
        return request_type.model_validate(request.model_dump(mode="python"))
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedCompensationNativeInvokerValidationError(
            f"{provider_name} native invoker request violates its sealed contract"
        ) from exc


def _validated_binding(
    binding: FederatedCompensationRunBinding,
) -> FederatedCompensationRunBinding:
    if not isinstance(binding, FederatedCompensationRunBinding):
        raise FederatedCompensationNativeInvokerValidationError(
            "native invoker requires a sealed federated run binding"
        )
    try:
        return FederatedCompensationRunBinding.model_validate(
            binding.model_dump(mode="python")
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise FederatedCompensationNativeInvokerValidationError(
            "native invoker received an invalid federated run binding"
        ) from exc


def _verify_binding_matches_request(
    binding: FederatedCompensationRunBinding,
    request: BaseModel,
    *,
    expected_engine: ProjectionEngine,
    provider_name: str,
) -> None:
    """Compare the callback binding with every execution-chain identity field."""

    plan = request.execution_plan
    source_plan = plan.source_plan
    target = getattr(request, "target", None)
    request_target_ref = getattr(request, "target_ref", None)
    if target is not None:
        request_target_ref = target.target_ref
    expected_values = {
        "tenant_id": request.tenant_id,
        "run_id": request.run_id,
        "position": plan.position,
        "projection_id": source_plan.projection_id,
        "target_engine": expected_engine,
        "target_ref": source_plan.target_ref,
        "source_plan_sha256": source_plan.plan_sha256,
        "plan_binding_sha256": plan.plan_binding_sha256,
        "materialization_binding_sha256": plan.materialization_binding_sha256,
        "provider_plan_sha256": plan.provider_plan_sha256,
        "provider_idempotency_key": plan.provider_idempotency_key,
    }
    if source_plan.target_engine is not expected_engine:
        raise FederatedCompensationNativeInvokerValidationError(
            f"{provider_name} request has an unexpected target engine"
        )
    if request_target_ref != source_plan.target_ref:
        raise FederatedCompensationNativeInvokerValidationError(
            f"{provider_name} request target identity differs from its execution plan"
        )
    if target is not None and (
        target.tenant_id != request.tenant_id
        or target.projection_id != source_plan.projection_id
    ):
        raise FederatedCompensationNativeInvokerValidationError(
            f"{provider_name} request target identity differs from its execution plan"
        )
    if any(
        getattr(binding, field_name) != expected_value
        for field_name, expected_value in expected_values.items()
    ):
        raise FederatedCompensationNativeInvokerValidationError(
            f"{provider_name} run binding differs from its sealed mutation request"
        )


def _build_native_invoker(
    *,
    request: RequestT,
    request_type: type[RequestT],
    executor: ExecutorT,
    executor_type: type[ExecutorT],
    expected_engine: ProjectionEngine,
    provider_name: str,
    execute: Callable[[RequestT], BaseModel],
) -> Callable[[FederatedCompensationRunBinding], BaseModel]:
    if not isinstance(executor, executor_type):
        raise FederatedCompensationNativeInvokerConfigurationError(
            f"{provider_name} native invoker requires its governed executor"
        )
    sealed_request = _validated_request(
        request,
        request_type,
        provider_name=provider_name,
    )

    def invoke(binding: FederatedCompensationRunBinding) -> BaseModel:
        current_request = _validated_request(
            sealed_request,
            request_type,
            provider_name=provider_name,
        )
        current_binding = _validated_binding(binding)
        _verify_binding_matches_request(
            current_binding,
            current_request,
            expected_engine=expected_engine,
            provider_name=provider_name,
        )
        return execute(current_request)

    return invoke


def build_federated_compensation_postgis_native_invoker(
    request: FederatedProjectionCompensationPostGISMutationRequest,
    *,
    executor: PostGISProjectionRepairExecutor,
) -> Callable[[FederatedCompensationRunBinding], BaseModel]:
    """Bind one sealed PostGIS mutation request to its governed executor."""

    return _build_native_invoker(
        request=request,
        request_type=FederatedProjectionCompensationPostGISMutationRequest,
        executor=executor,
        executor_type=PostGISProjectionRepairExecutor,
        expected_engine=ProjectionEngine.POSTGIS,
        provider_name="PostGIS",
        execute=lambda current: execute_federated_compensation_postgis_mutation(
            current,
            executor=executor,
        ),
    )


def build_federated_compensation_vector_native_invoker(
    request: FederatedProjectionCompensationVectorMutationRequest,
    *,
    executor: VectorProjectionRepairExecutor,
) -> Callable[[FederatedCompensationRunBinding], BaseModel]:
    """Bind one sealed pgvector mutation request to its governed executor."""

    return _build_native_invoker(
        request=request,
        request_type=FederatedProjectionCompensationVectorMutationRequest,
        executor=executor,
        executor_type=VectorProjectionRepairExecutor,
        expected_engine=ProjectionEngine.VECTOR,
        provider_name="pgvector",
        execute=lambda current: execute_federated_compensation_vector_mutation(
            current,
            executor=executor,
        ),
    )


def build_federated_compensation_rdf_native_invoker(
    request: FederatedProjectionCompensationRDFMutationRequest,
    *,
    executor: RDFProjectionRepairExecutor,
) -> Callable[[FederatedCompensationRunBinding], BaseModel]:
    """Bind one sealed RDF mutation request to its governed executor."""

    return _build_native_invoker(
        request=request,
        request_type=FederatedProjectionCompensationRDFMutationRequest,
        executor=executor,
        executor_type=RDFProjectionRepairExecutor,
        expected_engine=ProjectionEngine.RDF,
        provider_name="RDF",
        execute=lambda current: execute_federated_compensation_rdf_mutation(
            current,
            executor=executor,
        ),
    )


def build_federated_compensation_object_native_invoker(
    request: FederatedProjectionCompensationObjectMutationRequest,
    *,
    executor: ObjectProjectionRepairExecutor,
) -> Callable[[FederatedCompensationRunBinding], BaseModel]:
    """Bind one sealed object-store mutation request to its governed executor."""

    return _build_native_invoker(
        request=request,
        request_type=FederatedProjectionCompensationObjectMutationRequest,
        executor=executor,
        executor_type=ObjectProjectionRepairExecutor,
        expected_engine=ProjectionEngine.OBJECT_STORE,
        provider_name="object-store",
        execute=lambda current: execute_federated_compensation_object_mutation(
            current,
            executor=executor,
        ),
    )


def build_federated_compensation_lakehouse_native_invoker(
    request: FederatedProjectionCompensationLakehouseMutationRequest,
    *,
    executor: LakehouseProjectionRepairExecutor,
) -> Callable[[FederatedCompensationRunBinding], BaseModel]:
    """Bind one sealed Lakehouse mutation request to its governed executor."""

    return _build_native_invoker(
        request=request,
        request_type=FederatedProjectionCompensationLakehouseMutationRequest,
        executor=executor,
        executor_type=LakehouseProjectionRepairExecutor,
        expected_engine=ProjectionEngine.LAKEHOUSE,
        provider_name="Lakehouse",
        execute=lambda current: execute_federated_compensation_lakehouse_mutation(
            current,
            executor=executor,
        ),
    )


def build_federated_compensation_provider_native_invoker_registry(
    *,
    postgis_request: FederatedProjectionCompensationPostGISMutationRequest,
    postgis_executor: PostGISProjectionRepairExecutor,
    vector_request: FederatedProjectionCompensationVectorMutationRequest,
    vector_executor: VectorProjectionRepairExecutor,
    rdf_request: FederatedProjectionCompensationRDFMutationRequest,
    rdf_executor: RDFProjectionRepairExecutor,
    object_request: FederatedProjectionCompensationObjectMutationRequest,
    object_executor: ObjectProjectionRepairExecutor,
    lakehouse_request: FederatedProjectionCompensationLakehouseMutationRequest,
    lakehouse_executor: LakehouseProjectionRepairExecutor,
) -> FederatedCompensationProviderInvokerRegistry:
    """Assemble the complete five-engine callback allowlist for one deployment."""

    return FederatedCompensationProviderInvokerRegistry(
        {
            ProjectionEngine.POSTGIS: build_federated_compensation_postgis_native_invoker(
                postgis_request,
                executor=postgis_executor,
            ),
            ProjectionEngine.VECTOR: build_federated_compensation_vector_native_invoker(
                vector_request,
                executor=vector_executor,
            ),
            ProjectionEngine.RDF: build_federated_compensation_rdf_native_invoker(
                rdf_request,
                executor=rdf_executor,
            ),
            ProjectionEngine.OBJECT_STORE: build_federated_compensation_object_native_invoker(
                object_request,
                executor=object_executor,
            ),
            ProjectionEngine.LAKEHOUSE: build_federated_compensation_lakehouse_native_invoker(
                lakehouse_request,
                executor=lakehouse_executor,
            ),
        }
    )


__all__ = [
    "FederatedCompensationNativeInvokerConfigurationError",
    "FederatedCompensationNativeInvokerError",
    "FederatedCompensationNativeInvokerValidationError",
    "build_federated_compensation_lakehouse_native_invoker",
    "build_federated_compensation_object_native_invoker",
    "build_federated_compensation_postgis_native_invoker",
    "build_federated_compensation_provider_native_invoker_registry",
    "build_federated_compensation_rdf_native_invoker",
    "build_federated_compensation_vector_native_invoker",
]
