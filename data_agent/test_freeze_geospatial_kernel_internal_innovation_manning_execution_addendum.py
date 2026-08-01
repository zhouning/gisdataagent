from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import (
    freeze_geospatial_kernel_internal_innovation_manning_execution_addendum as freeze,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ADDENDUM_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_internal_innovation_manning_execution_addendum.json"
)


def test_manning_execution_addendum_is_reproducibly_frozen() -> None:
    frozen = json.loads(ADDENDUM_PATH.read_text(encoding="utf-8"))

    assert frozen == freeze.compile_addendum()
    assert frozen["status"] == "frozen_before_prospective_manning_episode_execution"
    assert frozen["claim_boundary"]["base_rollout_protocol_modified"] is False
    assert frozen["claim_boundary"]["prospective_manifests_acquired"] is False
    assert frozen["claim_boundary"]["outcomes_loaded"] is False


def test_addendum_seal_base_protocol_and_code_identities_recompute() -> None:
    frozen = json.loads(ADDENDUM_PATH.read_text(encoding="utf-8"))
    seal = frozen.pop("addendum_seal")
    canonical = json.dumps(
        frozen,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    assert seal["sha256"] == hashlib.sha256(canonical).hexdigest()
    protocol = freeze.BASE_PROTOCOL_PATH.read_bytes()
    assert hashlib.sha256(protocol).hexdigest() == freeze.BASE_PROTOCOL_FILE_SHA256
    assert frozen["base_rollout_protocol"]["bytes_modified"] is False
    for descriptor in frozen["frozen_code"].values():
        body = (REPO_ROOT / descriptor["path"]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == descriptor["sha256"]
        assert len(body) == descriptor["size_bytes"]


def test_addendum_keeps_execution_and_fit_outcome_blind() -> None:
    frozen = freeze.compile_addendum()

    assert frozen["executor_contract"]["outcome_argument_accepted"] is False
    assert frozen["execution_ledger_contract"]["innovation_fit_executed"] is False
    assert frozen["execution_ledger_contract"]["required_system_ids"] == [
        "center_hill",
        "j_percy_priest",
    ]
    assert "outcome_values" in frozen["forbidden_inputs"]
