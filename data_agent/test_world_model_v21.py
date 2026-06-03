from pathlib import Path

import pytest

from data_agent.world_model_v21 import (
    WorldModelV21Service,
    WorldModelV21ValidationError,
)


def test_status_missing_repo(tmp_path):
    svc = WorldModelV21Service(repo_path=tmp_path / "missing")
    status = svc.status()
    assert status["status"] == "unavailable"
    assert status["paper9"]["repo_exists"] is False
    assert status["paper9"]["importable"] is False


def test_onnx_discovery_accepts_standard_and_shipped_names(tmp_path):
    (tmp_path / "ensemble_member0.onnx").write_bytes(b"onnx")
    (tmp_path / "ensemble_lam5.0_member1.onnx").write_bytes(b"onnx")
    svc = WorldModelV21Service(repo_path=tmp_path)
    members = svc.find_onnx_members(tmp_path)
    assert [p.name for p in members] == [
        "ensemble_lam5.0_member1.onnx",
        "ensemble_member0.onnx",
    ]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("horizon", 0, "horizon must be between 1 and 20"),
        ("top_k", 0, "top_k must be between 1 and 500"),
        ("n_episodes", 0, "n_episodes must be between 1 and 20"),
        ("continuation", "beam", "continuation must be 'random' or 'greedy'"),
        ("scoring", "score", "scoring must be 'reward' or 'slope'"),
        ("env_kind", "other", "env_kind must be 'county' or 'restoration'"),
    ],
)
def test_validation_rejects_bad_ranges(tmp_path, field, value, message):
    prepared = tmp_path / "prepared"
    ensemble = tmp_path / "ensemble"
    prepared.mkdir()
    ensemble.mkdir()
    (ensemble / "ensemble_member0.onnx").write_bytes(b"onnx")
    payload = {
        "prepared_dir": str(prepared),
        "ensemble_dir": str(ensemble),
        "horizon": 5,
        "top_k": 50,
        "n_episodes": 1,
        "continuation": "random",
        "scoring": "reward",
        "env_kind": "county",
    }
    payload[field] = value

    svc = WorldModelV21Service(repo_path=tmp_path)
    with pytest.raises(WorldModelV21ValidationError, match=message):
        svc.validate_plan_request(payload)
