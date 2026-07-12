from __future__ import annotations
from hashlib import sha256
import json
from typing import Any,Mapping,Sequence
SCHEMA='traditional_livability.safety_comfort_evidence.v1'
JOIN_STATUSES={'exact_supported','aggregate_supported','reference_only','incompatible'}
CHANNELS={'mobility_context':'implemented','meteorology_context':'implemented','air_quality_context':'implemented','public_safety_facility_context':'implemented','source_coverage_audit':'implemented','spatial_grain_compatibility':'implemented','field_collection_priority':'implemented','relative_evidence_gap':'proxy_only','traffic_crashes_conflicts':'unavailable','pedestrian_incidents':'unavailable','crime_security_incidents':'unavailable','perceived_safety_surveys':'unavailable','lighting_illuminance':'unavailable','safe_crossings':'unavailable','emergency_routes_response_times':'unavailable','natural_surveillance':'unavailable','shaded_corridors':'unavailable','universal_accessibility_assets':'unavailable','observed_thermal_comfort':'unavailable','utci_wbgt_pet':'unavailable','safe_routes':'unavailable','authoritative_intervention_priority':'unavailable','causal_intervention_effect':'unavailable'}
def decide_join_status(*,source_unit:str,target_unit:str,source_join_key:str,target_join_key:str,crosswalk_available:bool)->str:
 if source_join_key in {'centroid','geometry','row_order'} or target_join_key in {'centroid','geometry','row_order'}:return 'incompatible'
 if source_unit==target_unit and source_join_key==target_join_key and source_join_key not in {'name','admin_name',''}:return 'exact_supported'
 if source_unit!=target_unit and crosswalk_available and source_join_key not in {'name','admin_name',''} and target_join_key not in {'name','admin_name',''}:return 'aggregate_supported'
 return 'reference_only'
def build_safety_comfort_product(*,admin_units:Sequence[Mapping[str,Any]],mobility_rows:Sequence[Mapping[str,Any]],meteorology_rows:Sequence[Mapping[str,Any]],air_quality_rows:Sequence[Mapping[str,Any]],public_safety_facilities:Sequence[Mapping[str,Any]],evidence_sources:Sequence[Mapping[str,Any]])->dict[str,Any]:
 mobility=_index(mobility_rows);met=_index(meteorology_rows);air=_index(air_quality_rows);facilities=list(public_safety_facilities);rows=[]
 for source in sorted(admin_units,key=lambda x:str(x.get('admin_unit_id'))):
  aid=str(source.get('admin_unit_id') or '').strip()
  if not aid:raise ValueError('admin_unit_id_missing')
  m=mobility.get(aid);w=met.get(aid);a=air.get(aid)
  reasons=[]
  if m is None:reasons.append('mobility_context_missing')
  if w is None:reasons.append('meteorology_context_missing')
  if a is None:reasons.append('air_quality_context_missing')
  rows.append({'admin_unit_id':aid,'county':source.get('county'),'township':source.get('township'),'mobility_context':_mobility(m),'meteorology_context':_met(w),'air_quality_context':_air(a),'public_safety_facility_context':{'observed_facility_count':sum(str(x.get('admin_unit_id') or '')==aid for x in facilities),'emergency_coverage_claim':False,'response_time_claim':False},'evidence_coverage':{'mobility_present':m is not None,'meteorology_present':w is not None,'air_quality_present':a is not None},'relative_safety_comfort_evidence_gap_rank':None,'evidence_gap_reasons':reasons,'evidence_gap_not_danger_level':True,'engineering_investment_priority':None,'field_collection_priorities':_collection_priorities(),'field_collection_not_intervention_plan':True,'source_trace':[],'limitations':['evidence_context_not_safety_or_comfort_outcome']})
 _rank_rows(rows)
 normalized_sources=[_source_contract(x) for x in evidence_sources]
 digest={'schema':SCHEMA,'admin_units':rows,'evidence_sources':normalized_sources};bundle='traditional-safety-comfort-'+sha256(json.dumps(digest,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:20]
 return {'schema':SCHEMA,'bundle_id':bundle,'summary':{'admin_unit_count':len(rows),'public_safety_facility_count':len(facilities)},'admin_units':rows,'channel_readiness':{k:{'status':v,'value':None,'proxy_not_observed_outcome':v=='proxy_only'} for k,v in CHANNELS.items()},'evidence_sources':normalized_sources,'public_safety_facilities':[dict(x) for x in facilities],'claim_boundary':{'max_claim_level':'mobility_environment_context_and_evidence_readiness','observed_safety_outcome_claim':False,'observed_crime_or_security_claim':False,'thermal_comfort_claim':False,'safe_route_claim':False,'universal_accessibility_compliance_claim':False,'causal_intervention_effect_claim':False},'fabricated_value_count':0,'production_blockers':['crash_conflict_observations_missing','crime_security_observations_missing','lighting_crossing_data_missing','shade_corridor_data_missing','universal_accessibility_assets_missing','observed_thermal_comfort_missing','emergency_response_time_missing','intervention_effect_evidence_missing']}
def _source_contract(source):
 row=dict(source);status=decide_join_status(source_unit=str(row.get('source_spatial_unit') or ''),target_unit=str(row.get('target_spatial_unit') or row.get('source_spatial_unit') or ''),source_join_key=str(row.get('join_key') or ''),target_join_key=str(row.get('target_join_key') or row.get('join_key') or ''),crosswalk_available=bool(row.get('crosswalk_available')));row['join_status']=status
 if status=='incompatible':row['join_reason']='centroid_join_forbidden' if 'centroid' in {row.get('join_key'),row.get('target_join_key')} else 'spatial_grain_incompatible'
 elif status=='reference_only':row['join_reason']='explicit_crosswalk_or_common_identifier_missing'
 elif status=='aggregate_supported':row['join_reason']='explicit_parent_child_crosswalk'
 else:row['join_reason']='explicit_common_identifier'
 return row
def _rank_rows(rows):
 ordered=sorted(rows,key=lambda x:(-len(x['evidence_gap_reasons']),0 if not x['evidence_coverage']['mobility_present'] else 1,0 if not x['evidence_coverage']['meteorology_present'] else 1,0 if not x['evidence_coverage']['air_quality_present'] else 1,x['admin_unit_id']))
 for rank,row in enumerate(ordered,1):row['relative_safety_comfort_evidence_gap_rank']=rank
def _collection_priorities():return ['collect_crash_and_near_miss_records','collect_lighting_and_illuminance','collect_crossing_inventory','collect_shade_and_canopy_paths','collect_accessibility_assets','collect_calibrated_thermal_comfort_measurements']
def _index(rows):return {str(x.get('admin_unit_id')):dict(x) for x in rows if x.get('admin_unit_id') is not None}
def _mobility(x):return {'available':x is not None,'road_segment_count':x.get('road_segment_count') if x else None,'service_accessibility_score':x.get('service_accessibility_score') if x else None,'network_context_not_road_safety':True,'observed_crash_risk':False,'observed_pedestrian_risk':False,'safe_route_claim':False}
def _met(x):return {'available':x is not None,'temperature_2m_mean_c':x.get('temperature_2m_mean_c') if x else None,'wind_speed_10m_ms':x.get('wind_speed_10m_ms') if x else None,'temperature_context_not_thermal_comfort':True,'thermal_comfort_index_calculated':False,'human_heat_stress_claim':False,'shade_effect_claim':False}
def _air(x):return {'available':x is not None,'pm25_ug_m3':x.get('pm25_ug_m3') if x else None,'air_quality_context_not_personal_safety':True,'causal_health_effect_claim':False,'safety_intervention_effect_claim':False}
