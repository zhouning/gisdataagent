from pathlib import Path
from data_agent.uwm.cross_domain_impact_service import CrossDomainImpactService
def test_real_cross_domain_service():
 s=CrossDomainImpactService(Path('data/uwm_public_proxy/chongqing_central/cross_domain_impact_chongqing'));assert s.overview()['summary']['source_product_count']==7
 assert len(s.source_products()['source_products'])==7
 assert len(s.priority_units()['priority_units'])==39
 x=s.priority_units();x['priority_units'][0]['admin_name']='changed';assert s.priority_units()['priority_units'][0]['admin_name']!='changed'
 assert len(s.map_payload()['layers'])==1
