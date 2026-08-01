from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from scripts.audit_geospatial_kernel_prospective_wwm_live_preflight import (
    compile_live_preflight,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/"
    "geospatial_kernel_prospective_wwm_live_preflight_20260801/raw"
)
REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_prospective_wwm_live_preflight_20260801.json"
)
NWM_URL = (
    "https://nomads.ncep.noaa.gov/pub/data/nccf/com/nwm/prod/"
    "nwm.20260801/short_range/"
    "nwm.t06z.short_range.channel_rt.f001.conus.nc"
)


def _compile() -> dict[str, object]:
    frozen = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    return compile_live_preflight(
        cwms_action_response_path=(
            DATA_ROOT / "cwms_center_hill_release_forecast.json"
        ),
        usgs_observation_response_path=DATA_ROOT / "usgs_03424730_current.json",
        nwm_response_headers_path=DATA_ROOT / "nwm_t06_f001_headers.txt",
        nwm_url=NWM_URL,
        audited_at=datetime.fromisoformat(
            frozen["audited_at_utc"].replace("Z", "+00:00")
        ),
    )


def test_live_preflight_report_recomputes_exactly() -> None:
    frozen = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert _compile() == frozen


def test_live_preflight_blocks_issue_without_claim_inflation() -> None:
    report = _compile()

    assert report["status"] == "blocked_live_wwm_v3_issue_inputs_not_ready"
    assert report["center_hill_live_wwm_v3_issue_ready"] is False
    assert report["trusted_dual_system_campaign_ready"] is False
    assert len(report["center_hill_blocking_reasons"]) == 4
    assert len(report["campaign_blocking_reasons"]) == 6
    assert report["live_inputs"][  # type: ignore[index]
        "center_hill_archival_release_source"
    ][
        "returned_value_count"
    ] == 0
    native = report["live_inputs"][  # type: ignore[index]
        "center_hill_native_dispatch_candidate"
    ]
    assert native["endpoint"].endswith("/generation-releases/CEHT1")
    assert native["api_http_status"] == 403
    assert native["native_action_unit"] == "generator_count"
    assert native["native_dispatch_action_ready"] is False
    assert native["physical_release_boundary_ready"] is False
    assert report["live_inputs"]["center_hill_outlet_observation"][  # type: ignore[index]
        "latest_value_is_provisional"
    ] is True
    nwm = report["live_inputs"]["nwm_short_range_candidate"]  # type: ignore[index]
    assert nwm["one_short_range_channel_file_available"] is True
    assert nwm["exact_forcing_contract_ready"] is False
    assert report["claim_boundary"] == {
        "live_public_input_readiness_audited": True,
        "wwm_v3_issue_compiled": False,
        "physical_prediction_executed": False,
        "future_outcome_loaded": False,
        "candidate_promoted": False,
        "geospatial_kernel_validated": False,
        "runtime_default_enabled": False,
    }
