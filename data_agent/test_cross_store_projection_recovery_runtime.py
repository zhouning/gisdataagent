import hashlib
import json
from types import SimpleNamespace

import pytest

from data_agent.cross_store_projection_consistency import ProjectionEngine
from data_agent.cross_store_projection_recovery_rehearsal import _plan
from data_agent.cross_store_projection_recovery_runtime import (
    ProjectionRecoveryControllerAdmissionBundleResolver,
    ProjectionRecoveryProviderBinding,
    ProjectionRecoveryProviderResolver,
    ProjectionRecoveryRuntimeConfigurationError,
    SealedProjectionRowsFileResolver,
)
from data_agent.platform_contracts import canonical_json_fingerprint
from data_agent.platform_runtime.cross_store_recovery import (
    CROSS_STORE_RECOVERY_SCHEMA,
)


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


def _admission_bundle(plan, *, tenant_id=None, source_resource_version_ref=None):
    tenant_id = tenant_id or plan.tenant_id
    payload = {
        "schema": CROSS_STORE_RECOVERY_SCHEMA,
        "tenant_ids": [tenant_id],
        "source_resource_version_ref": (
            source_resource_version_ref
            or plan.desired_state.source_resource_version_ref
            if tenant_id == plan.tenant_id
            else "gda://other/data_product/source/v1"
        ),
        "source_content_sha256": (
            plan.desired_state.source_content_sha256
            if tenant_id == plan.tenant_id
            else "a" * 64
        ),
        "control_manifest_sha256": "b" * 64,
        "object_manifest_sha256": "c" * 64,
    }
    binding = {
        **payload,
        "binding_sha256": hashlib.sha256(
            json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    return {
        "schema_id": "gda.cross_store_recovery_admission_bundle.v1",
        "admissions": {
            plan.plan_sha256: {
                "binding": binding,
                "persisted_tenant_ids": [tenant_id],
                "object_version_id_remap_allowed": False,
            }
        },
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


def test_controller_admission_bundle_is_bound_to_plan_and_tenant(tmp_path):
    plan = _plan()
    path = tmp_path / "controller-admissions.json"
    path.write_text(json.dumps(_admission_bundle(plan)), encoding="utf-8")

    admission = ProjectionRecoveryControllerAdmissionBundleResolver(path)(
        SimpleNamespace(
            plan_sha256=plan.plan_sha256,
            tenant_id=plan.tenant_id,
            plan=plan,
        )
    )

    assert admission.binding.tenant_ids == (plan.tenant_id,)
    assert admission.persisted_tenant_ids == (plan.tenant_id,)

    tampered = _admission_bundle(plan, tenant_id="other-tenant")
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ProjectionRecoveryRuntimeConfigurationError, match="does not cover"):
        ProjectionRecoveryControllerAdmissionBundleResolver(path)(
            SimpleNamespace(
                plan_sha256=plan.plan_sha256,
                tenant_id=plan.tenant_id,
                plan=plan,
            )
        )

    source_tampered = _admission_bundle(
        plan,
        source_resource_version_ref="gda://chongqing-customer/data_product/other-v1",
    )
    path.write_text(json.dumps(source_tampered), encoding="utf-8")
    with pytest.raises(ProjectionRecoveryRuntimeConfigurationError, match="source identity"):
        ProjectionRecoveryControllerAdmissionBundleResolver(path)(
            SimpleNamespace(
                plan_sha256=plan.plan_sha256,
                tenant_id=plan.tenant_id,
                plan=plan,
            )
        )
