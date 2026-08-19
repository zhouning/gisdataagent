import json
from types import SimpleNamespace

import pytest

from data_agent.cross_store_projection_consistency import ProjectionEngine
from data_agent.cross_store_projection_recovery_rehearsal import _plan
from data_agent.cross_store_projection_recovery_runtime import (
    ProjectionRecoveryProviderBinding,
    ProjectionRecoveryProviderResolver,
    ProjectionRecoveryRuntimeConfigurationError,
    SealedProjectionRowsFileResolver,
)
from data_agent.platform_contracts import canonical_json_fingerprint


class _Registry:
    def __init__(self, *, registered=True):
        self.registered = registered
        self.calls = []

    def resolve(self, **identity):
        self.calls.append(identity)
        if not self.registered:
            raise ValueError("target is not registered")
        return identity


class _Executor:
    def __init__(self):
        self.execute_calls = []

    def execute(self, plan, **kwargs):
        self.execute_calls.append((plan, kwargs))
        return "receipt"

    def observe(self, target):
        return SimpleNamespace(
            tenant_id=target["tenant_id"],
            projection_id=target["projection_id"],
            target_ref=target["target_ref"],
        )


def _row_bundle(plan, rows):
    return {
        "schema_id": "gda.projection-recovery-rows.v1",
        "tenant_id": plan.tenant_id,
        "projection_id": plan.projection_id,
        "target_engine": plan.target_engine.value,
        "target_ref": plan.target_ref,
        "plan_sha256": plan.plan_sha256,
        "plan_idempotency_key": plan.plan_idempotency_key,
        "rows": rows,
        "rows_sha256": canonical_json_fingerprint(rows),
    }


def test_server_side_rows_file_is_bound_to_plan_and_fingerprint(tmp_path):
    plan = _plan()
    rows = [{"parcel_id": index} for index in range(455)]
    path = tmp_path / f"{plan.plan_sha256}.json"
    path.write_text(json.dumps(_row_bundle(plan, rows)), encoding="utf-8")

    loaded = SealedProjectionRowsFileResolver(tmp_path)(plan)

    assert loaded == tuple(rows)

    tampered = _row_bundle(plan, rows)
    tampered["target_ref"] = "postgis://cq-db/public.other"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ProjectionRecoveryRuntimeConfigurationError, match="identity"):
        SealedProjectionRowsFileResolver(tmp_path)(plan)


def test_provider_resolver_rejects_rebuild_without_server_side_rows():
    plan = _plan()
    registry = _Registry()
    resolver = ProjectionRecoveryProviderResolver(
        bindings={
            ProjectionEngine.POSTGIS: ProjectionRecoveryProviderBinding(
                executor=_Executor(),
                registry=registry,
            )
        }
    )

    with pytest.raises(ProjectionRecoveryRuntimeConfigurationError, match="row bundle"):
        resolver(plan)


def test_provider_resolver_passes_rows_only_to_registered_sql_provider():
    plan = _plan()
    registry = _Registry()
    executor = _Executor()
    resolver = ProjectionRecoveryProviderResolver(
        bindings={
            ProjectionEngine.POSTGIS: ProjectionRecoveryProviderBinding(
                executor=executor,
                registry=registry,
            )
        },
        rows_resolver=lambda _plan: ({"parcel_id": 1},),
    )

    provider = resolver(plan)
    provider.execute(plan)

    assert registry.calls == [
        {
            "tenant_id": plan.tenant_id,
            "projection_id": plan.projection_id,
            "target_ref": plan.target_ref,
        }
    ]
    assert executor.execute_calls == [(plan, {"rows": ({"parcel_id": 1},)})]


def test_provider_resolver_fails_closed_for_unregistered_target():
    plan = _plan()
    resolver = ProjectionRecoveryProviderResolver(
        bindings={
            ProjectionEngine.POSTGIS: ProjectionRecoveryProviderBinding(
                executor=_Executor(),
                registry=_Registry(registered=False),
            )
        },
        rows_resolver=lambda _plan: ({"parcel_id": 1},),
    )

    provider = resolver(plan)
    with pytest.raises(ValueError, match="registered"):
        provider.execute(plan)
