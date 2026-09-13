from __future__ import annotations
import hashlib,json
from collections import Counter
from copy import deepcopy
SCHEMA='traditional_livability.cultural_heritage_place_evidence.v1'
VIEWS={x:{'demand_id':'16'} for x in ('confirmed_cultural_place_evidence','heritage_candidate_leads','excluded_ambiguous_records','heritage_evidence_readiness')}
CHANNELS={'cultural_place_classification':'implemented','spatial_distribution':'implemented','administrative_inventory':'implemented','ambiguity_diagnostics':'implemented','heritage_candidate_leads':'proxy_only','poi_inventory_coverage':'proxy_only','legal_heritage_designation':'unavailable','authenticity_integrity_significance':'unavailable','opening_operation_public_access':'unavailable','visitor_counts_actual_use':'unavailable','community_identity_participation':'unavailable','protection_condition_restoration_quality':'unavailable','cultural_economy_employment_revenue':'unavailable','activation_investment_priority':'unavailable','intervention_causal_effects':'unavailable'}
KEYWORDS=('遗址','故居','古镇','古街','文物','纪念碑','纪念馆','博物馆','寺','庙','教堂')
EXCLUDED_PRIMARY=('地名地址信息','金融保险服务','金融保险','交通设施','通行设施','酒店','购物','购物服务','餐饮','餐饮服务','公司企业','商务住宅','生活服务','教育培训','医疗保健服务','政府机构','政府机构及社会团体')
def _text(*xs):return '|'.join(str(x or '').strip() for x in xs)
def classify(record):
 p=str(record.get('raw_primary_class') or '');s=str(record.get('raw_secondary_class') or '');t=str(record.get('raw_tertiary_class') or '');name=str(record.get('name') or '');cats=_text(p,s,t)
 category=None
 if '博物馆' in cats:category='museum'
 elif '纪念馆' in cats:category='memorial_hall'
 elif any(x in cats for x in ('文物古迹','文化遗址','历史遗址')):category='cultural_relic_site'
 elif any(x in cats for x in ('寺庙','寺庙道观','教堂')):category='religious_place'
 elif '文化馆' in cats or '文化中心' in cats:category='cultural_center'
 elif any(x in cats for x in ('展览馆','美术馆','画廊')):category='exhibition_gallery'
 if category:return 'confirmed_cultural_place_evidence',category,'explicit_source_category'
 has_keyword=any(x in name for x in KEYWORDS)
 if has_keyword and any(p.startswith(x) for x in EXCLUDED_PRIMARY):return 'excluded_ambiguous_records',None,'incompatible_source_category'
 if has_keyword:return 'heritage_candidate_leads','historic_place_context','name_keyword_requires_verification'
 return None,None,'not_cultural_evidence'
def build_cultural_heritage_product(*,records,admin_units,source_artifacts):
 places=[];unrelated=0
 for r in records:
  tier,cat,basis=classify(r)
  if not tier:unrelated+=1;continue
  row={k:r.get(k) for k in ('place_id','name','raw_primary_class','raw_secondary_class','raw_tertiary_class','longitude','latitude','admin_unit_id','source_dataset','source_record_id')};row.update({'canonical_category':cat,'evidence_tier':tier,'candidate_status':'requires_authoritative_verification' if tier=='heritage_candidate_leads' else None,'legal_heritage_status':None,'classification_basis':basis,'exclusion_reason':basis if tier=='excluded_ambiguous_records' else None,'claim_boundary':{'cultural_place_poi_not_legal_heritage_designation':True,'religious_place_not_automatic_protected_relic':True,'name_keyword_only_candidate_lead':True,'poi_presence_not_opening_or_operation':True}});places.append(row)
 grouped={str(x['admin_unit_id']):[] for x in admin_units}
 names={str(x['admin_unit_id']):x.get('admin_name') or x.get('county') for x in admin_units}
 for x in places:
  aid=str(x.get('admin_unit_id') or '')
  if aid in grouped:grouped[aid].append(x)
 admins=[]
 for aid,rows in grouped.items():
  confirmed=[x for x in rows if x['evidence_tier']=='confirmed_cultural_place_evidence'];candidates=[x for x in rows if x['evidence_tier']=='heritage_candidate_leads'];excluded=[x for x in rows if x['evidence_tier']=='excluded_ambiguous_records'];counts=Counter(x['canonical_category'] for x in confirmed);sources={x.get('source_dataset') for x in confirmed if x.get('source_dataset')};reasons=[]
  if not confirmed:reasons.append('confirmed_cultural_place_evidence_missing')
  if len(candidates)>len(confirmed):reasons.append('candidate_to_confirmed_imbalance')
  if len(counts)<2:reasons.append('low_confirmed_category_diversity')
  if len(sources)<2:reasons.append('low_source_dataset_diversity')
  admins.append({'admin_unit_id':aid,'admin_name':names.get(aid),'confirmed_place_count':len(confirmed),'confirmed_category_counts':dict(sorted(counts.items())),'confirmed_category_count':len(counts),'candidate_lead_count':len(candidates),'excluded_ambiguous_count':len(excluded),'source_dataset_count':len(sources),'evidence_gap_reasons':reasons,'verification_priorities':['link_authoritative_heritage_register','verify_legal_status_and_opening','collect_asset_geometry_and_condition','collect_longitudinal_activity_and_interventions'],'limitations':{'relative_gap_not_cultural_resource_deprivation':True,'candidate_lead_not_authoritative_inventory':True}})
 ordered=sorted(admins,key=lambda x:(0 if x['confirmed_place_count']==0 else 1,-(x['candidate_lead_count']-x['confirmed_place_count']),x['confirmed_category_count'],x['source_dataset_count'],x['admin_unit_id']))
 for rank,row in enumerate(ordered,1):row['relative_cultural_heritage_evidence_gap_rank']=rank
 digest={'places':places,'admins':admins,'sources':sorted(map(str,source_artifacts))};bid='traditional-cultural-heritage-'+hashlib.sha256(json.dumps(digest,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:20]
 return {'schema':SCHEMA,'bundle_id':bid,'views':deepcopy(VIEWS),'summary':{'source_record_count':len(records),'relevant_record_count':len(places),'confirmed_place_count':sum(x['evidence_tier']=='confirmed_cultural_place_evidence' for x in places),'candidate_lead_count':sum(x['evidence_tier']=='heritage_candidate_leads' for x in places),'excluded_ambiguous_count':sum(x['evidence_tier']=='excluded_ambiguous_records' for x in places),'unrelated_record_count':unrelated,'admin_unit_count':len(admins)},'places':sorted(places,key=lambda x:x['place_id']),'admin_units':admins,'channel_readiness':{k:{'status':v,'value':None if v=='unavailable' else v} for k,v in CHANNELS.items()},'source_artifacts':sorted(map(str,source_artifacts)),'claim_boundary':{'max_claim_level':'cultural_place_inventory_candidate_leads_and_heritage_evidence_readiness','legal_heritage_claim':False,'cultural_value_claim':False,'protection_quality_claim':False,'activation_or_investment_claim':False,'causal_policy_effect_claim':False},'fabricated_value_count':0,'production_blockers':['authoritative_heritage_register_missing','legal_status_and_level_missing','opening_operation_and_public_access_missing','condition_and_restoration_observations_missing','visitor_and_community_activity_missing','longitudinal_intervention_outcomes_missing']}
