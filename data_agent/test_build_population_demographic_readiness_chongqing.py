import json
from scripts.build_population_demographic_readiness_chongqing import build_product


def test_builder_publishes_six_files_without_forecast(tmp_path):
    source = tmp_path / "manifest.json"
    source.write_text(json.dumps({"dataset_id": "p1", "summary": {"district_count": 39}}))
    product = build_product(evidence_specs=[{"product_id": "district", "source_path": source, "evidence_role": "district_population_context", "observation_year": 2021, "spatial_grain": "district", "record_count_field": "district_count"}], output_dir=tmp_path / "out")
    assert product["summary"]["forecast_population"] is None
    assert product["evidence_products"][0]["record_count"] == 39
    assert len(list((tmp_path / "out").glob("*.json"))) == 6
