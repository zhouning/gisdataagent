from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
FILES=('overview.json','admin_units.json','channel_readiness.json','evidence_sources.json','map.json')
FORBIDDEN={'housing_unit_count','residential_floor_area','housing_supply','housing_shortage','affordability_score','crowding_score','family_suitability_score','mixed_use_balance_score'}
def verify(root:Path):
 payloads={name:json.loads((root/name).read_text()) for name in FILES};ids={x.get('bundle_id') for x in payloads.values()}
 if len(ids)!=1 or None in ids:raise ValueError('bundle_mismatch')
 overview=payloads['overview.json'];admins=payloads['admin_units.json']['admin_units'];channels=payloads['channel_readiness.json']['channel_readiness']
 if overview.get('schema')!='traditional_livability.housing_community_evidence.v1':raise ValueError('schema_invalid')
 if overview.get('fabricated_value_count')!=0:raise ValueError('fabricated_values_present')
 for row in admins:
  if FORBIDDEN & set(row):raise ValueError('forbidden_housing_outcome_field')
  if row['building_morphology_context']['join_status']=='incompatible' and row['building_morphology_context']['building_count'] is not None:raise ValueError('inferred_morphology_join')
  if not row['limitations'].get('relative_gap_not_authoritative_housing_shortage'):raise ValueError('claim_boundary_missing')
 for name,item in channels.items():
  if item['status']=='unavailable' and item.get('value') is not None:raise ValueError(f'unavailable_value_present:{name}')
 digest=hashlib.sha256(''.join((root/name).read_text() for name in FILES).encode()).hexdigest()
 return {'bundle_id':next(iter(ids)),'admin_unit_count':len(admins),'fabricated_value_count':0,'digest':'sha256:'+digest}
def main():
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();print(json.dumps(verify(a.root),ensure_ascii=False))
if __name__=='__main__':main()
