from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
FILES=('overview.json','platform_operations.json','customer_channels.json','data_contracts.json','uwm_gate.json','map.json');FORBIDDEN={'customer_sla_compliance_rate','service_availability_rate','mttr','mtbf','customer_satisfaction_score','ticket_closure_rate','root_cause_distribution','maintenance_cost','failure_recurrence_probability','operations_performance_rank','sla_breach_prediction'}
def verify(root:Path):
 p={n:json.loads((root/n).read_text()) for n in FILES};ids={x.get('bundle_id') for x in p.values()}
 if len(ids)!=1 or None in ids:raise ValueError('bundle_mismatch')
 o=p['overview.json'];caps=p['platform_operations.json']['platform_operations'];channels=p['customer_channels.json']['customer_channels'];gate=p['uwm_gate.json']['uwm_gate']
 if o.get('fabricated_value_count')!=0 or FORBIDDEN & set(o):raise ValueError('invalid_overview')
 if any(not x.get('evidence_paths') for x in caps):raise ValueError('capability_without_evidence')
 if any(x['status']=='unavailable' and x.get('value') is not None for x in channels.values()):raise ValueError('fabricated_customer_metric')
 if any(v!='closed' for v in gate['mechanisms'].values()):raise ValueError('false_operations_prediction')
 digest=hashlib.sha256(''.join((root/n).read_text() for n in FILES).encode()).hexdigest();return {'bundle_id':next(iter(ids)),'summary':o['summary'],'fabricated_value_count':0,'digest':'sha256:'+digest}
def main():
 q=argparse.ArgumentParser();q.add_argument('root',type=Path);a=q.parse_args();print(json.dumps(verify(a.root),ensure_ascii=False))
if __name__=='__main__':main()
