from pathlib import Path
from data_agent.uwm.dependency_roadmap_service import DependencyRoadmapService
def test_real_roadmap_service():
 s=DependencyRoadmapService(Path('data/uwm_public_proxy/chongqing_central/dependency_roadmap_chongqing'));assert s.overview()['summary']['task_count']==42
 assert s.tasks(status='blocked')['count']==15
 assert len(s.domains()['domain_chains'])==5
 x=s.tasks();x['tasks'][0]['status']='changed';assert s.tasks()['tasks'][0]['status']!='changed'
