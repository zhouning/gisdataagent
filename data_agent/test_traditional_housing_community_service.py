import json
from pathlib import Path
from data_agent.uwm.traditional_housing_community_service import TraditionalHousingCommunityService

def test_real_product_service_contract():
 root=Path('data/uwm_public_proxy/chongqing_central/traditional_housing_community_chongqing');service=TraditionalHousingCommunityService(root)
 overview=service.overview();assert overview['summary']['admin_unit_count']==852
 rows=service.admin_units('housing_evidence_readiness');assert rows['count']==852
 first=rows['admin_units'][0];first['county']='changed';assert service.admin_unit(first['admin_unit_id'])['county']!='changed'
 assert len(service.map_payload('population_context')['layers'])==1
 assert service.readiness()['channel_readiness']['affordability']['value'] is None
