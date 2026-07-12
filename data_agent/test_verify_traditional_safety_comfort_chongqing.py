import json,pytest
from data_agent.test_build_traditional_safety_comfort_chongqing import sources
from scripts.build_traditional_safety_comfort_chongqing import build_product
from scripts.verify_traditional_safety_comfort_chongqing import verify_product
def test_accepts_valid_and_rejects_forbidden_score(tmp_path):
 m,e,f=sources(tmp_path);out=tmp_path/'out';build_product(mobility_path=m,environment_path=e,facility_path=f,output_dir=out);assert verify_product(out)['verified'] is True
 p=out/'admin_units.json';d=json.loads(p.read_text());d['admin_units'][0]['safety_score']=0.9;p.write_text(json.dumps(d))
 with pytest.raises(ValueError,match='forbidden_safety_or_comfort_score'):verify_product(out)
def test_rejects_environment_forced_join_and_bundle_mismatch(tmp_path):
 m,e,f=sources(tmp_path);out=tmp_path/'out';build_product(mobility_path=m,environment_path=e,facility_path=f,output_dir=out);p=out/'overview.json';d=json.loads(p.read_text());d['summary']['joined_environment_row_count']=1;p.write_text(json.dumps(d))
 with pytest.raises(ValueError,match='unsupported_environment_join_present'):verify_product(out)
