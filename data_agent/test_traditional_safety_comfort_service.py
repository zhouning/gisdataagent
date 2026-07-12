import json,pytest
from data_agent.test_build_traditional_safety_comfort_chongqing import sources
from data_agent.uwm.traditional_safety_comfort_service import TraditionalSafetyComfortService
from scripts.build_traditional_safety_comfort_chongqing import build_product
def product_dir(tmp_path):
 m,e,f=sources(tmp_path);out=tmp_path/'p';build_product(mobility_path=m,environment_path=e,facility_path=f,output_dir=out);return out
def test_service_deep_copies_and_reads_sources_and_admin(tmp_path):
 s=TraditionalSafetyComfortService(product_dir(tmp_path));o=s.overview();o['bundle_id']='bad';assert s.overview()['bundle_id']!='bad';assert s.admin_units()['count']==1;assert s.admin_unit('甲区|甲镇|1')['admin_unit_id']=='甲区|甲镇|1';assert s.evidence_sources()['count']==3
 with pytest.raises(KeyError,match='safety_comfort_admin_unit_not_found'):s.admin_unit('bad')
def test_service_rejects_bundle_mismatch(tmp_path):
 root=product_dir(tmp_path);p=root/'map.json';d=json.loads(p.read_text());d['bundle_id']='bad';p.write_text(json.dumps(d))
 with pytest.raises(ValueError,match='safety_comfort_product_bundle_mismatch'):TraditionalSafetyComfortService(root)
