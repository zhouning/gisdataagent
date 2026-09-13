import json,pytest
from data_agent.test_build_traditional_public_space_chongqing import source
from data_agent.uwm.traditional_public_space_service import TraditionalPublicSpaceService
from scripts.build_traditional_public_space_chongqing import build_product

def product_dir(tmp_path):out=tmp_path/'p';build_product(facility_product_path=source(tmp_path),output_dir=out);return out
def test_service_deep_copies_filters_and_admin_lookup(tmp_path):
 s=TraditionalPublicSpaceService(product_dir(tmp_path));o=s.overview();o['bundle_id']='bad';assert s.overview()['bundle_id']!='bad'
 assert s.spaces('core_open_space')['count']==1
 assert s.admin_units()['count']==2
 assert s.admin_unit('500101')['admin_unit_id']=='500101'
 with pytest.raises(ValueError,match='public_space_category_invalid'):s.spaces('bad')
 with pytest.raises(KeyError,match='public_space_admin_unit_not_found'):s.admin_unit('bad')
def test_service_rejects_bundle_mismatch(tmp_path):
 root=product_dir(tmp_path);p=root/'map.json';d=json.loads(p.read_text());d['bundle_id']='bad';p.write_text(json.dumps(d))
 with pytest.raises(ValueError,match='public_space_product_bundle_mismatch'):TraditionalPublicSpaceService(root)
