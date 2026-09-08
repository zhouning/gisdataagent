from __future__ import annotations

import copy
import hashlib
import json

import pytest

from data_agent.uwm.abu_dhabi_flood.event_reconstruction import (
    APRIL_2024_EVENT_EVIDENCE_SCHEMA,
    build_april_2024_event_evidence,
    verify_april_2024_event_evidence,
)


def test_april_2024_event_evidence_is_non_spatial_and_explicitly_not_calibrated():
    payload = build_april_2024_event_evidence()

    verify_april_2024_event_evidence(payload)

    assert payload["schema"] == APRIL_2024_EVENT_EVIDENCE_SCHEMA
    assert payload["data_class"] == "public_evidence_non_spatial"
    assert payload["map_behavior"] == "does_not_publish_any_map_layer"
    assert payload["reconstruction"]["admission"] == "prototype_sensitivity_only"
    assert payload["key_facts"][0]["value"] == "254.8 mm / 24 h"
    assert "not Abu Dhabi city rainfall" in payload["key_facts"][0]["detail_en"]


def test_event_evidence_rejects_spatial_content_or_a_changed_profile():
    spatial_payload = copy.deepcopy(build_april_2024_event_evidence())
    spatial_payload["timeline"][0]["latitude"] = 24.0
    spatial_content = dict(spatial_payload)
    spatial_content.pop("evidence_sha256")
    spatial_payload["evidence_sha256"] = hashlib.sha256(
        json.dumps(spatial_content, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()
    with pytest.raises(ValueError, match="geometry"):
        verify_april_2024_event_evidence(spatial_payload)

    changed_profile = copy.deepcopy(build_april_2024_event_evidence())
    changed_profile["reconstruction"]["rainfall_profile_mmph"][25] = 99.0
    changed_content = dict(changed_profile)
    changed_content.pop("evidence_sha256")
    changed_profile["evidence_sha256"] = hashlib.sha256(
        json.dumps(changed_content, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()
    with pytest.raises(ValueError, match="profile"):
        verify_april_2024_event_evidence(changed_profile)
