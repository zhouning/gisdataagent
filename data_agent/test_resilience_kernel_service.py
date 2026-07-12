from pathlib import Path
from data_agent.uwm.resilience_kernel_service import ResilienceKernelService
def test_real_resilience_service():
 s=ResilienceKernelService(Path('data/uwm_public_proxy/chongqing_central/resilience_kernel_chongqing'));assert s.overview()['summary']['state_node_count']==1017
 assert len(s.graph()['edges'])==250
 assert len(s.gates()['evidence_gates'])==7
 assert s.rollout()['current_rollout']['future_trajectory'] is None
 assert len(s.dependencies()['dependency_chain'])==6
