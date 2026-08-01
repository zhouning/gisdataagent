from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.audit_geospatial_kernel_center_hill_dispatch_conversion import (
    DEFAULT_POOL,
    DEFAULT_POOL_HEADERS,
    DEFAULT_STAGE39_MANIFEST,
    DEFAULT_TAIL,
    DEFAULT_TAIL_HEADERS,
    audit_dispatch_conversion,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_center_hill_dispatch_conversion_audit_20260801.json"
)
AUDITED_AT = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)


def _compile(*, pool_path: Path = DEFAULT_POOL) -> dict[str, object]:
    return audit_dispatch_conversion(
        pool_path=pool_path,
        pool_headers_path=DEFAULT_POOL_HEADERS,
        tail_path=DEFAULT_TAIL,
        tail_headers_path=DEFAULT_TAIL_HEADERS,
        stage39_manifest_path=DEFAULT_STAGE39_MANIFEST,
        audited_at=AUDITED_AT,
    )


def test_frozen_dispatch_conversion_report_recomputes_exactly() -> None:
    assert _compile() == json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def test_historical_diagnostic_does_not_invent_generator_labels() -> None:
    report = _compile()

    aligned = report["aligned_historical_support"]
    assert aligned["aligned_hour_count"] == 43_825
    assert aligned["complete_six_series_hour_count"] == 43_825
    latent = report["latent_generator_band_diagnostic"]
    assert latent["stable_latent_band_hour_count"] == 21_210
    assert latent["bands"]["1"]["sample_count"] > 0
    assert latent["bands"]["2"]["sample_count"] > 0
    assert latent["bands"]["3"]["sample_count"] > 0
    assert report["identifiability"][  # type: ignore[index]
        "flow_bands_are_independent_generator_labels"
    ] is False
    assert report["physical_release_boundary_ready"] is False
    assert report["claim_boundary"]["conversion_frozen"] is False  # type: ignore[index]


def test_non_turbine_release_is_not_hidden_by_generator_count() -> None:
    report = _compile()
    non_turbine = report["non_turbine_release_diagnostic"]

    assert non_turbine["nonzero_component_hour_count"] == 9_687
    assert non_turbine["nonzero_component_hour_fraction"] > 0.2
    assert non_turbine["represented_by_native_generator_count_schedule"] is False
    assert report["readiness_gates"][  # type: ignore[index]
        "prospective_non_turbine_release_components_available"
    ] is False


def test_pool_series_identity_drift_fails_closed(tmp_path: Path) -> None:
    payload = json.loads(DEFAULT_POOL.read_text(encoding="utf-8"))
    payload["name"] = "wrong-series"
    drifted = tmp_path / "pool.json"
    drifted.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="dispatch_conversion_cwms_series_invalid",
    ):
        _compile(pool_path=drifted)
