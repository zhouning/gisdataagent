from pathlib import Path

import pytest

from data_agent.world_model_v21 import WorldModelV21Service


REPO = Path(r"D:\test\_publish\arcgis-farmland-mpc")
PREPARED = REPO / "runs" / "restoration" / "buchanan_va" / "prepared_watershed"
ENSEMBLE = (
    REPO
    / "paper"
    / "checkpoints"
    / "restoration"
    / "profiles"
    / "buchanan_va"
    / "watershed"
    / "ensemble_seed0"
)


def test_world_model_v21_runs_real_buchanan_va_data_end_to_end():
    if not PREPARED.is_dir() or not ENSEMBLE.is_dir():
        pytest.skip("Paper9 Buchanan VA real-data fixture is not present")

    svc = WorldModelV21Service(repo_path=REPO)
    result = svc.run_plan(
        {
            "prepared_dir": str(PREPARED),
            "ensemble_dir": str(ENSEMBLE),
            "env_kind": "restoration",
            "horizon": 2,
            "top_k": 5,
            "n_episodes": 1,
            "continuation": "greedy",
            "scoring": "reward",
            "threads": 0,
        },
        user_id="pytest_realdata",
    )

    assert result["status"] == "ok"
    assert result["env_kind"] == "restoration"
    assert result["summary"]["n_blocks"] == 562
    assert result["summary"]["max_steps"] == 50
    assert result["summary"]["steps_run"] == 50
    assert result["summary"]["n_selected"] == 50
    assert result["summary"]["total_reward"] > 0
    assert (Path(result["out_dir"]) / "mpc_summary.json").exists()
    assert (Path(result["out_dir"]) / "mpc_land_use.npy").exists()
