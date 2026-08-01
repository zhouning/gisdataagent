from __future__ import annotations

from scripts import (
    compile_geotransport_stage43_component_event_lag_support_gates as gates,
)


def test_stage43_compiled_report_admits_local_sets_and_rejects_common_support():
    report = gates.compile_report()

    assert report["status"] == gates.STATUS
    assert len(report["gates"]) == 43
    assert sum(report["gates"].values()) == 43
    assert report["all_gates_passed"] is True
    assert report["decision"][
        "event_local_empirical_lag_support_admitted"
    ] is True
    assert report["decision"]["common_empirical_support_admitted"] is False
    assert report["decision"]["common_supported_lags_hours"] == []
    assert report["decision"]["causal_response_admitted"] is False
    assert report["decision"]["physical_travel_time_admitted"] is False
