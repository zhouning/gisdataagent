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
    ORIGEN_ABLATION_SCHEMA,
    ORIGEN_ABLATION_VARIANT_SCHEMA,
    SUPPLEMENTARY_SCHEMA,
    external_validation_payload,
)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _validation_receipts(root: Path) -> tuple[Path, Path, Path]:
    confirmatory = root / "confirmatory" / "run_receipt.json"
    supplementary = root / "supplementary" / "run_receipt.json"
    origen_ablation = root / "origen_ablation" / "run_receipt.json"
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
    origen_root = origen_ablation.parent
    protocol_path = origen_root / "experiment_protocol.json"
    metrics_path = origen_root / "spatial_ablation_metrics.csv"
    protocol_path.parent.mkdir(parents=True, exist_ok=True)
    protocol_path.write_text("{}\n", encoding="utf-8")
    metrics_path.write_text("fold,delta\n0,-0.1\n", encoding="utf-8")
    variant_artifacts = []
    for fold in range(4):
        for variant in ("zero_origen", "origen_static_prior"):
            variant_root = origen_root / f"fold_{fold}" / variant
            model_path = variant_root / "hybrid_residual.pt"
            model_path.parent.mkdir(parents=True, exist_ok=True)
            model_path.write_bytes(f"{fold}:{variant}".encode())
            child_path = variant_root / "run_receipt.json"
            child_payload = {
                "schema": ORIGEN_ABLATION_VARIANT_SCHEMA,
                "fold": fold,
                "variant": variant,
                "model_sha256": _file_sha256(model_path),
                "outputs": {
                    "model": str(model_path.relative_to(origen_root)),
                },
            }
            _write_receipt(child_path, child_payload, ensure_ascii=True)
            child = json.loads(child_path.read_text(encoding="utf-8"))
            variant_artifacts.append(
                {
                    "fold": fold,
                    "variant": variant,
                    "receipt": str(child_path.relative_to(origen_root)),
                    "receipt_file_sha256": _file_sha256(child_path),
                    "declared_receipt_sha256": child["receipt_sha256"],
                    "model_sha256": _file_sha256(model_path),
                }
            )
    _write_receipt(
        origen_ablation,
        {
            "schema": ORIGEN_ABLATION_SCHEMA,
            "status": "completed_exploratory_spatial_ablation",
            "fold_count": 4,
            "paired_variant_count": 8,
            "legacy_test_holdout_summary": {
                "mean_delta_macro_rmse_m": -0.0001,
                "mean_delta_macro_mae_m": -0.00005,
                "mean_delta_macro_inundation_iou": 0.01,
                "rmse_improved_fold_count": 3,
                "iou_improved_fold_count": 3,
            },
            "interpretation": "mixed_no_consistent_benefit",
            "promotion_decision": (
                "not_promoted_pending_future_independent_external_validation"
            ),
            "external_validation": {
                "used_for_training_or_selection": False,
                "current_confirmatory_cohort_use": (
                    "forbidden_model_postdates_existing_cohort"
                ),
                "required_next_step": "future_independent_event_cohort_frozen_before_scoring",
            },
            "outputs": {
                "protocol": protocol_path.name,
                "protocol_file_sha256": _file_sha256(protocol_path),
                "metrics": metrics_path.name,
                "metrics_sha256": _file_sha256(metrics_path),
                "variant_receipt_count": 8,
                "variant_artifacts": variant_artifacts,
                "private": "/Users/private/model.pt",
            },
        },
        ensure_ascii=True,
    )
    return confirmatory, supplementary, origen_ablation


def test_external_validation_is_hashed_deduplicated_and_path_free(
    tmp_path: Path, monkeypatch
) -> None:
    confirmatory, supplementary, origen_ablation = _validation_receipts(tmp_path)
    monkeypatch.setenv("ABU_DHABI_GWM_CONFIRMATORY_RECEIPT", str(confirmatory))
    monkeypatch.setenv("ABU_DHABI_GWM_SUPPLEMENTARY_RECEIPT", str(supplementary))
    monkeypatch.setenv("ABU_DHABI_GWM_ORIGEN_ABLATION_RECEIPT", str(origen_ablation))

    payload = external_validation_payload()

    assert payload["status"] == "completed_evidence_limited"
    assert payload["strict_confirmatory"]["event_count"] == 4
    assert payload["strict_confirmatory"]["target_sample_size_reached"] is False
    assert payload["supplementary"]["event_count"] == 2
    assert payload["origen_spatial_ablation"]["fold_count"] == 4
    assert payload["origen_spatial_ablation"]["paired_variant_count"] == 8
    assert (
        payload["origen_spatial_ablation"]["interpretation"]
        == "mixed_no_consistent_benefit"
    )
    assert (
        payload["origen_spatial_ablation"]["legacy_test_holdout_summary"][
            "rmse_improved_fold_count"
        ]
        == 3
    )
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
    confirmatory, supplementary, origen_ablation = _validation_receipts(tmp_path)
    value = json.loads(supplementary.read_text(encoding="utf-8"))
    value["event_ids"] = ["c1", "s2"]
    supplementary.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setenv("ABU_DHABI_GWM_CONFIRMATORY_RECEIPT", str(confirmatory))
    monkeypatch.setenv("ABU_DHABI_GWM_SUPPLEMENTARY_RECEIPT", str(supplementary))
    monkeypatch.setenv("ABU_DHABI_GWM_ORIGEN_ABLATION_RECEIPT", str(origen_ablation))

    payload = external_validation_payload()

    assert payload["status"] == "partial_or_invalid"
    assert payload["supplementary"]["receipt"]["integrity_verified"] is False
    assert payload["cross_cohort"]["event_ids_disjoint"] is False
    assert payload["audit"]["event_deduplication_passed"] is False


def test_external_validation_rejects_origen_model_artifact_tampering(
    tmp_path: Path, monkeypatch
) -> None:
    confirmatory, supplementary, origen_ablation = _validation_receipts(tmp_path)
    model_path = origen_ablation.parent / "fold_0/zero_origen/hybrid_residual.pt"
    model_path.write_bytes(b"tampered")
    monkeypatch.setenv("ABU_DHABI_GWM_CONFIRMATORY_RECEIPT", str(confirmatory))
    monkeypatch.setenv("ABU_DHABI_GWM_SUPPLEMENTARY_RECEIPT", str(supplementary))
    monkeypatch.setenv("ABU_DHABI_GWM_ORIGEN_ABLATION_RECEIPT", str(origen_ablation))

    payload = external_validation_payload()

    assert (
        payload["origen_spatial_ablation"]["receipt"]["artifact_chain_verified"]
        is False
    )
    assert payload["audit"]["all_available_receipts_integrity_verified"] is False


def test_external_validation_route_requires_authentication_and_serves_ledger(
    tmp_path: Path, monkeypatch
) -> None:
    confirmatory, supplementary, origen_ablation = _validation_receipts(tmp_path)
    monkeypatch.setenv("ABU_DHABI_GWM_CONFIRMATORY_RECEIPT", str(confirmatory))
    monkeypatch.setenv("ABU_DHABI_GWM_SUPPLEMENTARY_RECEIPT", str(supplementary))
    monkeypatch.setenv("ABU_DHABI_GWM_ORIGEN_ABLATION_RECEIPT", str(origen_ablation))
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
        assert response.json()["origen_spatial_ablation"]["fold_count"] == 4
