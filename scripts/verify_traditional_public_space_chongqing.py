from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
FILES=('overview.json','spaces.json','admin_units.json','channel_readiness.json','map.json');DENY=('网吧','ktv','度假村','电影院','洗浴推拿')
def verify_product(root:Path):
 p={n:json.loads((root/n).read_text(encoding='utf-8')) for n in FILES};ids={x.get('bundle_id') for x in p.values()}
 if len(ids)!=1:raise ValueError('bundle_id_mismatch')
 seen=set()
 for row in p['spaces.json']['spaces']:
  if row['space_id'] in seen:raise ValueError('duplicate_space_id')
  seen.add(row['space_id'])
  if not row.get('source_dataset') or not row.get('source_record_id'):raise ValueError('space_source_trace_missing')
  text='|'.join(str(row.get(x) or '') for x in ('name','raw_secondary_class','raw_tertiary_class')).lower()
  if any(term in text for term in DENY):raise ValueError('deny_list_record_in_eligible_spaces')
  for field in ('public_access_status','opening_hours','quality_score','vitality_score','shade_evidence','seating_evidence','waterfront_access_evidence'):
   if row.get(field) is not None:raise ValueError('unavailable_observation_present')
 for view in p['channel_readiness.json']['channel_readiness'].values():
  if view['status']=='unavailable' and view.get('value') is not None:raise ValueError('unavailable_channel_value_present')
 if p['overview.json'].get('fabricated_value_count')!=0:raise ValueError('fabricated_value_count_nonzero')
 ranks=[x['relative_public_space_evidence_gap_rank'] for x in p['admin_units.json']['admin_units']]
 if sorted(ranks)!=list(range(1,len(ranks)+1)):raise ValueError('ranking_not_contiguous')
 digest=hashlib.sha256(''.join((root/n).read_text(encoding='utf-8') for n in FILES).encode()).hexdigest()
 return {'verified':True,'bundle_id':ids.pop(),'eligible_space_count':len(p['spaces.json']['spaces']),'excluded_record_count':len(p['spaces.json']['excluded_records']),'admin_unit_count':len(ranks),'fabricated_value_count':0,'verification_digest':'sha256:'+digest}
def main():
 p=argparse.ArgumentParser();p.add_argument('--product-dir',type=Path,required=True);a=p.parse_args();print(json.dumps(verify_product(a.product_dir),ensure_ascii=False))
if __name__=='__main__':main()
