import json,pytest
from data_agent.test_build_traditional_daily_convenience_chongqing import sources
from data_agent.uwm.traditional_daily_convenience_service import TraditionalDailyConvenienceService
from scripts.build_traditional_daily_convenience_chongqing import build_product
def product_dir(tmp_path):f,a=sources(tmp_path);out=tmp_path/'p';build_product(facility_path=f,accessibility_path=a,output_dir=out);return out
def test_service_views_deep_copy_and_admin(tmp_path):
 s=TraditionalDailyConvenienceService(product_dir(tmp_path));o=s.overview();o['bundle_id']='bad';assert s.overview()['bundle_id']!='bad';assert s.places('daily_convenience')['count']==3;assert s.places('business_activity_evidence')['count']==1;assert s.admin_units()['count']==2;assert s.admin_unit('500101')['admin_unit_id']=='500101'
 with pytest.raises(ValueError,match='daily_convenience_view_invalid'):s.places('bad')
 with pytest.raises(KeyError,match='daily_convenience_admin_unit_not_found'):s.admin_unit('bad')
def test_bundle_mismatch(tmp_path):
 root=product_dir(tmp_path);p=root/'map.json';d=json.loads(p.read_text());d['bundle_id']='bad';p.write_text(json.dumps(d))
 with pytest.raises(ValueError,match='daily_convenience_product_bundle_mismatch'):TraditionalDailyConvenienceService(root)
