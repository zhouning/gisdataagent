import json,pytest
from data_agent.test_build_traditional_public_space_chongqing import source
from scripts.build_traditional_public_space_chongqing import build_product
from scripts.verify_traditional_public_space_chongqing import verify_product

def test_verifier_accepts_valid_and_rejects_deny_list_contamination(tmp_path):
 out=tmp_path/'out';build_product(facility_product_path=source(tmp_path),output_dir=out);r=verify_product(out);assert r['verified'] is True and r['fabricated_value_count']==0
 p=out/'spaces.json';d=json.loads(p.read_text());d['spaces'][0]['raw_tertiary_class']='KTV';p.write_text(json.dumps(d,ensure_ascii=False))
 with pytest.raises(ValueError,match='deny_list_record_in_eligible_spaces'):verify_product(out)
def test_verifier_rejects_bundle_mismatch(tmp_path):
 out=tmp_path/'out';build_product(facility_product_path=source(tmp_path),output_dir=out);p=out/'map.json';d=json.loads(p.read_text());d['bundle_id']='bad';p.write_text(json.dumps(d))
 with pytest.raises(ValueError,match='bundle_id_mismatch'):verify_product(out)
