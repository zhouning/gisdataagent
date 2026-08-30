import json
import os
from types import SimpleNamespace

import pytest

from data_agent.cross_store_projection_recovery_rehearsal import _plan
from data_agent.platform_runtime.cross_store_recovery_admission_bundle import (
    ProjectionRecoveryAdmissionBundle,
    ProjectionRecoveryAdmissionBundleError,
    load_projection_recovery_admission_bundle,
    rotate_projection_recovery_admission_bundle,
)
from data_agent.test_cross_store_projection_recovery_runtime import _admission_bundle


def _bundle(plan):
    return ProjectionRecoveryAdmissionBundle.from_dict(_admission_bundle(plan))


def test_bundle_is_canonical_and_round_trips(tmp_path):
    plan = _plan()
    bundle = _bundle(plan)
    path = tmp_path / "admissions.json"

    rotate_projection_recovery_admission_bundle(path, bundle)

    loaded = load_projection_recovery_admission_bundle(path)
    assert loaded.as_dict() == bundle.as_dict()
    assert path.read_bytes() == bundle.json_bytes()
    assert os.stat(path).st_mode & 0o777 == 0o440


def test_bundle_rejects_noncanonical_fields_and_tenant_drift():
    plan = _plan()
    document = _admission_bundle(plan)
    document["unexpected"] = True
    with pytest.raises(ProjectionRecoveryAdmissionBundleError, match="not canonical"):
        ProjectionRecoveryAdmissionBundle.from_dict(document)

    document = _admission_bundle(plan)
    document["admissions"][plan.plan_sha256]["persisted_tenant_ids"] = []
    with pytest.raises(ProjectionRecoveryAdmissionBundleError, match="tenant copies"):
        ProjectionRecoveryAdmissionBundle.from_dict(document)


def test_bundle_rejects_entry_extra_fields_and_invalid_plan_key():
    plan = _plan()
    document = _admission_bundle(plan)
    document["admissions"][plan.plan_sha256]["operator"] = "alice"
    with pytest.raises(ProjectionRecoveryAdmissionBundleError, match="not canonical"):
        ProjectionRecoveryAdmissionBundle.from_dict(document)

    document = _admission_bundle(plan)
    document["admissions"]["not-a-sha"] = document["admissions"].pop(plan.plan_sha256)
    with pytest.raises(ProjectionRecoveryAdmissionBundleError, match="plan key"):
        ProjectionRecoveryAdmissionBundle.from_dict(document)


def test_bundle_rotation_does_not_leave_a_partial_file(tmp_path):
    plan = _plan()
    path = tmp_path / "admissions.json"
    rotate_projection_recovery_admission_bundle(path, _bundle(plan))
    previous = path.read_bytes()

    second_plan = _plan(projection_id="cq.land_parcel_secondary")
    second = ProjectionRecoveryAdmissionBundle.from_dict(_admission_bundle(second_plan))
    combined = ProjectionRecoveryAdmissionBundle.from_admissions(
        {
            plan.plan_sha256: _bundle(plan).for_plan(plan.plan_sha256),
            second_plan.plan_sha256: second.for_plan(second_plan.plan_sha256),
        }
    )
    rotate_projection_recovery_admission_bundle(path, combined)

    assert path.read_bytes() != previous
    assert load_projection_recovery_admission_bundle(path).for_plan(
        second_plan.plan_sha256
    ).binding.source_content_sha256 == second.for_plan(
        second_plan.plan_sha256
    ).binding.source_content_sha256
    assert not list(tmp_path.glob(".admissions.json.*"))


def test_bundle_for_plan_reports_missing_evidence():
    plan = _plan()
    with pytest.raises(
        ProjectionRecoveryAdmissionBundleError, match="no controller admission evidence"
    ):
        _bundle(plan).for_plan("f" * 64)


def test_json_bytes_are_ascii_and_have_no_secret_fields():
    plan = _plan()
    raw = _bundle(plan).json_bytes()
    parsed = json.loads(raw)
    assert raw.endswith(b"\n")
    assert "password" not in raw.decode("ascii").lower()
    assert parsed["schema_id"] == "gda.cross_store_recovery_admission_bundle.v1"


def test_resolver_job_shape_can_select_bundle_entry(tmp_path):
    plan = _plan()
    path = tmp_path / "admissions.json"
    rotate_projection_recovery_admission_bundle(path, _bundle(plan))
    admission = load_projection_recovery_admission_bundle(path).for_plan(plan.plan_sha256)
    job = SimpleNamespace(plan_sha256=plan.plan_sha256, tenant_id=plan.tenant_id)
    assert job.tenant_id in admission.binding.tenant_ids
