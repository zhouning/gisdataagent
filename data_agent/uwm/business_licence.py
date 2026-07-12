from __future__ import annotations
import hashlib,json
from collections import Counter
from copy import deepcopy
CHANNELS=('entity_registry','business_licence_registry','licence_status_history','licensed_activity_taxonomy','branch_relationships','registered_operating_address_crosswalk','inspection_and_enforcement_records')
def build_business_licence_product(*,business_places,admin_units,source_artifacts):
 places=[]
 for raw in business_places:
  x=deepcopy(raw);x.update({'legal_entity_id':None,'licence_id':None,'licence_status':None,'operating_status':None,'company_poi_not_legal_entity_registry':True,'poi_presence_not_valid_business_licence':True,'poi_presence_not_active_operation':True,'company_name_not_authoritative_entity_match':True,'industrial_poi_not_observed_production':True,'business_count_not_employment_or_output':True});places.append(x)
 grouped={str(x['admin_unit_id']):[] for x in admin_units};names={str(x['admin_unit_id']):x.get('admin_name') for x in admin_units}
 for x in places:
  if str(x.get('admin_unit_id')) in grouped:grouped[str(x['admin_unit_id'])].append(x)
 admins=[]
 for aid,rows in grouped.items():
  c=Counter(x['canonical_category'] for x in rows);admins.append({'admin_unit_id':aid,'admin_name':names[aid],'business_poi_count':len(rows),'category_counts':dict(sorted(c.items())),'category_count':len(c),'licence_channel_available_count':0,'lifecycle_channel_available_count':0,'relative_business_licence_evidence_readiness_rank':None,'limitations':{'rank_not_economic_performance_or_investment_priority':True,'missing_licence_data_not_unlicensed_business':True}})
 for rank,x in enumerate(sorted(admins,key=lambda x:(x['business_poi_count'],x['category_count'],x['admin_unit_id'])),1):x['relative_business_licence_evidence_readiness_rank']=rank
 channels={k:{'status':'unavailable','value':None,'production_blockers':['authoritative_ded_licence_source_missing']} for k in CHANNELS};contracts={'licence':{'required_fields':['licence_id','entity_id','entity_name','licence_type','licensed_activity','issuing_authority','issue_date','expiry_date','licence_status','registered_address','operating_address','longitude','latitude','admin_unit_id','status_observed_at','source_system','source_record_id']},'lifecycle_event':{'required_fields':['entity_id','event_type','event_time','source_system','source_record_id','status_provenance']}}
 gate={'status':'closed','mechanisms':{'active_operation_inference':'closed','opening_closure_prediction':'closed','relocation_expansion_prediction':'closed','employment_output_prediction':'closed','licence_policy_response':'closed','business_survival_estimation':'closed','investment_intervention_effect':'closed'}}
 digest={'places':places,'admins':admins};bid='business-licence-'+hashlib.sha256(json.dumps(digest,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:20]
 return {'schema':'uwm.business_licence_activity_readiness.v1','bundle_id':bid,'summary':{'business_poi_count':len(places),'admin_unit_count':len(admins),'available_licence_channel_count':0,'open_lifecycle_mechanism_count':0},'business_places':places,'admin_units':admins,'licence_channels':channels,'data_contracts':contracts,'uwm_gate':gate,'source_artifacts':sorted(map(str,source_artifacts)),'claim_boundary':{'max_claim_level':'business_poi_spatial_evidence_and_authoritative_licence_lifecycle_readiness','company_poi_not_legal_entity_registry':True,'poi_presence_not_valid_business_licence':True,'poi_presence_not_active_operation':True,'company_name_not_authoritative_entity_match':True,'industrial_poi_not_observed_production':True,'business_count_not_employment_or_output':True,'missing_licence_data_not_unlicensed_business':True},'fabricated_value_count':0}
