from pathlib import Path
from data_agent.uwm.traditional_cultural_heritage_service import TraditionalCulturalHeritageService
def test_real_cultural_heritage_service():
 s=TraditionalCulturalHeritageService(Path('data/uwm_public_proxy/chongqing_central/traditional_cultural_heritage_chongqing'));o=s.overview();assert o['summary']['confirmed_place_count']==242
 assert s.places('heritage_candidate_leads')['count']==59
 rows=s.admin_units();assert rows['count']==39
 first=rows['admin_units'][0];first['admin_name']='changed';assert s.admin_unit(first['admin_unit_id'])['admin_name']!='changed'
 assert len(s.map_payload('confirmed_cultural_place_evidence')['layers'])==1
