import csv
import io
import json

from scripts.evaluate_geospatial_kernel_mvp import HORIZONS, compile_evaluation


def test_kernel_mvp_compiles_real_development_gate_without_new_data(tmp_path) -> None:
    parameter_path = tmp_path / "parameters.json"
    prediction_path = tmp_path / "predictions.csv"

    parameter_body, prediction_body, report = compile_evaluation(
        parameter_output_path=parameter_path,
        prediction_output_path=prediction_path,
    )

    parameters = json.loads(parameter_body)
    predictions = list(csv.DictReader(io.StringIO(prediction_body.decode("utf-8"))))
    assert parameters["support"]["lag_hours"] == [5, 6, 7]
    assert parameters["support"]["admitted"] is False
    assert parameters["mass_conserving_network_routing_replacement"] is False
    assert len(predictions) == 1_920
    assert {int(row["horizon_hours"]) for row in predictions} == set(HORIZONS)
    assert all(row["future_outcome_observation_used"] == "False" for row in predictions)

    gates = report["registered_hard_gate"]
    assert gates["development_gate_passed"] is True
    assert gates["state_writeback_gate_passed"] is True
    assert gates["clipped_candidate_step_count"] == 0
    for horizon in HORIZONS:
        assert gates["per_horizon"][str(horizon)]["candidate_beats_causal_persistence_rmse"]
        assert gates["per_horizon"][str(horizon)]["candidate_beats_graph_manning_rmse"]
    assert report["data_isolation"]["new_target_data_acquired"] is False
    assert report["information_boundary"]["operational_forecast_claim_permitted"] is False
    assert report["claim_boundary"]["geospatial_kernel_validated"] is False


def test_kernel_mvp_has_real_action_and_forcing_ablation_effects(tmp_path) -> None:
    _, _, report = compile_evaluation(
        parameter_output_path=tmp_path / "parameters.json",
        prediction_output_path=tmp_path / "predictions.csv",
    )

    metrics = report["metrics_by_horizon"]
    assert metrics["12"]["kernel_mvp"]["rmse_m3s"] < metrics["12"]["no_future_action"]["rmse_m3s"]
    for horizon in HORIZONS:
        assert (
            metrics[str(horizon)]["kernel_mvp"]["rmse_m3s"]
            < metrics[str(horizon)]["no_future_forcing"]["rmse_m3s"]
        )
