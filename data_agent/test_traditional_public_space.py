import pytest
from data_agent.uwm.traditional_public_space import DEMAND9_CHANNELS,build_public_space_product

def fixture():
 return {'records':[{'space_id':'p1','name':'甲公园','raw_primary_class':'旅游景点','raw_secondary_class':'公园','raw_tertiary_class':None,'longitude':106.5,'latitude':29.5,'admin_unit_id':'A','source_dataset':'poi','source_record_id':'1'}],'admin_units':[{'admin_unit_id':'A','county':'甲区'},{'admin_unit_id':'B','county':'乙区'}],'source_artifacts':['facility.json']}
def test_channel_registry_covers_complete_requirement():
 assert set(DEMAND9_CHANNELS)=={'public_space_inventory','strict_semantic_classification','administrative_distribution','category_diversity','relative_public_space_evidence_gap','availability_proxy','public_access_status','opening_hours','landscape_quality','street_vitality','attractiveness_actual_use','shade_tree_canopy','shaded_seating','street_furniture','visual_comfort','waterfront_accessibility','universal_accessibility','safety_lighting','authoritative_service_area','authoritative_per_capita_open_space','intervention_effect','future_demand'}
def test_product_contract_and_null_unavailable_fields():
 p=build_public_space_product(**fixture());assert p['schema']=='traditional_livability.public_space_opportunity.v1';assert p['spaces'][0]['canonical_space_category']=='core_open_space'
 for field in ('public_access_status','opening_hours','quality_score','vitality_score','shade_evidence','seating_evidence','waterfront_access_evidence'):assert p['spaces'][0][field] is None
 for r in p['channel_readiness'].values():
  if r['status']=='unavailable':assert r['value'] is None
def test_claim_boundary_prevents_unsupported_claims():
 b=build_public_space_product(**fixture())['claim_boundary'];assert b['max_claim_level']=='observed_inventory_and_relative_public_space_evidence_gap';assert b['authoritative_public_space_shortage_claim'] is False;assert b['observed_quality_claim'] is False;assert b['observed_use_or_vitality_claim'] is False;assert b['causal_intervention_effect_claim'] is False
