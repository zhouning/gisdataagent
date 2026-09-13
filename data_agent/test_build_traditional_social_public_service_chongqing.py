import json
from pathlib import Path
import subprocess
import sys

from scripts.build_traditional_social_public_service_chongqing import build_product


def write_sources(root: Path) -> tuple[Path, Path]:
    facility_path = root / "facility.json"
    mobility_path = root / "mobility.json"
    facility_path.write_text(json.dumps({
        "schema": "uwm.traditional_livability.facility_product.v1",
        "bundle_id": "facility-bundle",
        "facilities": [
            {"name":"学校甲","source_record_id":"1","source_dataset_id":"poi","raw_primary_class":"教育培训","raw_secondary_class":"学校","raw_tertiary_class":None,"canonical_class":"education.school","mapping_status":"mapped","admin_code":"500101","longitude":106.5,"latitude":29.5},
            {"name":"街道办甲","source_record_id":"2","source_dataset_id":"poi","raw_primary_class":"政府机构","raw_secondary_class":"政府机关","raw_tertiary_class":None,"canonical_class":"government_community.facility","mapping_status":"mapped","admin_code":"500101","longitude":106.6,"latitude":29.6},
        ],
        "population_units": [
            {"admin_code":"500101","admin_name":"万州区","population":100,"population_basis":"observed"},
            {"admin_code":"500102","admin_name":"涪陵区","population":200,"population_basis":"observed"},
        ],
        "source_manifest": {"complete_inventory": False},
    }, ensure_ascii=False))
    mobility_path.write_text(json.dumps({
        "schema":"traditional_livability.mobility_admin_units.v1",
        "bundle_id":"mobility-bundle",
        "admin_units":[{"admin_unit_id":"万州区|甲镇|1","county":"万州区","township":"甲镇","service_accessibility_score":0.5}]
    }, ensure_ascii=False))
    return facility_path, mobility_path


def test_builder_writes_five_consistent_files_and_does_not_fake_township_join(tmp_path):
    facility_path, mobility_path = write_sources(tmp_path)
    output = tmp_path / "out"
    result = build_product(facility_product_path=facility_path, mobility_admin_units_path=mobility_path, output_dir=output)

    assert set(path.name for path in output.iterdir()) == {"overview.json","facilities.json","admin_units.json","channel_readiness.json","map.json"}
    payloads = [json.loads(path.read_text()) for path in output.iterdir()]
    assert {payload["bundle_id"] for payload in payloads} == {result["bundle_id"]}
    admins = json.loads((output / "admin_units.json").read_text())["admin_units"]
    assert [row["admin_unit_id"] for row in admins] == ["500101", "500102"]
    assert admins[0]["service_accessibility_score"] is None
    assert "township_accessibility_not_joined_to_county_facilities" in result["production_blockers"]
    assert result["fabricated_value_count"] == 0


def test_builder_supports_direct_cli_execution(tmp_path):
    facility_path, mobility_path = write_sources(tmp_path)
    output = tmp_path / "cli-out"
    completed = subprocess.run(
        [sys.executable, "scripts/build_traditional_social_public_service_chongqing.py", "--facility-product", str(facility_path), "--mobility-admin-units", str(mobility_path), "--output-dir", str(output)],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert (output / "overview.json").is_file()
