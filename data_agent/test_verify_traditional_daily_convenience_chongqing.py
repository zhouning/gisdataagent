import json,pytest
from data_agent.test_build_traditional_daily_convenience_chongqing import sources
from scripts.build_traditional_daily_convenience_chongqing import build_product
from scripts.verify_traditional_daily_convenience_chongqing import verify_product
def test_accepts_valid_and_rejects_atm_as_bank(tmp_path):
 f,a=sources(tmp_path);out=tmp_path/'out';build_product(facility_path=f,accessibility_path=a,output_dir=out);assert verify_product(out)['verified'] is True
 p=out/'places.json';d=json.loads(p.read_text());atm=next(x for x in d['places'] if x['canonical_category']=='atm_access_point');atm['canonical_category']='bank_branch';p.write_text(json.dumps(d,ensure_ascii=False))
 with pytest.raises(ValueError,match='atm_bank_classification_violation'):verify_product(out)
def test_rejects_company_employment_and_bundle_mismatch(tmp_path):
 f,a=sources(tmp_path);out=tmp_path/'out';build_product(facility_path=f,accessibility_path=a,output_dir=out);p=out/'places.json';d=json.loads(p.read_text());company=next(x for x in d['places'] if x['canonical_category']=='company_poi');company['employment_count']=10;p.write_text(json.dumps(d,ensure_ascii=False))
 with pytest.raises(ValueError,match='unavailable_economic_value_present'):verify_product(out)
