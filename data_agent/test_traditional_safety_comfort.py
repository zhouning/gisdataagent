import pytest
from data_agent.uwm.traditional_safety_comfort import CHANNELS,JOIN_STATUSES,build_safety_comfort_product

def fixture():return {'admin_units':[{'admin_unit_id':'A','county':'甲','township':'镇甲'}],'mobility_rows':[{'admin_unit_id':'A','road_segment_count':10,'service_accessibility_score':0.4}],'meteorology_rows':[{'admin_unit_id':'A','temperature_2m_mean_c':28.0,'wind_speed_10m_ms':1.2}],'air_quality_rows':[{'admin_unit_id':'A','pm25_ug_m3':35.0}],'public_safety_facilities':[],'evidence_sources':[{'source_id':'mobility','source_spatial_unit':'township','source_spatial_unit_count':1,'source_time_range':'2021','join_key':'admin_unit_id'}]}
def test_complete_channel_and_join_contracts():
 assert JOIN_STATUSES=={'exact_supported','aggregate_supported','reference_only','incompatible'}
 assert set(CHANNELS)=={'mobility_context','meteorology_context','air_quality_context','public_safety_facility_context','source_coverage_audit','spatial_grain_compatibility','field_collection_priority','relative_evidence_gap','traffic_crashes_conflicts','pedestrian_incidents','crime_security_incidents','perceived_safety_surveys','lighting_illuminance','safe_crossings','emergency_routes_response_times','natural_surveillance','shaded_corridors','universal_accessibility_assets','observed_thermal_comfort','utci_wbgt_pet','safe_routes','authoritative_intervention_priority','causal_intervention_effect'}
def test_product_has_context_not_outcome_flags_and_no_forbidden_scores():
 p=build_safety_comfort_product(**fixture());r=p['admin_units'][0]
 assert p['schema']=='traditional_livability.safety_comfort_evidence.v1'
 assert r['mobility_context']['network_context_not_road_safety'] is True
 assert r['meteorology_context']['temperature_context_not_thermal_comfort'] is True
 assert r['air_quality_context']['air_quality_context_not_personal_safety'] is True
 text=str(p)
 for forbidden in ('safety_score','crime_score','pedestrian_risk_score','thermal_comfort_score','safe_route_score'):assert forbidden not in text
def test_unavailable_channels_are_null_and_claims_closed():
 p=build_safety_comfort_product(**fixture())
 for row in p['channel_readiness'].values():
  if row['status']=='unavailable':assert row['value'] is None
 b=p['claim_boundary'];assert b['max_claim_level']=='mobility_environment_context_and_evidence_readiness';assert b['observed_safety_outcome_claim'] is False;assert b['thermal_comfort_claim'] is False;assert b['safe_route_claim'] is False;assert p['fabricated_value_count']==0
