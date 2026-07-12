from __future__ import annotations
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from data_agent.uwm.resilience_kernel import validate_resilience_graph
FILES=('overview.json','state.json','graph.json','evidence_gates.json','current_rollout.json','dependency_chain.json','map.json');FORBIDDEN={'resilience_score','vulnerability_score','hazard_loss','expected_damage','mortality','response_effectiveness','recovery_time','recovery_probability','intervention_benefit','robustness_score'}
def verify(root:Path):
 p={n:json.loads((root/n).read_text()) for n in FILES};ids={x.get('bundle_id') for x in p.values()}
 if len(ids)!=1 or None in ids:raise ValueError('bundle_mismatch')
 o=p['overview.json'];state=p['state.json']['state'];edges=p['graph.json']['edges'];roll=p['current_rollout.json']['current_rollout'];validate_resilience_graph(edges)
 if o.get('fabricated_value_count')!=0:raise ValueError('fabricated_values')
 if any(FORBIDDEN & set(x) for x in state) or FORBIDDEN & set(roll):raise ValueError('forbidden_prediction_field')
 if roll.get('future_trajectory') is not None:raise ValueError('closed_rollout_has_trajectory')
 if any(roll[k]!='closed' for k in ('disturbance_transition_status','hazard_propagation_status','response_capacity_status','recovery_transition_status','intervention_effect_status','counterfactual_status')):raise ValueError('mechanism_open_without_evidence')
 digest=hashlib.sha256(''.join((root/n).read_text() for n in FILES).encode()).hexdigest();return {'bundle_id':next(iter(ids)),'summary':o['summary'],'fabricated_value_count':0,'digest':'sha256:'+digest}
def main():
 q=argparse.ArgumentParser();q.add_argument('root',type=Path);a=q.parse_args();print(json.dumps(verify(a.root),ensure_ascii=False))
if __name__=='__main__':main()
