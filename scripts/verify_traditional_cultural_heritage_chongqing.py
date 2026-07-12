from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
FILES=('overview.json','places.json','admin_units.json','channel_readiness.json','map.json');FORBIDDEN={'legal_heritage_level','cultural_value_score','authenticity_score','integrity_score','protection_quality_score','visitor_attractiveness_score','community_identity_score','activation_potential_score','investment_priority_score','policy_effect_score'}
def verify(root:Path):
 p={n:json.loads((root/n).read_text()) for n in FILES};ids={x.get('bundle_id') for x in p.values()}
 if len(ids)!=1 or None in ids:raise ValueError('bundle_mismatch')
 o=p['overview.json'];places=p['places.json']['places'];channels=p['channel_readiness.json']['channel_readiness']
 if o.get('schema')!='traditional_livability.cultural_heritage_place_evidence.v1' or o.get('fabricated_value_count')!=0:raise ValueError('overview_invalid')
 for x in places:
  if FORBIDDEN & set(x):raise ValueError('forbidden_score_present')
  if x.get('legal_heritage_status') is not None:raise ValueError('legal_status_inferred')
  if x['evidence_tier']=='confirmed_cultural_place_evidence' and x['classification_basis']!='explicit_source_category':raise ValueError('keyword_promoted_to_confirmed')
 for k,v in channels.items():
  if v['status']=='unavailable' and v.get('value') is not None:raise ValueError('unavailable_value_present:'+k)
 digest=hashlib.sha256(''.join((root/n).read_text() for n in FILES).encode()).hexdigest();return {'bundle_id':next(iter(ids)),'summary':o['summary'],'fabricated_value_count':0,'digest':'sha256:'+digest}
def main():
 q=argparse.ArgumentParser();q.add_argument('root',type=Path);a=q.parse_args();print(json.dumps(verify(a.root),ensure_ascii=False))
if __name__=='__main__':main()
