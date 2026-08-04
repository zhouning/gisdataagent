import copy
import json
from pathlib import Path

import pytest

from data_agent.uwm.geospatial_kernel.state_prior_p1_protocol_closure import (
    build_state_prior_p1_protocol_closure,
    compute_state_prior_p1_protocol_closure_sha256,
    validate_state_prior_p1_protocol_closure,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
PROTOCOL = (
    DATA_ROOT
    / "geospatial_state_prior_next_p1_protocol_2024_07_02_07"
    / "uwm_geospatial_state_prior_p1_prospective_protocol.json"
)
PREFLIGHT = (
    DATA_ROOT
    / "geospatial_state_prior_2024_predictor_preflight"
    / "uwm_geospatial_state_prior_predictor_preflight.json"
)
PLAN = (
    DATA_ROOT
    / "openaq_multi_station_acquisition_plan_2024_07_02_07"
    / "uwm_openaq_multi_station_acquisition_plan.json"
)
PRIOR_ATTEMPT = DATA_ROOT / "openaq_station_observations_2024_07_attempt/snapshot_manifest.json"
GEOFABRIK_PROBE = (
    ROOT / "docs/reports/uwm_ai_urban_scientist_skill_audit_2026_07_18/live_route_probe.json"
)
CLOSURE = (
    DATA_ROOT
    / "geospatial_state_prior_2024_protocol_closure"
    / "uwm_geospatial_state_prior_p1_protocol_closure.json"
)


def test_checked_in_closure_retires_protocol_without_consuming_target():
    closure = _read_json(CLOSURE)

    assert validate_state_prior_p1_protocol_closure(closure) == {
        "valid": True,
        "errors": [],
    }
    assert closure["protocol_binding"]["protocol_sha256"] == (
        "ee52b37d10bda4b7f64fea960254312806bcefaea8ef9220630226001df37488"
    )
    assert closure["target_access_audit"]["target_unconsumed_under_available_evidence"] is True
    assert closure["replacement_candidate_audit"]["geofabrik_chongqing"]["snapshot_date"] == (
        "2026-07-17"
    )
    assert (
        closure["replacement_candidate_audit"]["geofabrik_chongqing"][
            "eligible_as_frozen_protocol_repair"
        ]
        is False
    )
    assert closure["closure_decision"]["protocol_reactivation_permitted"] is False
    assert closure["closure_decision"]["target_acquisition_permitted"] is False
    assert closure["closure_decision"]["replacement_protocol_required"] is True


def test_protocol_closure_rebuild_is_deterministic():
    assert _build() == _read_json(CLOSURE)


def test_closure_cannot_reopen_protocol_after_digest_recomputation():
    forged = copy.deepcopy(_read_json(CLOSURE))
    forged["closure_decision"]["protocol_reactivation_permitted"] = True
    forged["closure_decision"]["target_acquisition_permitted"] = True
    forged["closure_decision"]["p1_execution_permitted"] = True
    forged["closure_sha256"] = compute_state_prior_p1_protocol_closure_sha256(forged)

    validation = validate_state_prior_p1_protocol_closure(forged)

    assert not validation["valid"]
    assert "p1_protocol_closure_decision_invalid" in validation["errors"]
    assert "p1_protocol_closure_sha256_mismatch" not in validation["errors"]


def test_closure_builder_rejects_any_plan_that_claims_target_download():
    plan = _read_json(PLAN)
    plan["measurement_downloaded"] = True
    values = copy.deepcopy(plan)
    values.pop("plan_sha256")
    plan["plan_sha256"] = _canonical_sha256(values)

    with pytest.raises(
        ValueError,
        match="state_prior_p1_protocol_closure_requires_unacquired_plan",
    ):
        _build(acquisition_plan=plan)


def _build(*, acquisition_plan: dict | None = None) -> dict:
    evidence_paths = [PROTOCOL, PREFLIGHT, PLAN, PRIOR_ATTEMPT, GEOFABRIK_PROBE]
    return build_state_prior_p1_protocol_closure(
        closure_id="chongqing-observed-station-p1-2024-admin-provenance-closure",
        created_at="2026-08-04T23:10:00Z",
        protocol=_read_json(PROTOCOL),
        predictor_preflight=_read_json(PREFLIGHT),
        acquisition_plan=acquisition_plan or _read_json(PLAN),
        prior_attempt_manifest=_read_json(PRIOR_ATTEMPT),
        geofabrik_probe_report=_read_json(GEOFABRIK_PROBE),
        evidence_refs=[_relative_or_absolute(path) for path in evidence_paths],
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative_or_absolute(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


def _canonical_sha256(payload: object) -> str:
    import hashlib

    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
