from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import freeze_geospatial_kernel_internal_innovation_rollout_protocol as freeze

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_internal_innovation_rollout_protocol.json"
)


def test_internal_innovation_rollout_protocol_is_identity_frozen() -> None:
    frozen = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))

    assert frozen == freeze.compile_protocol()
    assert frozen["status"] == "frozen_awaiting_prospective_outcome_free_inputs"
    assert frozen["systems"]["system_ids"] == ["center_hill", "j_percy_priest"]
    assert frozen["claim_boundary"]["prospective_inputs_acquired"] is False
    assert frozen["claim_boundary"]["prospective_predictions_executed"] is False
    assert frozen["claim_boundary"]["outcomes_loaded"] is False


def test_protocol_seal_and_every_code_artifact_hash_match() -> None:
    frozen = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    seal = frozen.pop("protocol_seal")
    canonical = json.dumps(
        frozen,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    assert seal["sha256"] == hashlib.sha256(canonical).hexdigest()
    for descriptor in frozen["frozen_code"].values():
        body = (REPO_ROOT / descriptor["path"]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == descriptor["sha256"]
        assert len(body) == descriptor["size_bytes"]


def test_protocol_requires_causal_future_inputs_and_keeps_candidate_disabled() -> None:
    frozen = freeze.compile_protocol()
    episode = frozen["prospective_episode_contract"]

    assert episode["support_must_start_after_protocol_freeze"] is True
    assert episode["every_input_available_at_or_before_issue"] is True
    assert episode["one_telemetry_bundle_per_issue_time"] is True
    assert "outcome_values" in frozen["forbidden_executor_inputs"]
    assert frozen["operator_roles"]["candidate_internal_innovation"]["default_enabled"] is False
    assert frozen["operator_roles"]["candidate_internal_innovation"]["runtime_admitted"] is False
    assert (
        frozen["claim_boundary"]["historical_posthoc_inputs_may_be_relabelled_prospective"] is False
    )
