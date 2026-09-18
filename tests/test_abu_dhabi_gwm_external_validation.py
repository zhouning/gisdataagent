from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from starlette.applications import Starlette
from starlette.testclient import TestClient

from data_agent.api import abu_dhabi_flood_routes as flood_routes
from data_agent.uwm.abu_dhabi_flood.external_validation import (
    CONFIRMATORY_SCHEMA,
    SUPPLEMENTARY_SCHEMA,
    external_validation_payload,
)


def _write_receipt(
    path: Path,
    payload: dict,
    *,
    ensure_ascii: bool,
) -> None:
    value = dict(payload)
    encoded = json.dumps(
        value,
        ensure_ascii=ensure_ascii,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii" if ensure_ascii else "utf-8")
    value["receipt_sha256"] = hashlib.sha256(encoded).hexdigest()
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _validation_receipts(root: Path) -> tuple[Path, Path]:
    confirmatory = root / "confirmatory" / "run_receipt.json"
    supplementary = root / "supplementary" / "run_receipt.json"
    _write_receipt(
        confirmatory,
        {
            "schema": CONFIRMATORY_SCHEMA,
            "status": "completed_confirmatory_small_n",
            "event_count": 4,
            "event_ids": ["c1", "c2", "c3", "c4"],
            "frozen_contract": {"protocol": "/Users/private/confirmatory.json"},
            "physics_emulation_macro_metrics": [
                {"model": "gated_hybrid_gwm", "macro_physics_binary_iou": 0.625}
            ],
            "sentinel2_macro_metrics": [
                {"model": "physics", "macro_iou": 0.059},
                {"model": "gated_hybrid_gwm", "macro_iou": 0.055},
            ],
            "claim_boundary": ["Confirmatory inference is small-n."],
            "outputs": {"private": "/Users/private/prediction.npz"},
        },
        ensure_ascii=True,
    )
    _write_receipt(
        supplementary,
        {
            "schema": SUPPLEMENTARY_SCHEMA,
            "status": "completed_exploratory_supplementary_underpowered",
            "event_count": 2,
            "event_ids": ["s1", "s2"],
            "target_event_count": 5,
            "target_sample_size_reached": False,
            "frozen_contract": {"cohort_path": "/Users/private/cohort.json"},
            "source_specific_metrics": [
                {
                    "observation_source": "landsat_c2_l2_partial_aoi",
                    "space": "raw_depth_primary",
                    "model": "physics",
                    "event_count": 1,
                    "macro_iou": 0.0,
                },
                {
                    "observation_source": "sentinel1_same_orbit_partial_aoi",
                    "space": "raw_depth_primary",
                    "model": "gated_hybrid_gwm",
                    "event_count": 1,
                    "macro_iou": 0.01,
                },
            ],
            "claim_boundary": ["Optical and SAR metrics are not pooled."],
            "outputs": {"private": "/Users/private/prediction.npz"},
        },
        ensure_ascii=False,
    )
    return confirmatory, supplementary


def test_external_validation_is_hashed_deduplicated_and_path_free(
    tmp_path: Path, monkeypatch
) -> None:
    confirmatory, supplementary = _validation_receipts(tmp_path)
    monkeypatch.setenv("ABU_DHABI_GWM_CONFIRMATORY_RECEIPT", str(confirmatory))
    monkeypatch.setenv("ABU_DHABI_GWM_SUPPLEMENTARY_RECEIPT", str(supplementary))

    payload = external_validation_payload()

    assert payload["status"] == "completed_evidence_limited"
    assert payload["strict_confirmatory"]["event_count"] == 4
    assert payload["strict_confirmatory"]["target_sample_size_reached"] is False
    assert payload["supplementary"]["event_count"] == 2
    assert payload["cross_cohort"] == {
        "independent_event_count": 6,
        "overlap_event_count": 0,
        "event_ids_unique_within_cohorts": True,
        "event_ids_disjoint": True,
        "performance_metrics_pooled": False,
        "pooling_prohibited_reason": "different_sensor_observation_contracts",
    }
    assert payload["audit"]["all_available_receipts_integrity_verified"] is True
    assert payload["engineering_admission"]["admitted"] is False
    serialized = json.dumps(payload)
    assert "/Users/" not in serialized
    assert str(tmp_path) not in serialized
    assert '"event_ids":' not in serialized
    assert '"c1"' not in serialized
    assert '"s1"' not in serialized


def test_external_validation_rejects_hash_tampering_and_event_overlap(
    tmp_path: Path, monkeypatch
) -> None:
    confirmatory, supplementary = _validation_receipts(tmp_path)
    value = json.loads(supplementary.read_text(encoding="utf-8"))
    value["event_ids"] = ["c1", "s2"]
    supplementary.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setenv("ABU_DHABI_GWM_CONFIRMATORY_RECEIPT", str(confirmatory))
    monkeypatch.setenv("ABU_DHABI_GWM_SUPPLEMENTARY_RECEIPT", str(supplementary))

    payload = external_validation_payload()

    assert payload["status"] == "partial_or_invalid"
    assert payload["supplementary"]["receipt"]["integrity_verified"] is False
    assert payload["cross_cohort"]["event_ids_disjoint"] is False
    assert payload["audit"]["event_deduplication_passed"] is False


def test_external_validation_route_requires_authentication_and_serves_ledger(
    tmp_path: Path, monkeypatch
) -> None:
    confirmatory, supplementary = _validation_receipts(tmp_path)
    monkeypatch.setenv("ABU_DHABI_GWM_CONFIRMATORY_RECEIPT", str(confirmatory))
    monkeypatch.setenv("ABU_DHABI_GWM_SUPPLEMENTARY_RECEIPT", str(supplementary))
    app = Starlette(routes=flood_routes.get_abu_dhabi_flood_routes())
    with TestClient(app) as client:
        assert client.get("/api/abu-dhabi/flood/gwm/external-validation").status_code == 401

    monkeypatch.setattr(
        flood_routes,
        "_get_user_from_request",
        lambda request: SimpleNamespace(identifier="analyst", metadata={"role": "analyst"}),
    )
    monkeypatch.setattr(flood_routes, "_set_user_context", lambda user: None)
    app = Starlette(routes=flood_routes.get_abu_dhabi_flood_routes())
    with TestClient(app) as client:
        response = client.get("/api/abu-dhabi/flood/gwm/external-validation")
        assert response.status_code == 200
        assert response.json()["cross_cohort"]["independent_event_count"] == 6
