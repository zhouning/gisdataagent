from __future__ import annotations
import hashlib,json
from copy import deepcopy
SCHEMA='uwm.cross_domain_impact_evidence.v1'
CLOSED_GATES={'housing':'housing_transition_calibration_missing','culture':'cultural_asset_transition_calibration_missing','economy':'authoritative_economic_lifecycle_and_response_missing','resilience':'hazard_propagation_response_recovery_calibration_missing'}
def _compare(a,b):
 if a['spatial_grain']!=b['spatial_grain'] or a['unit_identifier_contract']!=b['unit_identifier_contract']:return 'incompatible','spatial_grain_or_identifier_mismatch'
 if a.get('temporal_scope')!=b.get('temporal_scope'):return 'reference_only','temporal_scope_mismatch'
 return 'exact_comparable','identical_grain_identifier_and_temporal_scope'
def build_cross_domain_impact_product(*,source_products):
 sources=[]
 for raw in source_products:
  x=deepcopy(raw);x['unit_count']=len(x.get('units',[]));sources.append(x)
 matrix=[]
 for i,a in enumerate(sources):
  for b in sources[i+1:]:
   status,reason=_compare(a,b);matrix.append({'left_domain_id':a['domain_id'],'right_domain_id':b['domain_id'],'status':status,'reason':reason})
 district=[x for x in sources if x['spatial_grain']=='district' and x['unit_identifier_contract']=='admin_code'];ids=sorted({str(u['admin_unit_id']) for x in district for u in x.get('units',[]) if u.get('admin_unit_id')})
 units=[]
 for aid in ids:
  evidence={};name=None;blockers=0
  for product in district:
   row=next((u for u in product.get('units',[]) if str(u.get('admin_unit_id'))==aid),None)
   if row:
    name=name or row.get('admin_name');evidence[product['domain_id']]={'native_gap_rank':row.get('native_gap_rank'),'source_bundle_id':product['bundle_id'],'max_claim_level':product['max_claim_level']};blockers+=int(row.get('production_blocker_count') or len(product.get('production_blockers',[])))
  missing=len(district)-len(evidence);units.append({'admin_unit_id':aid,'admin_name':name,'domain_evidence':evidence,'compatible_domain_count':len(evidence),'reference_only_domain_count':len(sources)-len(district),'unavailable_channel_count':missing,'production_blocker_count':blockers,'cross_domain_evidence_gap_reasons':(['compatible_domain_evidence_missing'] if missing else [])+(['source_production_blockers_present'] if blockers else []),'dependency_requirements':sorted({b for p in sources for b in p.get('production_blockers',[])}),'source_trace':{k:v['source_bundle_id'] for k,v in evidence.items()},'limitations':{'cross_domain_priority_not_outcome_severity':True,'evidence_gap_not_observed_deprivation':True,'rank_not_investment_return':True,'reference_only_not_joined_observation':True}})
 ordered=sorted(units,key=lambda x:(-x['unavailable_channel_count'],-x['production_blocker_count'],x['compatible_domain_count'],x['admin_unit_id']))
 for rank,row in enumerate(ordered,1):row['cross_domain_evidence_priority_rank']=rank
 dynamic={x['domain_id']:{'technology_route':x['technology_route'],'bundle_id':x['bundle_id'],'max_claim_level':x['max_claim_level']} for x in sources if x['technology_route']=='uwm_calibrated_dynamic'}
 for domain,blocker in CLOSED_GATES.items():dynamic.setdefault(domain,{'technology_route':'uwm_closed_gate','bundle_id':None,'max_claim_level':None,'blockers':[blocker]})
 digest={'sources':sources,'matrix':matrix,'units':units};bid='cross-domain-impact-'+hashlib.sha256(json.dumps(digest,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:20]
 return {'schema':SCHEMA,'bundle_id':bid,'source_products':sources,'comparability_matrix':matrix,'priority_units':sorted(units,key=lambda x:x['admin_unit_id']),'dynamic_channels':dynamic,'dependency_graph':{'housing':['housing_stock_state','household_transitions','interventions','held_out_calibration'],'culture':['longitudinal_asset_condition','activity','intervention_outcomes'],'economy':['authoritative_licences','lifecycle','employment_or_transactions'],'resilience':['hazards','exposure','response_capacity','propagation','recovery'],'investment':['costs','benefits','funding','feasibility','risk']},'claim_boundary':{'max_claim_level':'cross_domain_evidence_compatibility_priority_and_dynamic_channel_readiness','cross_domain_priority_not_outcome_severity':True,'evidence_gap_not_observed_deprivation':True,'rank_not_investment_return':True,'product_presence_not_requirement_completion':True,'reference_only_not_joined_observation':True,'static_evidence_not_dynamic_impact':True,'closed_uwm_gate_not_simulation':True,'calibrated_environment_channel_not_general_uwm':True},'fabricated_value_count':0}
