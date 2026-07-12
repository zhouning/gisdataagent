from data_agent.uwm.traditional_daily_convenience import build_daily_convenience_product

def r(i,a,p,s):return {'place_id':i,'name':i,'raw_primary_class':p,'raw_secondary_class':s,'raw_tertiary_class':None,'admin_unit_id':a,'source_dataset':'poi','source_record_id':i}
def product():return build_daily_convenience_product(records=[r('a1','A','购物服务','便民商店/便利店'),r('a2','A','购物服务','超级市场'),r('a3','A','购物服务','综合市场'),r('a4','A','医疗保健服务','医药保健销售店'),r('b1','B','购物服务','便民商店/便利店')],admin_units=[{'admin_unit_id':x,'county':x} for x in ['C','B','A']],accessibility_rows=[{'admin_unit_id':'A','service_accessibility_score':0.8}],source_artifacts=[])
def test_rank_prioritizes_zero_essential_then_missing_core_categories_and_accessibility():
 rows={x['admin_unit_id']:x for x in product()['admin_units']};assert rows['C']['relative_daily_convenience_evidence_gap_rank']==1;assert rows['B']['relative_daily_convenience_evidence_gap_rank']==2;assert rows['A']['relative_daily_convenience_evidence_gap_rank']==3
 assert 'zero_daily_convenience_evidence' in rows['C']['relative_gap_reasons'];assert 'core_daily_categories_missing' in rows['B']['relative_gap_reasons'];assert 'exact_accessibility_evidence_missing' in rows['B']['relative_gap_reasons']
def test_accessibility_reuse_is_exact_id_only_and_missing_is_null():
 rows={x['admin_unit_id']:x for x in product()['admin_units']};assert rows['A']['service_accessibility_context']['exact_id_match'] is True;assert rows['B']['service_accessibility_context']['service_accessibility_score'] is None
def test_rank_is_not_market_shortage_or_economic_score():
 row=product()['admin_units'][0];assert row['relative_gap_not_authoritative_market_shortage'] is True;assert row['economic_performance_claim'] is False;assert row['investment_priority'] is None
 for forbidden in ('economic_vitality_score','employment_score','market_demand_score','profitability_score'):assert forbidden not in str(product())
def test_ties_stable_by_id():
 p=build_daily_convenience_product(records=[],admin_units=[{'admin_unit_id':'B'},{'admin_unit_id':'A'}],accessibility_rows=[],source_artifacts=[]);assert [x['admin_unit_id'] for x in sorted(p['admin_units'],key=lambda x:x['relative_daily_convenience_evidence_gap_rank'])]==['A','B']
