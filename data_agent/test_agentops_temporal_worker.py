from __future__ import annotations

import asyncio
import builtins
from typing import Any

import pytest

from data_agent.agentops_temporal_contracts import temporal_contract_fingerprint
from data_agent.agentops_temporal_worker import (
    TEMPORAL_WORKER_REGISTRATION_SCHEMA,
    TemporalioWorkerFactory,
    TemporalWorkerDefinition,
    TemporalWorkerRuntimeConfig,
    build_worker_registration,
)
from data_agent.agentops_temporalio_provider import TemporalAdapterError
from data_agent.test_agentops_contracts import _deployment, _evaluation, _spec


def _registration():
    spec = _spec()
    deployment = _deployment(spec, _evaluation(spec))
    return build_worker_registration(
        tenant_id="planning",
        namespace_ref="gda-planning",
        task_queue_ref="agentops-gis",
        worker_identity_ref="workload:agentops-worker",
        workflow_type="gda.agentops.gis_product",
        activity_types=("gda.agentops.activity", "gda.agentops.quality"),
        agent_spec_sha256=spec.spec_sha256,
        deployment_revision_sha256=deployment.revision_sha256,
    )


async def gda_agentops_gis_product() -> None:
    return None


async def gda_agentops_activity() -> None:
    return None


async def gda_agentops_quality() -> None:
    return None


class _FakeClient:
    namespace = "gda-planning"


class _FakeWorker:
    def __init__(self, client: Any, **kwargs: Any) -> None:
        self.client = client
        self.kwargs = kwargs
        self.shutdown_called = False

    async def run(self) -> None:
        return None

    def shutdown(self) -> None:
        self.shutdown_called = True


def test_registration_is_canonical_and_hash_bound():
    registration = _registration()
    assert registration.activity_types == (
        "gda.agentops.activity",
        "gda.agentops.quality",
    )
    assert registration.registration_sha256 == temporal_contract_fingerprint(
        TEMPORAL_WORKER_REGISTRATION_SCHEMA,
        registration.model_dump(mode="json"),
        "registration_sha256",
    )


def test_worker_factory_binds_namespace_queue_workflow_activities_and_limits():
    registration = _registration()
    worker = TemporalioWorkerFactory(
        _FakeClient(),
        registration,
        workflows=(
            TemporalWorkerDefinition(
                "gda.agentops.gis_product", gda_agentops_gis_product
            ),
        ),
        activities=(
            TemporalWorkerDefinition("gda.agentops.quality", gda_agentops_quality),
            TemporalWorkerDefinition("gda.agentops.activity", gda_agentops_activity),
        ),
        worker_class=_FakeWorker,
    ).build()

    assert worker.kwargs["task_queue"] == "agentops-gis"
    assert worker.kwargs["workflows"] == [gda_agentops_gis_product]
    assert worker.kwargs["activities"] == [gda_agentops_quality, gda_agentops_activity]
    assert worker.kwargs["max_concurrent_activities"] == 10
    assert worker.kwargs["max_concurrent_workflow_tasks"] == 10
    asyncio.run(worker.run())
    worker.shutdown()
    assert worker.shutdown_called is True


def test_worker_factory_fails_closed_for_namespace_or_registration_drift():
    registration = _registration()

    class _WrongNamespaceClient:
        namespace = "other-namespace"

    with pytest.raises(TemporalAdapterError, match="namespace"):
        TemporalioWorkerFactory(
            _WrongNamespaceClient(),
            registration,
            workflows=(
                TemporalWorkerDefinition(
                    "gda.agentops.gis_product", gda_agentops_gis_product
                ),
            ),
            activities=(
                TemporalWorkerDefinition("gda.agentops.activity", gda_agentops_activity),
                TemporalWorkerDefinition("gda.agentops.quality", gda_agentops_quality),
            ),
            worker_class=_FakeWorker,
        ).build()

    with pytest.raises(TemporalAdapterError, match="workflow_type"):
        TemporalioWorkerFactory(
            _FakeClient(),
            registration,
            workflows=(
                TemporalWorkerDefinition("gda.agentops.other", gda_agentops_activity),
            ),
            activities=(
                TemporalWorkerDefinition("gda.agentops.activity", gda_agentops_activity),
                TemporalWorkerDefinition("gda.agentops.quality", gda_agentops_quality),
            ),
            worker_class=_FakeWorker,
        ).build()

    with pytest.raises(TemporalAdapterError, match="missing"):
        TemporalioWorkerFactory(
            _FakeClient(),
            registration,
            workflows=(
                TemporalWorkerDefinition(
                    "gda.agentops.gis_product", gda_agentops_gis_product
                ),
            ),
            activities=(
                TemporalWorkerDefinition("gda.agentops.activity", gda_agentops_activity),
            ),
            worker_class=_FakeWorker,
        ).build()


def test_worker_factory_requires_sdk_when_no_worker_class_is_supplied(
    monkeypatch: pytest.MonkeyPatch,
):
    registration = _registration()
    original_import = builtins.__import__

    def _missing_temporal_worker(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "temporalio.worker":
            raise ImportError("simulated missing temporalio worker SDK")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _missing_temporal_worker)
    with pytest.raises(TemporalAdapterError, match="optional dependency temporalio"):
        TemporalioWorkerFactory(
            _FakeClient(),
            registration,
            workflows=(
                TemporalWorkerDefinition(
                    "gda.agentops.gis_product", gda_agentops_gis_product
                ),
            ),
            activities=(
                TemporalWorkerDefinition("gda.agentops.activity", gda_agentops_activity),
                TemporalWorkerDefinition("gda.agentops.quality", gda_agentops_quality),
            ),
        ).build()


def test_runtime_config_requires_explicit_hashes_and_builds_registration():
    registration = _registration()
    environ = {
        "GDA_AGENTOPS_TEMPORAL_TENANT_ID": registration.tenant_id,
        "GDA_AGENTOPS_TEMPORAL_NAMESPACE": registration.namespace_ref,
        "GDA_AGENTOPS_TEMPORAL_FRONTEND": "gis-agent-temporal-frontend:7233",
        "GDA_AGENTOPS_TEMPORAL_TASK_QUEUE": registration.task_queue_ref,
        "GDA_AGENTOPS_TEMPORAL_WORKER_ID": registration.worker_identity_ref,
        "GDA_AGENTOPS_TEMPORAL_WORKFLOW_TYPE": registration.workflow_type,
        "GDA_AGENTOPS_TEMPORAL_ACTIVITY_TYPES": ",".join(registration.activity_types),
        "GDA_AGENTOPS_AGENT_SPEC_SHA256": registration.agent_spec_sha256,
        "GDA_AGENTOPS_DEPLOYMENT_REVISION_SHA256": registration.deployment_revision_sha256,
    }
    config = TemporalWorkerRuntimeConfig.from_env(environ)
    assert config.frontend_target == "gis-agent-temporal-frontend:7233"
    assert config.registration() == registration

    missing = dict(environ)
    missing.pop("GDA_AGENTOPS_AGENT_SPEC_SHA256")
    with pytest.raises(TemporalAdapterError, match="AGENT_SPEC_SHA256"):
        TemporalWorkerRuntimeConfig.from_env(missing)


def test_runtime_config_rejects_invalid_frontend_and_activity_values():
    registration = _registration()
    environ = {
        "GDA_AGENTOPS_TEMPORAL_TENANT_ID": registration.tenant_id,
        "GDA_AGENTOPS_TEMPORAL_NAMESPACE": registration.namespace_ref,
        "GDA_AGENTOPS_TEMPORAL_FRONTEND": "frontend:not-a-port",
        "GDA_AGENTOPS_TEMPORAL_TASK_QUEUE": registration.task_queue_ref,
        "GDA_AGENTOPS_TEMPORAL_WORKER_ID": registration.worker_identity_ref,
        "GDA_AGENTOPS_TEMPORAL_WORKFLOW_TYPE": registration.workflow_type,
        "GDA_AGENTOPS_TEMPORAL_ACTIVITY_TYPES": "",
        "GDA_AGENTOPS_AGENT_SPEC_SHA256": registration.agent_spec_sha256,
        "GDA_AGENTOPS_DEPLOYMENT_REVISION_SHA256": registration.deployment_revision_sha256,
    }
    with pytest.raises(TemporalAdapterError, match="ACTIVITY_TYPES"):
        TemporalWorkerRuntimeConfig.from_env(environ)
    environ["GDA_AGENTOPS_TEMPORAL_ACTIVITY_TYPES"] = ",".join(
        registration.activity_types
    )
    with pytest.raises(TemporalAdapterError, match="runtime configuration"):
        TemporalWorkerRuntimeConfig.from_env(environ)
    environ["GDA_AGENTOPS_TEMPORAL_FRONTEND"] = "frontend:7233"
    environ["GDA_AGENTOPS_TEMPORAL_ACTIVITY_TYPES"] = "InvalidActivity"
    with pytest.raises(TemporalAdapterError, match="runtime configuration"):
        TemporalWorkerRuntimeConfig.from_env(environ)
