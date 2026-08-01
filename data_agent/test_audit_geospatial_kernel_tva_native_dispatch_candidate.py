from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scripts.audit_geospatial_kernel_tva_native_dispatch_candidate import (
    EXPECTED_SOURCE_MAP_SHA256,
    EXPECTED_XAPK_SHA256,
    REQUIRED_FORECAST_HOURS,
    REQUIRED_LOOKBACK_HOURS,
    SOURCE_EXPECTATIONS,
    audit_native_dispatch_candidate,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/"
    "geospatial_kernel_tva_native_dispatch_20260801/raw"
)
REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_tva_native_dispatch_candidate_20260801.json"
)
OBSERVED_AT = datetime(2026, 8, 1, 8, 37, 5, tzinfo=UTC)
ISSUE_TIME = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
CENTRAL = ZoneInfo("America/Chicago")


def _compile_frozen() -> dict[str, object]:
    return audit_native_dispatch_candidate(
        app_contract_evidence_path=(
            DATA_ROOT / "tva_lake_info_5.2.0_contract_evidence.json"
        ),
        lake_config_path=DATA_ROOT / "lakesConfiguration.json",
        response_headers_path=(
            DATA_ROOT / "generation_releases_CEHT1_headers.txt"
        ),
        response_body_path=DATA_ROOT / "generation_releases_CEHT1_body.txt",
        observed_at=OBSERVED_AT,
        issue_time=ISSUE_TIME,
    )


def _write_fixture_inputs(
    tmp_path: Path,
    *,
    body: object,
) -> tuple[Path, Path, Path, Path]:
    contract_evidence = tmp_path / "contract_evidence.json"
    lake_config = tmp_path / "lakesConfiguration.json"
    headers = tmp_path / "headers.txt"
    response_body = tmp_path / "body.json"
    contract_evidence.write_text(
        json.dumps(
            {
                "schema": (
                    "gwm.geospatial_kernel."
                    "tva_lake_info_contract_evidence.v1"
                ),
                "application": {
                    "package": "com.tva.lakeinfo",
                    "version": "5.2.0",
                    "xapk_sha256": EXPECTED_XAPK_SHA256,
                },
                "source_map": {
                    "asset_path": "assets/public/main.js.map",
                    "sha256": EXPECTED_SOURCE_MAP_SHA256,
                    "full_artifact_committed": False,
                },
                "sanitized_source_excerpts": {
                    name: list(snippets)
                    for name, snippets in SOURCE_EXPECTATIONS.items()
                },
                "sanitization": {
                    (
                        "only_required_endpoint_and_field_mapping_"
                        "excerpts_retained"
                    ): True,
                    "embedded_credentials_retained": False,
                    "parent_source_map_hash_retained": True,
                },
            }
        ),
        encoding="utf-8",
    )
    lake_config.write_text(
        json.dumps(
            [
                {
                    "lakeId": "CEHT1",
                    "name": "Center Hill",
                    "infoImage": "USACE",
                    "gpData": True,
                }
            ]
        ),
        encoding="utf-8",
    )
    headers.write_text(
        "HTTP/2 200\n"
        "date: Sat, 01 Aug 2026 08:37:00 GMT\n"
        "content-type: application/json\n"
        "server: cloudflare\n\n",
        encoding="ascii",
    )
    response_body.write_text(json.dumps(body), encoding="utf-8")
    return contract_evidence, lake_config, headers, response_body


def _clock(value: datetime) -> str:
    hour = value.hour % 12 or 12
    meridiem = "AM" if value.hour < 12 else "PM"
    return f"{hour} {meridiem}"


def _complete_hour_rows(issue_time: datetime) -> list[dict[str, str]]:
    rows = []
    cursor = issue_time - timedelta(hours=REQUIRED_LOOKBACK_HOURS)
    end = issue_time + timedelta(hours=REQUIRED_FORECAST_HOURS)
    while cursor < end:
        local_start = cursor.astimezone(CENTRAL)
        local_end = (cursor + timedelta(hours=1)).astimezone(CENTRAL)
        rows.append(
            {
                "Day": local_start.strftime("%m/%d/%Y"),
                "Time": f"{_clock(local_start)} - {_clock(local_end)} CT",
                "Generators": "1 generator",
            }
        )
        cursor += timedelta(hours=1)
    return rows


def test_frozen_tva_native_dispatch_report_recomputes_exactly() -> None:
    assert _compile_frozen() == json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def test_current_api_denial_preserves_the_two_layer_boundary() -> None:
    report = _compile_frozen()

    assert report["status"] == "blocked_native_dispatch_api_access"
    assert report["api_acquisition"]["http_status"] == 403  # type: ignore[index]
    assert report["api_acquisition"][  # type: ignore[index]
        "geographic_access_policy_denial_observed"
    ] is True
    assert report["official_mobile_app_contract"][  # type: ignore[index]
        "generation_release_endpoint"
    ].endswith("/generation-releases/CEHT1")
    assert report["readiness_gates"][  # type: ignore[index]
        "native_dispatch_action_ready"
    ] is False
    assert report["readiness_gates"][  # type: ignore[index]
        "physical_release_boundary_ready"
    ] is False
    assert report["claim_boundary"][  # type: ignore[index]
        "geospatial_kernel_validated"
    ] is False


def test_explicit_200_payload_can_verify_native_axis_without_inventing_flow(
    tmp_path: Path,
) -> None:
    paths = _write_fixture_inputs(
        tmp_path,
        body=_complete_hour_rows(ISSUE_TIME),
    )

    report = audit_native_dispatch_candidate(
        app_contract_evidence_path=paths[0],
        lake_config_path=paths[1],
        response_headers_path=paths[2],
        response_body_path=paths[3],
        observed_at=OBSERVED_AT,
        issue_time=ISSUE_TIME,
    )

    action = report["native_dispatch_action"]
    assert action["payload_verified"] is True
    assert action["required_axis_explicitly_covered"] is True
    assert action["explicitly_covered_required_hour_count"] == 19
    assert report["readiness_gates"][  # type: ignore[index]
        "generator_count_to_release_m3s_mapping_frozen"
    ] is False
    assert report["readiness_gates"][  # type: ignore[index]
        "physical_release_boundary_ready"
    ] is False


def test_omitted_periods_are_not_silently_filled_with_zero(tmp_path: Path) -> None:
    rows = _complete_hour_rows(ISSUE_TIME)
    paths = _write_fixture_inputs(tmp_path, body=rows[:-1])

    report = audit_native_dispatch_candidate(
        app_contract_evidence_path=paths[0],
        lake_config_path=paths[1],
        response_headers_path=paths[2],
        response_body_path=paths[3],
        observed_at=OBSERVED_AT,
        issue_time=ISSUE_TIME,
    )

    action = report["native_dispatch_action"]
    assert action["payload_verified"] is True
    assert action["required_axis_explicitly_covered"] is False
    assert len(action["missing_required_hour_starts_utc"]) == 1
    assert action["omitted_periods_may_be_treated_as_zero"] is False


def test_unparseable_generator_count_fails_closed(tmp_path: Path) -> None:
    rows = _complete_hour_rows(ISSUE_TIME)
    rows[0]["Generators"] = "unknown"
    paths = _write_fixture_inputs(tmp_path, body=rows)

    with pytest.raises(
        ValueError,
        match="tva_native_dispatch_generator_count_invalid",
    ):
        audit_native_dispatch_candidate(
            app_contract_evidence_path=paths[0],
            lake_config_path=paths[1],
            response_headers_path=paths[2],
            response_body_path=paths[3],
            observed_at=OBSERVED_AT,
            issue_time=ISSUE_TIME,
        )
