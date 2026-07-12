from data_agent.uwm.traditional_cultural_heritage import build_cultural_heritage_product

def rec(pid,name,p,s=None,t=None,admin='500001'):
 return {'place_id':pid,'name':name,'raw_primary_class':p,'raw_secondary_class':s,'raw_tertiary_class':t,'longitude':106.5,'latitude':29.5,'admin_unit_id':admin,'source_dataset':'fixture','source_record_id':pid}

def test_strict_tiers_and_boundaries():
 rows=[rec('m','重庆博物馆','旅游景点','博物馆'),rec('r','慈云寺','旅游景点','寺庙'),rec('c','某古镇遗址','旅游景点','其他'),rec('v','白庙村','地名地址信息','普通地名','村庄级地名'),rec('b','重庆农村商业银行玉清寺分理处','金融保险服务','银行')]
 p=build_cultural_heritage_product(records=rows,admin_units=[{'admin_unit_id':'500001','admin_name':'A'}],source_artifacts=['fixture'])
 assert p['schema']=='traditional_livability.cultural_heritage_place_evidence.v1'
 assert set(p['views'])=={'confirmed_cultural_place_evidence','heritage_candidate_leads','excluded_ambiguous_records','heritage_evidence_readiness'}
 by={x['place_id']:x for x in p['places']}
 assert by['m']['evidence_tier']=='confirmed_cultural_place_evidence' and by['m']['canonical_category']=='museum'
 assert by['r']['canonical_category']=='religious_place'
 assert by['c']['evidence_tier']=='heritage_candidate_leads' and by['c']['legal_heritage_status'] is None
 assert by['v']['evidence_tier']=='excluded_ambiguous_records'
 assert by['b']['evidence_tier']=='excluded_ambiguous_records'
 assert p['fabricated_value_count']==0
 assert p['channel_readiness']['legal_heritage_designation']['status']=='unavailable'
 assert p['channel_readiness']['legal_heritage_designation']['value'] is None
 forbidden={'legal_heritage_level','cultural_value_score','authenticity_score','integrity_score','protection_quality_score','visitor_attractiveness_score','community_identity_score','activation_potential_score','investment_priority_score','policy_effect_score'}
 assert all(forbidden.isdisjoint(x) for x in p['places'])

def test_admin_ranking_is_evidence_readiness_only():
 rows=[rec('m','博物馆','旅游景点','博物馆','',admin='A'),rec('c','古镇遗址','旅游景点','其他','',admin='B')]
 p=build_cultural_heritage_product(records=rows,admin_units=[{'admin_unit_id':'A','admin_name':'甲'},{'admin_unit_id':'B','admin_name':'乙'}],source_artifacts=[])
 by={x['admin_unit_id']:x for x in p['admin_units']}
 assert by['B']['relative_cultural_heritage_evidence_gap_rank']<by['A']['relative_cultural_heritage_evidence_gap_rank']
 assert 'cultural_value_score' not in by['B']
