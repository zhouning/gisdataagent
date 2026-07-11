import json
from pathlib import Path
import subprocess
import sys

from scripts.build_uwm_environmental_kernel_chongqing import build_product


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def fixture_root(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    base = root / "data/uwm_public_proxy/chongqing_central"
    write_json(
        base / "uwm_environmental_evidence_bundle_2024_07_multisource.json",
        {
            "schema": "uwm.environmental_evidence_bundle.v1",
            "bundle_id": "evidence-1",
            "scene_time_range": {"start_date": "2024-07-01", "end_date": "2024-07-07"},
            "source_dataset_ids": ["weather", "air"],
            "observed_holdout_ready": False,
            "claim_boundary": {"max_claim_level": "bounded_support"},
        },
    )
    write_json(
        base / "multisource_livability_scene_2026_07_06/uwm_multisource_livability_scene.json",
        {
            "schema": "uwm.multisource_livability_scene.v1",
            "scene_id": "scene-1",
            "admin_unit_states": [
                {
                    "admin_unit_id": "A",
                    "county": "县A",
                    "township": "镇A",
                    "state_vector": {
                        "gee_temperature_2m_mean_c": 28.5,
                        "tap_scene_pm25_mean_ugm3": 20.0,
                        "ghsl_built_surface_proxy_sum": 1000.0,
                    },
                },
                {
                    "admin_unit_id": "B",
                    "county": "县B",
                    "township": "镇B",
                    "state_vector": {
                        "gee_temperature_2m_mean_c": None,
                        "tap_scene_pm25_mean_ugm3": 22.0,
                        "ghsl_built_surface_proxy_sum": 500.0,
                    },
                },
            ],
        },
    )
    write_json(
        base / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json",
        {
            "schema": "uwm.admin_spatial_adjacency_graph.v1",
            "graph_id": "graph-1",
            "source_dataset_id": "admin-boundary",
            "nodes": [
                {"unit_id": "A", "centroid": {"lon": 106.5, "lat": 29.5}, "bbox": [106.4, 29.4, 106.6, 29.6]},
                {"unit_id": "B", "centroid": {"lon": 106.7, "lat": 29.5}, "bbox": [106.6, 29.4, 106.8, 29.6]},
            ],
            "edges": [{"source": "A", "target": "B", "edge_type": "admin_boundary_adjacency"}],
        },
    )
    write_json(
        base / "tap_pm25_external_dynamics_2026_07_06/tap_external_dynamics_report.json",
        {
            "schema": "uwm.tap_external_spatiotemporal_dynamics_report.v1",
            "supported_claim": "tap_external_temporal_dynamics_advantage_without_spatial_claim",
            "source_dataset_ids": ["tap"],
            "overall_results": {"spatial_negative_control_passed": False},
        },
    )
    return root


def test_build_product_writes_atomic_bundle_with_closed_action_effects(tmp_path):
    output = tmp_path / "product"
    result = build_product(source_root=fixture_root(tmp_path), output_dir=output)

    assert result["ready"] is True
    assert sorted(path.name for path in output.iterdir()) == [
        "current_rollout.json",
        "evidence_gate.json",
        "map.json",
        "scene.json",
    ]
    payloads = [json.loads(path.read_text()) for path in output.iterdir()]
    assert len({payload["bundle_id"] for payload in payloads}) == 1
    rollout = json.loads((output / "current_rollout.json").read_text())
    assert rollout["intervention_status"] == "action_response_closed"
    assert rollout["not_a_causal_effect_estimate"] is True
    assert rollout["fabricated_value_count"] == 0


def test_build_product_preserves_missing_values_and_real_source_dates(tmp_path):
    output = tmp_path / "product"
    build_product(source_root=fixture_root(tmp_path), output_dir=output)
    scene = json.loads((output / "scene.json").read_text())

    assert scene["scene_time_range"] == {"start_date": "2024-07-01", "end_date": "2024-07-07"}
    rows = {row["node_id"]: row for row in scene["state"]["spatial_nodes"]}
    assert rows["B"]["temperature_c"] is None
    assert rows["B"]["temperature_support_level"] == "unavailable"
    assert set(scene["source_dataset_ids"]) >= {"weather", "air", "tap", "admin-boundary"}


def test_build_script_runs_as_direct_cli(tmp_path):
    output = tmp_path / "product"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_uwm_environmental_kernel_chongqing.py",
            "--source-root",
            str(fixture_root(tmp_path)),
            "--output-dir",
            str(output),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert (output / "scene.json").exists()
