import json
from pathlib import Path
import subprocess
import sys

from scripts.build_traditional_mobility_accessibility_chongqing import build_product


def write(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def source_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    base = root / "data/uwm_public_proxy/chongqing_central"
    write(base / "full_admin_service_accessibility_surface_2026_07_08/uwm_full_admin_service_accessibility_surface.json", {
        "schema":"uwm.full_admin_service_accessibility_surface.v1","source_dataset_ids":["services","roads"],"admin_unit_count":2,
        "admin_service_rows":[
            {"admin_unit_id":"A","county":"县A","township":"镇A","longitude":106.5,"latitude":29.5,"service_point_count":5,"essential_service_count":2,"nearest_essential_service_distance_m":700.0,"nearest_essential_service_travel_time_min_proxy":10.0,"road_segment_count":30,"road_length_km":12.0,"mean_road_speed_kmh":25.0,"service_accessibility_score":0.5},
            {"admin_unit_id":"B","county":"县B","township":"镇B","longitude":106.7,"latitude":29.6,"service_point_count":0,"essential_service_count":0,"nearest_essential_service_distance_m":1500.0,"nearest_essential_service_travel_time_min_proxy":24.0,"road_segment_count":4,"road_length_km":2.0,"mean_road_speed_kmh":20.0,"service_accessibility_score":0.1},
        ],"claim_boundary":{"max_claim_level":"bounded_support"},"limitations":["proxy"]})
    write(base / "full_admin_mobility_graph_2026_07_10/full_admin_mobility_graph.json", {"schema":"uwm.full_admin_mobility_graph.v1","graph_id":"g1","summary":{"node_count":2,"edge_count":1,"road_segment_count_sum":34,"road_length_km_sum":14.0},"limitations":["not_observed_trip_time"]})
    write(base / "full_admin_service_surface_quality_audit_2026_07_08/uwm_full_admin_service_surface_quality_audit.json", {"schema":"uwm.full_admin_service_surface_quality_audit.v1","supported_claim":"quality_audit_ready","claim_boundary":{"max_claim_level":"bounded_support"},"limitations":["not_observed_policy_outcome"]})
    return root


def test_builder_writes_four_file_atomic_product(tmp_path):
    output = tmp_path / "product"
    result = build_product(source_root=source_root(tmp_path), output_dir=output)
    assert result["ready"] is True
    assert sorted(path.name for path in output.iterdir()) == ["admin_units.json", "channel_readiness.json", "map.json", "overview.json"]
    payloads = [json.loads(path.read_text()) for path in output.iterdir()]
    assert len({payload["bundle_id"] for payload in payloads}) == 1


def test_builder_preserves_real_counts_and_unavailable_channels(tmp_path):
    output = tmp_path / "product"
    build_product(source_root=source_root(tmp_path), output_dir=output)
    overview = json.loads((output / "overview.json").read_text())
    channels = json.loads((output / "channel_readiness.json").read_text())
    assert overview["summary"]["admin_unit_count"] == 2
    assert overview["summary"]["road_segment_count"] == 34
    assert overview["summary"]["road_length_km_proxy"] == 14.0
    assert overview["fabricated_value_count"] == 0
    assert channels["channels"]["public_transport"]["status"] == "unavailable"
    assert channels["channels"]["public_transport"]["value"] is None


def test_builder_runs_as_direct_cli(tmp_path):
    output = tmp_path / "product"
    completed = subprocess.run([sys.executable,"scripts/build_traditional_mobility_accessibility_chongqing.py","--source-root",str(source_root(tmp_path)),"--output-dir",str(output)],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert completed.returncode == 0, completed.stderr
    assert (output / "overview.json").exists()
