from data_agent.uwm.cross_domain_impact import build_cross_domain_impact_product

def source(domain,grain,identifier='admin_code',route='traditional_gis',units=None,temporal='2021'):
 return {'domain_id':domain,'demand_ids':['x'],'product_schema':domain+'.v1','bundle_id':domain+'-bundle','technology_route':route,'spatial_grain':grain,'temporal_scope':temporal,'unit_identifier_contract':identifier,'max_claim_level':domain+'_evidence','fabricated_value_count':0,'production_blockers':[],'source_artifacts':[domain+'.json'],'units':units or []}

def test_registry_and_comparability_contract():
 a=source('public_service','district',units=[{'admin_unit_id':'500101','admin_name':'A','native_gap_rank':2}]);b=source('public_space','district',units=[{'admin_unit_id':'500101','admin_name':'A','native_gap_rank':1}]);c=source('housing','township',identifier='admin_unit_id',units=[{'admin_unit_id':'A|T|1'}]);e=source('environment','scene_time',identifier='scene_id',route='uwm_calibrated_dynamic')
 p=build_cross_domain_impact_product(source_products=[a,b,c,e])
 assert p['schema']=='uwm.cross_domain_impact_evidence.v1'
 assert p['fabricated_value_count']==0
 matrix={(x['left_domain_id'],x['right_domain_id']):x['status'] for x in p['comparability_matrix']}
 assert matrix[('public_service','public_space')]=='exact_comparable'
 assert matrix[('public_service','housing')]=='incompatible'
 assert matrix[('housing','environment')]=='incompatible'
 assert p['dynamic_channels']['environment']['technology_route']=='uwm_calibrated_dynamic'
 assert p['claim_boundary']['cross_domain_priority_not_outcome_severity'] is True

def test_priority_has_no_universal_score():
 a=source('a','district',units=[{'admin_unit_id':'1','admin_name':'甲','native_gap_rank':1,'production_blocker_count':2}]);b=source('b','district',units=[{'admin_unit_id':'1','admin_name':'甲','native_gap_rank':3,'production_blocker_count':1}])
 p=build_cross_domain_impact_product(source_products=[a,b])
 row=p['priority_units'][0]
 assert row['admin_unit_id']=='1' and row['compatible_domain_count']==2
 assert 'overall_livability_score' not in row
 assert 'composite_impact_score' not in row
 assert row['limitations']['rank_not_investment_return'] is True
