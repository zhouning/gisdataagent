from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
FILES=('overview.json','places.json','admin_units.json','channel_readiness.json','map.json');ECON=('operating_status','opening_hours','employment_count','revenue','transaction_volume','customer_visits','service_capacity')
def verify_product(root:Path):
 p={n:json.loads((root/n).read_text()) for n in FILES};ids={x.get('bundle_id') for x in p.values()}
 if len(ids)!=1:raise ValueError('bundle_id_mismatch')
 seen=set()
 for row in p['places.json']['places']:
  if row['place_id'] in seen:raise ValueError('duplicate_place_id')
  seen.add(row['place_id'])
  if not row.get('source_dataset') or not row.get('source_record_id'):raise ValueError('place_source_trace_missing')
  if row.get('raw_secondary_class')=='自动提款机' and row.get('canonical_category')!='atm_access_point':raise ValueError('atm_bank_classification_violation')
  if row.get('canonical_category')=='atm_access_point' and row.get('raw_secondary_class')!='自动提款机':raise ValueError('atm_bank_classification_violation')
  if any(row.get(x) is not None for x in ECON):raise ValueError('unavailable_economic_value_present')
  if row.get('canonical_category')=='company_poi' and row.get('company_poi_not_employment_count') is not True:raise ValueError('company_employment_claim_gate_missing')
 if p['overview.json'].get('fabricated_value_count')!=0:raise ValueError('fabricated_value_count_nonzero')
 if p['overview.json']['summary'].get('exact_accessibility_match_count')!=0:raise ValueError('unsupported_accessibility_join_present')
 for c in p['channel_readiness.json']['channel_readiness'].values():
  if c['status']=='unavailable' and c.get('value') is not None:raise ValueError('unavailable_channel_value_present')
 ranks=[x['relative_daily_convenience_evidence_gap_rank'] for x in p['admin_units.json']['admin_units']]
 if sorted(ranks)!=list(range(1,len(ranks)+1)):raise ValueError('ranking_not_contiguous')
 digest=hashlib.sha256(''.join((root/n).read_text() for n in FILES).encode()).hexdigest();s=p['overview.json']['summary'];return {'verified':True,'bundle_id':ids.pop(),'daily_convenience_place_count':s['daily_convenience_place_count'],'business_activity_place_count':s['business_activity_place_count'],'bank_branch_count':s['bank_branch_count'],'atm_access_point_count':s['atm_access_point_count'],'exact_accessibility_match_count':0,'fabricated_value_count':0,'verification_digest':'sha256:'+digest}
def main():
 p=argparse.ArgumentParser();p.add_argument('--product-dir',type=Path,required=True);a=p.parse_args();print(json.dumps(verify_product(a.product_dir),ensure_ascii=False))
if __name__=='__main__':main()
