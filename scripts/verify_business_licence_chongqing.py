from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
FILES=('overview.json','business_places.json','admin_units.json','licence_channels.json','data_contracts.json','uwm_gate.json','map.json');FORBIDDEN={'valid_licence_business_count','unlicensed_business_count','business_opening_rate','business_exit_rate','business_survival_rate','employment_count','revenue','turnover','tax_contribution','economic_contribution','business_health_score','investment_attractiveness_score','investment_priority','policy_effect'}
def verify(root:Path):
 p={n:json.loads((root/n).read_text()) for n in FILES};ids={x.get('bundle_id') for x in p.values()}
 if len(ids)!=1 or None in ids:raise ValueError('bundle_mismatch')
 o=p['overview.json'];places=p['business_places.json']['business_places'];channels=p['licence_channels.json']['licence_channels'];gate=p['uwm_gate.json']['uwm_gate']
 if o.get('fabricated_value_count')!=0 or FORBIDDEN & set(o):raise ValueError('invalid_overview')
 if any(x.get('legal_entity_id') is not None or x.get('licence_status') is not None or x.get('operating_status') is not None for x in places):raise ValueError('poi_promoted_to_entity_or_operation')
 if any(FORBIDDEN & set(x) for x in places):raise ValueError('forbidden_economic_field')
 if any(x['status']=='unavailable' and x.get('value') is not None for x in channels.values()):raise ValueError('fabricated_licence')
 if any(v!='closed' for v in gate['mechanisms'].values()):raise ValueError('false_lifecycle_prediction')
 digest=hashlib.sha256(''.join((root/n).read_text() for n in FILES).encode()).hexdigest();return {'bundle_id':next(iter(ids)),'summary':o['summary'],'fabricated_value_count':0,'digest':'sha256:'+digest}
def main():
 q=argparse.ArgumentParser();q.add_argument('root',type=Path);a=q.parse_args();print(json.dumps(verify(a.root),ensure_ascii=False))
if __name__=='__main__':main()
