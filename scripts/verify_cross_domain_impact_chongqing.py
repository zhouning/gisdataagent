from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
FILES=('overview.json','source_products.json','comparability_matrix.json','priority_units.json','dependency_graph.json','map.json');FORBIDDEN={'overall_livability_score','composite_impact_score','policy_benefit_score','investment_return_score','worst_district','best_intervention'}
def verify(root:Path):
 p={n:json.loads((root/n).read_text()) for n in FILES};ids={x.get('bundle_id') for x in p.values()}
 if len(ids)!=1 or None in ids:raise ValueError('bundle_mismatch')
 o=p['overview.json'];sources=p['source_products.json']['source_products'];matrix=p['comparability_matrix.json']['comparability_matrix'];units=p['priority_units.json']['priority_units']
 if o.get('fabricated_value_count')!=0:raise ValueError('fabricated_values')
 for x in units:
  if FORBIDDEN & set(x):raise ValueError('forbidden_composite')
  if not x['limitations'].get('reference_only_not_joined_observation'):raise ValueError('join_boundary_missing')
 for x in matrix:
  if x['status']=='exact_comparable':
   a=next(s for s in sources if s['domain_id']==x['left_domain_id']);b=next(s for s in sources if s['domain_id']==x['right_domain_id'])
   if a['spatial_grain']!=b['spatial_grain'] or a['unit_identifier_contract']!=b['unit_identifier_contract']:raise ValueError('inferred_exact_join')
 dynamic=o['dynamic_channels']
 for domain in ('housing','culture','economy','resilience'):
  if dynamic[domain]['technology_route']!='uwm_closed_gate':raise ValueError('false_dynamic_channel')
 digest=hashlib.sha256(''.join((root/n).read_text() for n in FILES).encode()).hexdigest();return {'bundle_id':next(iter(ids)),'summary':o['summary'],'fabricated_value_count':0,'digest':'sha256:'+digest}
def main():
 q=argparse.ArgumentParser();q.add_argument('root',type=Path);a=q.parse_args();print(json.dumps(verify(a.root),ensure_ascii=False))
if __name__=='__main__':main()
