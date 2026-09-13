from data_agent.uwm.openaq_temporal_benchmark import (
    OPENAQ_OBSERVED_TEMPORAL_BENCHMARK_SCHEMA,
    build_openaq_observed_temporal_benchmark,
    validate_openaq_observed_temporal_benchmark,
)


def _payloads():
    values = [10, 10, 10, 10, 20, 21, 22, 23]
    return {
        "sensor-pm25": {
            "results": [
                {
                    "value": value,
                    "parameter": {"name": "pm25", "units": "µg/m³"},
                    "period": {"datetimeFrom": {"utc": f"2018-10-17T{hour:02d}:00:00Z"}},
                }
                for hour, value in enumerate(values)
            ]
        }
    }


def test_openaq_temporal_benchmark_compares_dynamic_persistence_with_static_mean_holdout():
    benchmark = build_openaq_observed_temporal_benchmark(
        sensor_measurement_payloads=_payloads(),
        benchmark_id="openaq-temporal-test",
        created_at="2026-07-05T15:30:00Z",
        train_fraction=0.5,
    )

    validation = validate_openaq_observed_temporal_benchmark(benchmark)
    assert validation["valid"], validation["errors"]
    assert benchmark["schema"] == OPENAQ_OBSERVED_TEMPORAL_BENCHMARK_SCHEMA
    assert benchmark["pollutant_count"] == 1
    assert benchmark["observation_count"] == 8
    assert benchmark["holdout_count"] == 4
    assert benchmark["traditional_baseline_suite"] == [
        "static_train_mean",
        "static_last_train_observation",
    ]
    assert benchmark["observed_temporal_state_advantage_over_static_baseline_suite"] is True
    result = benchmark["per_pollutant_results"][0]
    assert result["pollutant"] == "pm25"
    assert result["static_mean_baseline_mae"] == 11.5
    assert result["uwm_dynamic_persistence_mae"] == 3.25
    assert result["mae_reduction"] == 8.25
    assert result["mae_reduction_fraction"] == 0.717391
    assert result["holdout_win_rate"] == 0.75
    assert result["holdout_win_count"] == 3
    assert result["dynamic_advantage_over_static_mean"] is True
    assert result["traditional_static_baseline_suite"]["static_train_mean"]["mae"] == 11.5
    assert result["traditional_static_baseline_suite"]["static_last_train_observation"]["mae"] == 11.5
    assert result["traditional_static_baseline_suite"]["static_train_mean"]["dynamic_sign_test"] == {
        "wins": 3,
        "losses": 0,
        "ties": 1,
        "effective_n": 3,
        "one_sided_p_value": 0.125,
    }
    assert result["uwm_dynamic_state_update"]["method"] == "online_persistence_state_update"
    assert result["uwm_dynamic_state_update"]["mae"] == 3.25
    assert result["uwm_dynamic_state_update"]["uses_prior_holdout_observations_online"] is True
    assert result["uwm_dynamic_state_update"]["uses_current_or_future_holdout_labels"] is False
    assert result["temporal_order_negative_control"] == {
        "method": "deterministic_holdout_order_rotation",
        "rotation": 2,
        "shuffled_dynamic_mae": 4.25,
        "ordered_dynamic_mae": 3.25,
        "ordered_mae_advantage": 1.0,
        "ordered_temporal_state_advantage": True,
    }
    assert result["best_traditional_static_baseline"]["method"] == "static_train_mean"
    assert result["beats_all_traditional_static_baselines"] is True
    assert benchmark["overall_holdout_win_rate"] == 0.75
    assert benchmark["temporal_order_negative_control_summary"] == {
        "pollutant_count": 1,
        "ordered_advantage_count": 1,
        "ordered_advantage_rate": 1.0,
        "mean_ordered_mae_advantage": 1.0,
        "all_pollutants_ordered_temporal_state_advantage": True,
    }
    assert benchmark["overall_sign_tests"]["static_train_mean"] == {
        "wins": 3,
        "losses": 0,
        "ties": 1,
        "effective_n": 3,
        "one_sided_p_value": 0.125,
    }
    assert benchmark["observed_temporal_state_advantage_over_static_baseline"] is True
    assert benchmark["empirical_superiority_claim"] is False
    assert "not_policy_intervention_outcome" in benchmark["limitations"]
