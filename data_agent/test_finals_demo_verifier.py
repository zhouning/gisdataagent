import json

from scripts.verify_gemma4_finals_demo import _paper9_data_checks


def test_paper9_checks_read_metrics_from_committed_run(tmp_path):
    final_run = tmp_path / "final-run"
    final_run.mkdir()
    (final_run / "mpc_summary.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "steps_run": 100,
                        "swaps_completed": 412,
                        "cultivated_area_change_ha": 0.06,
                        "slope_change_pct": -0.62,
                        "cont_change": 0.02,
                        "baimu_area_change_ha": 32.5,
                    }
                ],
                "shapefile_output": {
                    "n_input": 101657,
                    "n_in_env": 53004,
                    "n_farm_to_forest": 412,
                    "n_forest_to_farm": 412,
                    "land_use_code_scheme": "legacy_three_digit_test_data",
                },
            }
        ),
        encoding="utf-8",
    )
    pipeline = {
        "status": "ok",
        "plan_result": {
            "status": "ok",
            "out_dir": str(tmp_path / "failed-first-run"),
            "summary": {
                "results": [{"cultivated_area_change_ha": -489.02}]
            },
        },
    }
    audit = {
        "out_dir": str(final_run),
        "hard_constraint_passed": True,
        "all_expected_outputs_exist": True,
        "artifacts": {"optimized_spatial_result": {"exists": True}},
    }
    commit = {
        "status": "committed",
        "episode": {"episode_id": "episode-1", "out_dir": str(final_run)},
    }

    checks, metrics = _paper9_data_checks(pipeline, audit, commit)

    assert all(checks.values())
    assert metrics["out_dir"] == str(final_run)
    assert metrics["cultivated_area_change_ha"] == 0.06
    assert metrics["swaps_completed"] == 412
    assert metrics["episode_id"] == "episode-1"
