from data_agent.uwm.digital_readiness import build_digital_readiness_product

def test_platform_and_infrastructure_are_separate():
 caps=[{'capability_id':'p1','capability_type':'verified_product','status':'verified','product_schema':'x.v1','bundle_id':'b1','api_prefix':'/api/x','evidence_artifacts':['report.md','overview.json'],'verification_status':'independently_verified','technology_route':'traditional_gis','max_claim_level':'inventory','production_blockers':[],'source_trace':['overview.json']}]
 p=build_digital_readiness_product(platform_capabilities=caps,source_artifacts=['ledger.json'])
 assert p['schema']=='uwm.digital_asset_smart_district_readiness.v1'
 assert p['summary']['verified_platform_capability_count']==1
 assert all(x['status']=='unavailable' and x['value'] is None for x in p['infrastructure_channels'].values())
 assert all(v=='closed' for v in p['uwm_gate']['mechanisms'].values())
 assert p['fabricated_value_count']==0
 forbidden={'smart_city_score','digital_maturity_score','iot_coverage_rate','camera_coverage_rate','wifi_coverage_rate','five_g_coverage_rate','device_online_rate','digital_service_usage_rate','smart_district_rank','digital_investment_return','smart_policy_effect'}
 assert forbidden.isdisjoint(p)
 assert p['claim_boundary']['platform_capability_not_district_infrastructure_coverage'] is True
