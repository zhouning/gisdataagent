from pathlib import Path
from data_agent.uwm.digital_readiness_service import DigitalReadinessService
def test_real_digital_readiness_service():
 s=DigitalReadinessService(Path('data/uwm_public_proxy/chongqing_central/digital_readiness_chongqing'));assert s.overview()['summary']['verified_platform_capability_count']==17
 assert len(s.platform_capabilities()['platform_capabilities'])==17
 assert all(x['value'] is None for x in s.infrastructure_channels()['infrastructure_channels'].values())
 assert s.uwm_gate()['uwm_gate']['status']=='closed'
