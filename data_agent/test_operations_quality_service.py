from pathlib import Path
from data_agent.uwm.operations_quality_service import OperationsQualityService
def test_real_operations_quality_service():
 s=OperationsQualityService(Path('data/uwm_public_proxy/chongqing_central/operations_quality_chongqing'));assert s.overview()['summary']['platform_operation_capability_count']==14
 assert len(s.platform_operations()['platform_operations'])==14
 assert all(x['value'] is None for x in s.customer_channels()['customer_channels'].values())
 assert s.uwm_gate()['uwm_gate']['status']=='closed'
