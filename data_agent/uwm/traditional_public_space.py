from __future__ import annotations
from hashlib import sha256
import json
from typing import Any,Mapping,Sequence
SCHEMA='traditional_livability.public_space_opportunity.v1'
DEMAND9_CHANNELS={
 'public_space_inventory':'implemented','strict_semantic_classification':'implemented','administrative_distribution':'implemented','category_diversity':'implemented','relative_public_space_evidence_gap':'proxy_only','availability_proxy':'proxy_only',
 'public_access_status':'unavailable','opening_hours':'unavailable','landscape_quality':'unavailable','street_vitality':'unavailable','attractiveness_actual_use':'unavailable','shade_tree_canopy':'unavailable','shaded_seating':'unavailable','street_furniture':'unavailable','visual_comfort':'unavailable','waterfront_accessibility':'unavailable','universal_accessibility':'unavailable','safety_lighting':'unavailable','authoritative_service_area':'unavailable','authoritative_per_capita_open_space':'unavailable','intervention_effect':'unavailable','future_demand':'unavailable'}
DENY_TERMS={'网吧','ktv','度假村','电影院','休闲场所','洗浴推拿场所','娱乐场所'}
def classify_public_space(record:Mapping[str,Any])->dict[str,Any]:
 secondary=str(record.get('raw_secondary_class') or '').strip();tertiary=str(record.get('raw_tertiary_class') or '').strip();combined=f'{secondary}|{tertiary}'.lower()
 if any(term.lower() in combined for term in DENY_TERMS):return {'classification_decision':'excluded_deny_list','classification_reason':'commercial_or_ambiguous_recreation_excluded','canonical_space_category':None}
 if secondary=='公园' or tertiary in {'城市广场','植物园','动物园','公园','公园广场'} or (secondary=='公园广场' and not tertiary):return {'classification_decision':'included','classification_reason':'explicit_park_or_plaza_allow_list','canonical_space_category':'core_open_space'}
 if secondary in {'图书馆','博物馆','科技馆'} or tertiary in {'图书馆','博物馆','科技馆'}:return {'classification_decision':'included','classification_reason':'explicit_civic_cultural_allow_list','canonical_space_category':'civic_cultural_space'}
 if secondary in {'运动场馆','体育场馆'} and tertiary in {'综合体育馆','体育馆','运动场馆',''}:return {'classification_decision':'included','classification_reason':'explicit_public_sports_venue_allow_list','canonical_space_category':'public_recreation_space'}
 return {'classification_decision':'excluded_ambiguous','classification_reason':'not_in_strict_public_space_allow_list','canonical_space_category':None}
def build_public_space_product(*,records:Sequence[Mapping[str,Any]],admin_units:Sequence[Mapping[str,Any]],source_artifacts:Sequence[str])->dict[str,Any]:
 spaces=[];excluded=[];seen=set()
 for source in records:
  sid=str(source.get('space_id') or '').strip()
  if not sid:raise ValueError('space_id_missing')
  if sid in seen:raise ValueError('duplicate_space_id')
  seen.add(sid);dataset=str(source.get('source_dataset') or '').strip();record_id=str(source.get('source_record_id') or '').strip()
  if not dataset or not record_id:raise ValueError('space_source_trace_missing')
  decision=classify_public_space(source);base={'space_id':sid,'name':source.get('name'),'raw_primary_class':source.get('raw_primary_class'),'raw_secondary_class':source.get('raw_secondary_class'),'raw_tertiary_class':source.get('raw_tertiary_class'),'canonical_space_category':decision['canonical_space_category'],'classification_decision':decision['classification_decision'],'classification_reason':decision['classification_reason'],'longitude':source.get('longitude'),'latitude':source.get('latitude'),'admin_unit_id':source.get('admin_unit_id'),'source_dataset':dataset,'source_record_id':record_id,'source_trace':{'source_dataset':dataset,'source_record_id':record_id}}
  if decision['classification_decision']=='included':spaces.append({**base,'public_access_status':None,'opening_hours':None,'quality_score':None,'vitality_score':None,'shade_evidence':None,'seating_evidence':None,'waterfront_access_evidence':None,'limitations':['public_access_quality_use_and_comfort_not_observed']})
  else:excluded.append(base)
 admins=_admins(admin_units,spaces);_rank_admins(admins)
 digest={'schema':SCHEMA,'spaces':sorted(spaces,key=lambda x:x['space_id']),'admin_units':admins,'source_artifacts':sorted(source_artifacts)};bundle='traditional-public-space-'+sha256(json.dumps(digest,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:20]
 return {'schema':SCHEMA,'bundle_id':bundle,'summary':{'eligible_space_count':len(spaces),'excluded_record_count':len(excluded),'admin_unit_count':len(admins)},'spaces':sorted(spaces,key=lambda x:x['space_id']),'excluded_records':sorted(excluded,key=lambda x:x['space_id']),'admin_units':admins,'channel_readiness':{k:{'status':v,'value':None,'relative_proxy_not_authoritative_standard':v=='proxy_only'} for k,v in DEMAND9_CHANNELS.items()},'source_artifacts':sorted(source_artifacts),'claim_boundary':{'max_claim_level':'observed_inventory_and_relative_public_space_evidence_gap','authoritative_public_space_shortage_claim':False,'observed_quality_claim':False,'observed_use_or_vitality_claim':False,'causal_intervention_effect_claim':False,'future_demand_claim':False},'fabricated_value_count':0,'production_blockers':['public_access_and_opening_hours_missing','quality_vitality_and_actual_use_missing','shade_seating_furniture_missing','waterfront_accessibility_missing','safety_and_universal_accessibility_missing','authoritative_per_capita_standard_missing','intervention_effect_evidence_missing']}
def _admins(admin_units,spaces):
 rows=[]
 for source in sorted(admin_units,key=lambda x:str(x.get('admin_unit_id'))):
  aid=str(source.get('admin_unit_id') or '').strip()
  if not aid:raise ValueError('admin_unit_id_missing')
  selected=[x for x in spaces if str(x.get('admin_unit_id') or '')==aid];cats=sorted({x['canonical_space_category'] for x in selected})
  core=sum(x['canonical_space_category']=='core_open_space' for x in selected);reasons=[]
  if core==0:reasons.append('zero_core_open_space')
  if not selected:reasons.append('zero_total_eligible_space')
  if len(cats)<=1:reasons.append('low_supported_category_diversity')
  rows.append({'admin_unit_id':aid,'county':source.get('county'),'core_open_space_count':core,'civic_cultural_space_count':sum(x['canonical_space_category']=='civic_cultural_space' for x in selected),'public_recreation_space_count':sum(x['canonical_space_category']=='public_recreation_space' for x in selected),'space_category_count':len(cats),'total_eligible_space_count':len(selected),'relative_public_space_evidence_gap_rank':None,'relative_gap_reasons':reasons,'relative_proxy_not_authoritative_standard':True,'observed_public_space_use':False,'observed_quality':False,'policy_outcome_claim':False,'authoritative_public_space_shortage':None})
 return rows
def _rank_admins(rows):
 ordered=sorted(rows,key=lambda x:(0 if x['core_open_space_count']==0 else 1,0 if x['total_eligible_space_count']==0 else 1,x['space_category_count'],x['core_open_space_count'],x['total_eligible_space_count'],x['admin_unit_id']))
 for rank,row in enumerate(ordered,1):row['relative_public_space_evidence_gap_rank']=rank
