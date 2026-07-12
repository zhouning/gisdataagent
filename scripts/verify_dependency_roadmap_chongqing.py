from __future__ import annotations
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from data_agent.uwm.dependency_roadmap import validate_task_graph
FILES=('overview.json','tasks.json','dependency_graph.json','domain_chains.json','gates.json','map.json');FORBIDDEN=('capital_budget','operating_budget','implementation_duration','start_date','completion_date','responsible_agency','expected_benefit','investment_return','policy_effect')
def verify(root:Path):
 p={n:json.loads((root/n).read_text()) for n in FILES};ids={x.get('bundle_id') for x in p.values()}
 if len(ids)!=1 or None in ids:raise ValueError('bundle_mismatch')
 o=p['overview.json'];tasks=p['tasks.json']['tasks'];validate_task_graph(tasks)
 if o.get('fabricated_value_count')!=0:raise ValueError('fabricated_values')
 by={x['task_id']:x for x in tasks}
 for x in tasks:
  if any(x.get(k) is not None for k in FORBIDDEN):raise ValueError('forbidden_recommendation_value')
  if x['status']=='blocked' and not x['blocking_evidence']:raise ValueError('blocked_without_evidence')
  if x['phase']=='phase_4_decision_product_release' and any(by[p]['status']!='verified' for p in x['prerequisite_task_ids']):
   if x['status']!='blocked':raise ValueError('premature_release')
 digest=hashlib.sha256(''.join((root/n).read_text() for n in FILES).encode()).hexdigest();return {'bundle_id':next(iter(ids)),'summary':o['summary'],'fabricated_value_count':0,'digest':'sha256:'+digest}
def main():
 q=argparse.ArgumentParser();q.add_argument('root',type=Path);a=q.parse_args();print(json.dumps(verify(a.root),ensure_ascii=False))
if __name__=='__main__':main()
