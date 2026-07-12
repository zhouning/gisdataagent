from pathlib import Path
from data_agent.uwm.business_licence_service import BusinessLicenceService
def test_real_business_licence_service():
 s=BusinessLicenceService(Path('data/uwm_public_proxy/chongqing_central/business_licence_chongqing'));assert s.overview()['summary']['business_poi_count']==3749
 assert len(s.places()['business_places'])==3749
 assert len(s.admin_units()['admin_units'])==39
 assert all(x['value'] is None for x in s.licence_channels()['licence_channels'].values())
 assert s.uwm_gate()['uwm_gate']['status']=='closed'
