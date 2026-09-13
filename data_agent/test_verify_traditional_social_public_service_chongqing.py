import json
from pathlib import Path
import pytest
from data_agent.test_build_traditional_social_public_service_chongqing import write_sources
from scripts.build_traditional_social_public_service_chongqing import build_product
from scripts.verify_traditional_social_public_service_chongqing import verify_product


def test_verifier_accepts_valid_bundle_and_rejects_bundle_mismatch(tmp_path):
    facility, mobility = write_sources(tmp_path); output=tmp_path/'out'
    build_product(facility_product_path=facility,mobility_admin_units_path=mobility,output_dir=output)
    result=verify_product(output)
    assert result['verified'] is True and result['fabricated_value_count']==0
    payload=json.loads((output/'facilities.json').read_text()); payload['bundle_id']='bad'; (output/'facilities.json').write_text(json.dumps(payload))
    with pytest.raises(ValueError,match='bundle_id_mismatch'): verify_product(output)
