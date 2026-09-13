import json

import pytest

from data_agent.test_build_traditional_mobility_accessibility_chongqing import source_root
from data_agent.uwm.traditional_mobility_accessibility_service import TraditionalMobilityAccessibilityService
from scripts.build_traditional_mobility_accessibility_chongqing import build_product


def product_dir(tmp_path):
    output=tmp_path/"product"; build_product(source_root=source_root(tmp_path),output_dir=output); return output


def test_service_returns_deep_copies_and_admin_lookup(tmp_path):
    service=TraditionalMobilityAccessibilityService(product_dir(tmp_path))
    overview=service.overview(); overview["bundle_id"]="mutated"
    assert service.overview()["bundle_id"]!="mutated"
    listing=service.admin_units(); assert listing["count"]==2
    detail=service.admin_unit("A"); assert detail["admin_unit_id"]=="A"
    with pytest.raises(KeyError,match="mobility_admin_unit_not_found"): service.admin_unit("missing")


def test_service_rejects_bundle_mismatch(tmp_path):
    root=product_dir(tmp_path); path=root/"map.json"; payload=json.loads(path.read_text()); payload["bundle_id"]="other"; path.write_text(json.dumps(payload))
    with pytest.raises(ValueError,match="mobility_product_bundle_mismatch"): TraditionalMobilityAccessibilityService(root)
