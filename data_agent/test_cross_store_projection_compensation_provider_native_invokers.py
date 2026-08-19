from __future__ import annotations

from typing import Any

import pytest

from data_agent.cross_store_projection_compensation_federated_run import (
    FederatedCompensationRunBinding,
    build_federated_compensation_run_bindings,
)
from data_agent.cross_store_projection_compensation_provider_native_invokers import (
    FederatedCompensationNativeInvokerConfigurationError,
    FederatedCompensationNativeInvokerValidationError,
    build_federated_compensation_lakehouse_native_invoker,
    build_federated_compensation_object_native_invoker,
    build_federated_compensation_provider_native_invoker_registry,
    build_federated_compensation_rdf_native_invoker,
    build_federated_compensation_vector_native_invoker,
)
from data_agent.cross_store_projection_consistency import ProjectionEngine
from data_agent.lakehouse_projection_executor import LakehouseProjectionRepairExecutor
from data_agent.object_projection_executor import ObjectProjectionRepairExecutor
from data_agent.platform_contracts import canonical_json_fingerprint
from data_agent.postgis_projection_executor import PostGISProjectionRepairExecutor
from data_agent.rdf_projection_executor import RDFProjectionRepairExecutor
from data_agent.test_cross_store_projection_compensation_lakehouse_adapter import (
    _chain as _lakehouse_chain,
)
from data_agent.test_cross_store_projection_compensation_object_adapter import (
    _chain as _object_chain,
)
from data_agent.test_cross_store_projection_compensation_postgis_adapter import (
    _chain as _postgis_chain,
)
from data_agent.test_cross_store_projection_compensation_rdf_adapter import (
    _chain as _rdf_chain,
)
from data_agent.test_cross_store_projection_compensation_vector_adapter import (
    _chain as _vector_chain,
)
from data_agent.test_cross_store_projection_compensation_vector_adapter import (
    _RecordingVectorExecutor,
)


class _NoCallPostGISExecutor(PostGISProjectionRepairExecutor):
    def __init__(self) -> None:
        pass


class _NoCallRDFExecutor(RDFProjectionRepairExecutor):
    def __init__(self) -> None:
        pass


class _NoCallObjectExecutor(ObjectProjectionRepairExecutor):
    def __init__(self) -> None:
        pass


class _NoCallLakehouseExecutor(LakehouseProjectionRepairExecutor):
    def __init__(self) -> None:
        pass


def _binding_for(chain: Any, engine: ProjectionEngine) -> FederatedCompensationRunBinding:
    return next(
        binding
        for binding in build_federated_compensation_run_bindings(
            chain.plan_set,
            chain.materialization,
        )
        if binding.target_engine is engine
    )


def _rebind(
    binding: FederatedCompensationRunBinding,
    **updates: Any,
) -> FederatedCompensationRunBinding:
    values = binding.model_dump(mode="json", exclude={"binding_sha256"})
    values.update(updates)
    return FederatedCompensationRunBinding(
        **values,
        binding_sha256=canonical_json_fingerprint(
            {"schema": FederatedCompensationRunBinding.schema_id, "data": values}
        ),
    )


def test_vector_native_invoker_revalidates_the_binding_before_provider_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _vector_chain(monkeypatch)
    binding = _binding_for(chain, ProjectionEngine.VECTOR)
    executor = _RecordingVectorExecutor(chain.target)
    invoker = build_federated_compensation_vector_native_invoker(
        chain.request,
        executor=executor,
    )

    result = invoker(binding)

    assert executor.execute_calls == 1
    assert result.tenant_id == binding.tenant_id
    assert result.provider_plan_sha256 == binding.provider_plan_sha256

    drifted = _rebind(binding, run_id="cq-different-run")
    with pytest.raises(
        FederatedCompensationNativeInvokerValidationError,
        match="run binding differs",
    ):
        invoker(drifted)
    assert executor.execute_calls == 1


def test_native_invoker_rejects_an_untyped_executor_before_callback_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _vector_chain(monkeypatch)

    with pytest.raises(
        FederatedCompensationNativeInvokerConfigurationError,
        match="governed executor",
    ):
        build_federated_compensation_vector_native_invoker(
            chain.request,
            executor=object(),  # type: ignore[arg-type]
        )


def test_hash_only_target_requests_validate_binding_before_provider_access(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = (
        (
            ProjectionEngine.RDF,
            _rdf_chain(tmp_path, monkeypatch),
            build_federated_compensation_rdf_native_invoker,
            _NoCallRDFExecutor(),
        ),
        (
            ProjectionEngine.OBJECT_STORE,
            _object_chain(tmp_path, monkeypatch),
            build_federated_compensation_object_native_invoker,
            _NoCallObjectExecutor(),
        ),
        (
            ProjectionEngine.LAKEHOUSE,
            _lakehouse_chain(monkeypatch),
            build_federated_compensation_lakehouse_native_invoker,
            _NoCallLakehouseExecutor(),
        ),
    )

    for engine, chain, builder, executor in cases:
        binding = _binding_for(chain, engine)
        invoker = builder(chain.request, executor=executor)

        with pytest.raises(
            FederatedCompensationNativeInvokerValidationError,
            match="run binding differs",
        ):
            invoker(_rebind(binding, run_id="cq-different-run"))


def test_registry_builder_requires_and_wires_all_five_native_provider_callbacks(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    postgis = _postgis_chain(monkeypatch)
    vector = _vector_chain(monkeypatch)
    rdf = _rdf_chain(tmp_path, monkeypatch)
    object_store = _object_chain(tmp_path, monkeypatch)
    lakehouse = _lakehouse_chain(monkeypatch)

    registry = build_federated_compensation_provider_native_invoker_registry(
        postgis_request=postgis.request,
        postgis_executor=_NoCallPostGISExecutor(),
        vector_request=vector.request,
        vector_executor=_RecordingVectorExecutor(vector.target),
        rdf_request=rdf.request,
        rdf_executor=_NoCallRDFExecutor(),
        object_request=object_store.request,
        object_executor=_NoCallObjectExecutor(),
        lakehouse_request=lakehouse.request,
        lakehouse_executor=_NoCallLakehouseExecutor(),
    )

    assert registry.engines == (
        ProjectionEngine.LAKEHOUSE,
        ProjectionEngine.OBJECT_STORE,
        ProjectionEngine.POSTGIS,
        ProjectionEngine.RDF,
        ProjectionEngine.VECTOR,
    )
