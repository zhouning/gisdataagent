from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
FILES=('overview.json','admin_units.json','channel_readiness.json','evidence_sources.json','map.json');FORBIDDEN=('safety_score','crime_score','pedestrian_risk_score','thermal_comfort_score','safe_route_score','investment_priority_score')
def verify_product(root:Path):
 p={n:json.loads((root/n).read_text()) for n in FILES};ids={x.get('bundle_id') for x in p.values()}
 if len(ids)!=1:raise ValueError('bundle_id_mismatch')
 overview=p['overview.json']
 if overview.get('fabricated_value_count')!=0:raise ValueError('fabricated_value_count_nonzero')
 if overview['summary'].get('joined_environment_row_count')!=0:raise ValueError('unsupported_environment_join_present')
 if overview['summary'].get('joined_public_safety_facility_count')!=0:raise ValueError('unsupported_facility_join_present')
 for row in p['admin_units.json']['admin_units']:
  if any(k in row for k in FORBIDDEN):raise ValueError('forbidden_safety_or_comfort_score')
  if row['mobility_context'].get('network_context_not_road_safety') is not True:raise ValueError('network_context_claim_gate_missing')
  if row['meteorology_context'].get('temperature_context_not_thermal_comfort') is not True:raise ValueError('temperature_context_claim_gate_missing')
  if row.get('evidence_gap_not_danger_level') is not True:raise ValueError('evidence_gap_danger_gate_missing')
 for source in p['evidence_sources.json']['evidence_sources']:
  if source['source_id'] in {'environment','public_safety_facility'} and source['join_status'] not in {'reference_only','incompatible'}:raise ValueError('unsupported_cross_source_join_status')
 for channel in p['channel_readiness.json']['channel_readiness'].values():
  if channel['status']=='unavailable' and channel.get('value') is not None:raise ValueError('unavailable_channel_value_present')
 ranks=[x['relative_safety_comfort_evidence_gap_rank'] for x in p['admin_units.json']['admin_units']]
 if sorted(ranks)!=list(range(1,len(ranks)+1)):raise ValueError('ranking_not_contiguous')
 digest=hashlib.sha256(''.join((root/n).read_text() for n in FILES).encode()).hexdigest();return {'verified':True,'bundle_id':ids.pop(),'admin_unit_count':len(ranks),'environment_reference_row_count':overview['summary']['environment_reference_row_count'],'observed_public_safety_facility_count':overview['summary']['observed_public_safety_facility_count'],'joined_environment_row_count':0,'fabricated_value_count':0,'verification_digest':'sha256:'+digest}
def main():
 p=argparse.ArgumentParser();p.add_argument('--product-dir',type=Path,required=True);a=p.parse_args();print(json.dumps(verify_product(a.product_dir),ensure_ascii=False))
if __name__=='__main__':main()
