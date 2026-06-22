from __future__ import annotations

from pathlib import Path

import pytest

from scripts.build_twm_public_landcover_benchmark import DEFAULT_DONGGUAN_ZIP, run_public_landcover_benchmark


@pytest.mark.skipif(not DEFAULT_DONGGUAN_ZIP.exists(), reason="GeoSOS DongGuan 80m tutorial zip is not available")
def test_twm_public_landcover_benchmark_runs_on_existing_dongguan_data() -> None:
    report = run_public_landcover_benchmark(
        dongguan_zip=Path(DEFAULT_DONGGUAN_ZIP),
        asset_dir=None,
        render=False,
    )

    assert report["schema"] == "territory_world_model.public_landcover_benchmark.v1"
    assert report["status"] == "pass"
    assert report["source"]["source_type"] == "dongguan_zip_adapter"
    assert report["data_profile"]["region_count"] == 1
    assert report["data_profile"]["case_count"] == 1
    assert report["data_profile"]["regions"][0]["years"] == [2000, 2005, 2006]
    assert set(report["data_profile"]["regions"][0]["driver_layers"]) >= {
        "dtcity",
        "dtfreeway",
        "dtrailway",
        "dtroad",
    }

    experiment = report["experiments"][0]
    metrics = experiment["metrics"]
    metadata = experiment["candidate_metadata"]
    forecast_twm = "twm_independent_transition_forecast_demand"
    oracle_twm = "twm_independent_transition_oracle_demand"
    no_neighborhood = "twm_ablation_no_neighborhood_forecast_demand"
    no_demand = "twm_ablation_no_demand_projection"

    assert metadata[forecast_twm]["demand_mode"] == "forecast_demand"
    assert metadata[forecast_twm]["uses_holdout_labels_for_training"] is False
    assert metadata[forecast_twm]["component_flags"]["driver_features"] is True
    assert metadata[forecast_twm]["component_flags"]["neighborhood_features"] is True
    assert metadata[forecast_twm]["component_flags"]["transition_prior"] is True
    assert metadata[forecast_twm]["component_flags"]["demand_projection"] is True
    assert metadata[oracle_twm]["demand_mode"] == "oracle_demand"
    assert metadata[oracle_twm]["uses_holdout_class_totals"] is True
    assert metadata[no_neighborhood]["component_flags"]["neighborhood_features"] is False
    assert metadata[no_demand]["demand_mode"] == "no_demand_projection"
    assert metadata[no_demand]["component_flags"]["demand_projection"] is False
    assert experiment["best_forecast_by_change_fom"] == forecast_twm
    assert metrics[forecast_twm]["change_fom"] > metrics["markov_transition_projection"]["change_fom"]
    assert metrics[forecast_twm]["overall_accuracy"] > metrics["markov_transition_projection"]["overall_accuracy"]
    assert metrics[forecast_twm]["change_fom"] > metrics[no_neighborhood]["change_fom"]
    assert metrics[forecast_twm]["target_total_demand_abs_error"] == 0
    assert metrics[no_demand]["target_total_demand_abs_error"] > 0
    assert metrics[oracle_twm]["oracle_total_demand_abs_error"] == 0

    ablation = experiment["ablation_summary"]
    assert ablation["status"] == "pass"
    assert ablation["full_candidate_id"] == forecast_twm
    assert "neighborhood" in ablation["components_with_positive_change_fom_contribution"]
    assert no_demand in ablation["ablations_with_higher_change_fom_than_full"]
