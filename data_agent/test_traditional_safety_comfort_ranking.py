from data_agent.uwm.traditional_safety_comfort import build_safety_comfort_product

def build():return build_safety_comfort_product(admin_units=[{'admin_unit_id':'C','county':'C'},{'admin_unit_id':'A','county':'A'},{'admin_unit_id':'B','county':'B'}],mobility_rows=[{'admin_unit_id':'A','road_segment_count':1},{'admin_unit_id':'B','road_segment_count':1}],meteorology_rows=[{'admin_unit_id':'A','temperature_2m_mean_c':28}],air_quality_rows=[{'admin_unit_id':'A','pm25_ug_m3':20},{'admin_unit_id':'B','pm25_ug_m3':30}],public_safety_facilities=[],evidence_sources=[])
def test_ranking_measures_missing_evidence_not_danger():
 rows={x['admin_unit_id']:x for x in build()['admin_units']}
 assert rows['C']['relative_safety_comfort_evidence_gap_rank']==1
 assert rows['B']['relative_safety_comfort_evidence_gap_rank']==2
 assert rows['A']['relative_safety_comfort_evidence_gap_rank']==3
 assert 'mobility_context_missing' in rows['C']['evidence_gap_reasons']
 assert 'meteorology_context_missing' in rows['B']['evidence_gap_reasons']
 for row in rows.values():
  assert row['evidence_gap_not_danger_level'] is True
  assert row['engineering_investment_priority'] is None
def test_field_priorities_are_data_collection_not_interventions():
 row=build()['admin_units'][0]
 priorities=row['field_collection_priorities']
 for required in ('collect_crash_and_near_miss_records','collect_lighting_and_illuminance','collect_crossing_inventory','collect_shade_and_canopy_paths','collect_accessibility_assets','collect_calibrated_thermal_comfort_measurements'):assert required in priorities
 assert row['field_collection_not_intervention_plan'] is True
def test_complete_ties_are_stable_by_identifier():
 p=build_safety_comfort_product(admin_units=[{'admin_unit_id':'B'},{'admin_unit_id':'A'}],mobility_rows=[],meteorology_rows=[],air_quality_rows=[],public_safety_facilities=[],evidence_sources=[])
 assert [x['admin_unit_id'] for x in sorted(p['admin_units'],key=lambda x:x['relative_safety_comfort_evidence_gap_rank'])]==['A','B']
