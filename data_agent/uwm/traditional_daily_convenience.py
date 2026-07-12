from __future__ import annotations
from hashlib import sha256
import json
from typing import Any,Mapping,Sequence
SCHEMA='traditional_livability.daily_convenience_business_evidence.v1'
CHANNELS={'daily_service_inventory':'implemented','business_activity_inventory':'implemented','strict_semantic_classification':'implemented','administrative_distribution':'implemented','category_diversity':'implemented','classification_audit':'implemented','exact_id_accessibility':'implemented','relative_evidence_gap':'proxy_only','commercial_coverage_proxy':'proxy_only','operating_status':'unavailable','opening_hours':'unavailable','business_licence':'unavailable','revenue_sales_transactions':'unavailable','customer_visits':'unavailable','employment_positions':'unavailable','observed_employment_accessibility':'unavailable','service_capacity':'unavailable','household_consumption':'unavailable','business_vacancy':'unavailable','business_survival_churn':'unavailable','home_enterprise_potential':'unavailable','market_demand':'unavailable','entrepreneurship_success':'unavailable','land_value_rent':'unavailable','investment_return':'unavailable','causal_activation_effect':'unavailable','future_commercial_demand':'unavailable'}
DAILY={('购物服务','便民商店/便利店'):'convenience_store',('购物','便利店'):'convenience_store',('购物服务','超级市场'):'supermarket',('购物','超市'):'supermarket',('购物服务','综合市场'):'market',('购物','市场'):'market',('医疗保健服务','医药保健销售店'):'pharmacy',('医疗','药店'):'pharmacy',('餐饮服务','咖啡厅'):'cafe',('餐饮服务','快餐厅'):'fast_food',('美食','小吃快餐店'):'fast_food',('生活服务','邮局'):'postal_service',('生活服务','洗衣店'):'laundry',('生活服务','维修站点'):'repair_service',('生活服务','电讯营业厅'):'telecom_outlet',('金融保险服务','银行'):'bank_branch',('金融','银行'):'bank_branch',('金融保险服务','自动提款机'):'atm_access_point'}
BUSINESS={'公司':'company_poi','厂矿':'industrial_enterprise_poi','工厂':'industrial_enterprise_poi','园区':'business_park_poi','物流公司':'logistics_enterprise_poi'}
def classify_place(record:Mapping[str,Any])->dict[str,Any]:
 primary=str(record.get('raw_primary_class') or '').strip();secondary=str(record.get('raw_secondary_class') or '').strip();category=DAILY.get((primary,secondary))
 if category:return {'classification_decision':'included','classification_reason':'strict_daily_convenience_allow_list','canonical_category':category,'view_membership':['daily_convenience']}
 if primary=='公司企业' and secondary in BUSINESS:return {'classification_decision':'included','classification_reason':'strict_business_activity_allow_list','canonical_category':BUSINESS[secondary],'view_membership':['business_activity_evidence']}
 return {'classification_decision':'excluded_ambiguous','classification_reason':'not_in_strict_allow_list','canonical_category':None,'view_membership':[]}
def build_daily_convenience_product(*,records:Sequence[Mapping[str,Any]],admin_units:Sequence[Mapping[str,Any]],accessibility_rows:Sequence[Mapping[str,Any]],source_artifacts:Sequence[str])->dict[str,Any]:
 places=[];excluded=[];seen=set()
 for source in records:
  pid=str(source.get('place_id') or '').strip()
  if not pid:raise ValueError('place_id_missing')
  if pid in seen:raise ValueError('duplicate_place_id')
  seen.add(pid);dataset=str(source.get('source_dataset') or '').strip();rid=str(source.get('source_record_id') or '').strip()
  if not dataset or not rid:raise ValueError('place_source_trace_missing')
  c=classify_place(source);base={'place_id':pid,'name':source.get('name'),'raw_primary_class':source.get('raw_primary_class'),'raw_secondary_class':source.get('raw_secondary_class'),'raw_tertiary_class':source.get('raw_tertiary_class'),'canonical_category':c['canonical_category'],'view_membership':c['view_membership'],'longitude':source.get('longitude'),'latitude':source.get('latitude'),'admin_unit_id':source.get('admin_unit_id'),'classification_decision':c['classification_decision'],'classification_reason':c['classification_reason'],'source_dataset':dataset,'source_record_id':rid,'source_trace':{'source_dataset':dataset,'source_record_id':rid}}
  if c['view_membership']:places.append({**base,'operating_status':None,'opening_hours':None,'employment_count':None,'revenue':None,'transaction_volume':None,'customer_visits':None,'service_capacity':None,'poi_presence_not_observed_business_operation':True,'company_poi_not_employment_count':True,'economic_performance_claim':False,'limitations':['operation_employment_revenue_demand_not_observed']})
  else:excluded.append(base)
 access={str(x.get('admin_unit_id')):dict(x) for x in accessibility_rows if x.get('admin_unit_id') is not None};admins=[]
 for source in sorted(admin_units,key=lambda x:str(x.get('admin_unit_id'))):
  aid=str(source.get('admin_unit_id') or '').strip();selected=[x for x in places if str(x.get('admin_unit_id') or '')==aid];daily=[x for x in selected if 'daily_convenience' in x['view_membership']];business=[x for x in selected if 'business_activity_evidence' in x['view_membership']];a=access.get(aid)
  counts=_counts(daily);core={'convenience_store','supermarket','market','pharmacy'};reasons=[]
  if not daily:reasons.append('zero_daily_convenience_evidence')
  if not core.issubset(counts):reasons.append('core_daily_categories_missing')
  if a is None:reasons.append('exact_accessibility_evidence_missing')
  admins.append({'admin_unit_id':aid,'county':source.get('county'),'township':source.get('township'),'daily_convenience_counts':counts,'daily_convenience_category_count':len({x['canonical_category'] for x in daily}),'daily_convenience_place_count':len(daily),'business_activity_counts':_counts(business),'business_activity_category_count':len({x['canonical_category'] for x in business}),'business_activity_place_count':len(business),'service_accessibility_context':{'exact_id_match':a is not None,'service_accessibility_score':a.get('service_accessibility_score') if a else None},'relative_daily_convenience_evidence_gap_rank':None,'relative_gap_reasons':reasons,'relative_gap_not_authoritative_market_shortage':True,'economic_performance_claim':False,'investment_priority':None,'classification_review_priority':None,'field_collection_priorities':['verify_operating_status_and_hours','collect_business_licence_and_lifecycle','collect_employment_and_workplace_data','collect_sales_transactions_and_visits','survey_household_daily_service_demand']})
 _rank_admins(admins)
 digest={'schema':SCHEMA,'places':sorted(places,key=lambda x:x['place_id']),'admin_units':admins};bundle='traditional-daily-convenience-'+sha256(json.dumps(digest,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:20]
 return {'schema':SCHEMA,'bundle_id':bundle,'views':{'daily_convenience':{'demand_id':'14'},'business_activity_evidence':{'demand_id':'14'}},'summary':{'eligible_place_count':len(places),'excluded_record_count':len(excluded),'admin_unit_count':len(admins)},'places':sorted(places,key=lambda x:x['place_id']),'excluded_records':sorted(excluded,key=lambda x:x['place_id']),'admin_units':admins,'channel_readiness':{k:{'status':v,'value':None} for k,v in CHANNELS.items()},'source_artifacts':sorted(source_artifacts),'claim_boundary':{'max_claim_level':'daily_service_inventory_accessibility_context_and_business_activity_evidence','authoritative_market_shortage_claim':False,'observed_business_operation_claim':False,'employment_claim':False,'economic_performance_claim':False,'entrepreneurship_opportunity_claim':False,'causal_activation_effect_claim':False},'fabricated_value_count':0,'production_blockers':['business_operation_and_opening_hours_missing','business_licence_missing','employment_data_missing','revenue_transactions_visits_missing','market_demand_missing','entrepreneurship_evidence_missing','causal_activation_effect_missing']}
def _counts(rows):
 result={}
 for x in rows:result[x['canonical_category']]=result.get(x['canonical_category'],0)+1
 return dict(sorted(result.items()))
def _rank_admins(rows):
 core={'convenience_store','supermarket','market','pharmacy'}
 ordered=sorted(rows,key=lambda x:(0 if x['daily_convenience_place_count']==0 else 1,-len(core-set(x['daily_convenience_counts'])),x['daily_convenience_category_count'],x['daily_convenience_place_count'],0 if not x['service_accessibility_context']['exact_id_match'] else 1,x['admin_unit_id']))
 for rank,row in enumerate(ordered,1):row['relative_daily_convenience_evidence_gap_rank']=rank
