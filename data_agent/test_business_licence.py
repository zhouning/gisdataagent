from data_agent.uwm.business_licence import build_business_licence_product

def test_poi_is_not_licence_or_operation():
 rows=[{'place_id':'p1','name':'某公司','canonical_category':'company_poi','longitude':1,'latitude':2,'admin_unit_id':'500101','source_dataset':'x','source_record_id':'1','classification_reason':'allow','source_trace':{}}]
 p=build_business_licence_product(business_places=rows,admin_units=[{'admin_unit_id':'500101','admin_name':'A'}],source_artifacts=['x'])
 assert p['schema']=='uwm.business_licence_activity_readiness.v1'
 x=p['business_places'][0]
 assert x['legal_entity_id'] is None and x['licence_status'] is None and x['operating_status'] is None
 assert all(v['status']=='unavailable' and v['value'] is None for v in p['licence_channels'].values())
 assert all(v=='closed' for v in p['uwm_gate']['mechanisms'].values())
 assert p['claim_boundary']['poi_presence_not_valid_business_licence'] is True
 forbidden={'valid_licence_business_count','unlicensed_business_count','business_opening_rate','business_exit_rate','business_survival_rate','employment_count','revenue','turnover','tax_contribution','economic_contribution','business_health_score','investment_attractiveness_score','investment_priority','policy_effect'}
 assert forbidden.isdisjoint(p) and forbidden.isdisjoint(x)
