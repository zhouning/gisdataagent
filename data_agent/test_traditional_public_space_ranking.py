from data_agent.uwm.traditional_public_space import build_public_space_product

def record(i,admin,secondary,tertiary=None):return {'space_id':i,'name':i,'raw_primary_class':'x','raw_secondary_class':secondary,'raw_tertiary_class':tertiary,'longitude':106.5,'latitude':29.5,'admin_unit_id':admin,'source_dataset':'poi','source_record_id':i}
def product():
 return build_public_space_product(records=[record('a1','A','公园'),record('a2','A','图书馆'),record('b1','B','图书馆'),record('d1','D','公园')],admin_units=[{'admin_unit_id':x,'county':x} for x in ['D','C','B','A']],source_artifacts=['x'])
def test_ranking_prioritizes_zero_core_then_zero_total_then_diversity_and_count():
 rows={x['admin_unit_id']:x for x in product()['admin_units']}
 assert rows['C']['relative_public_space_evidence_gap_rank']==1
 assert rows['B']['relative_public_space_evidence_gap_rank']==2
 assert rows['D']['relative_public_space_evidence_gap_rank']==3
 assert rows['A']['relative_public_space_evidence_gap_rank']==4
 assert rows['C']['relative_gap_reasons'][0]=='zero_core_open_space'
 assert 'zero_total_eligible_space' in rows['C']['relative_gap_reasons']
 assert rows['B']['authoritative_public_space_shortage'] is None
def test_ties_are_stable_by_admin_identifier():
 p=build_public_space_product(records=[],admin_units=[{'admin_unit_id':'C','county':'C'},{'admin_unit_id':'A','county':'A'},{'admin_unit_id':'B','county':'B'}],source_artifacts=[])
 ordered=sorted(p['admin_units'],key=lambda x:x['relative_public_space_evidence_gap_rank'])
 assert [x['admin_unit_id'] for x in ordered]==['A','B','C']
def test_rank_is_relative_proxy_not_quality_or_investment_score():
 row=product()['admin_units'][0]
 assert row['relative_proxy_not_authoritative_standard'] is True
 assert row['observed_public_space_use'] is False
 assert row['observed_quality'] is False
 assert row['policy_outcome_claim'] is False
 assert 'quality_score' not in row and 'investment_priority_score' not in row
