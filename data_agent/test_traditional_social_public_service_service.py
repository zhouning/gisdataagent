import json
import pytest
from data_agent.test_build_traditional_social_public_service_chongqing import write_sources
from data_agent.uwm.traditional_social_public_service_service import TraditionalSocialPublicServiceService
from scripts.build_traditional_social_public_service_chongqing import build_product

def product_dir(tmp_path):
 f,m=write_sources(tmp_path);out=tmp_path/'product';build_product(facility_product_path=f,mobility_admin_units_path=m,output_dir=out);return out

def test_service_returns_deep_copies_and_view_filters(tmp_path):
 s=TraditionalSocialPublicServiceService(product_dir(tmp_path));o=s.overview();o['bundle_id']='bad';assert s.overview()['bundle_id']!='bad'
 assert s.facilities('social_infrastructure')['count']==1
 assert s.facilities('government_public_service')['count']==1
 assert s.admin_units('social_infrastructure')['count']==2
 assert s.admin_unit('500101','government_public_service')['view']['facility_count']==1
 with pytest.raises(KeyError,match='social_public_service_admin_unit_not_found'):s.admin_unit('x','social_infrastructure')
 with pytest.raises(ValueError,match='social_public_service_view_invalid'):s.facilities('bad')

def test_service_rejects_bundle_mismatch(tmp_path):
 root=product_dir(tmp_path);p=root/'map.json';d=json.loads(p.read_text());d['bundle_id']='bad';p.write_text(json.dumps(d))
 with pytest.raises(ValueError,match='social_public_service_product_bundle_mismatch'):TraditionalSocialPublicServiceService(root)
