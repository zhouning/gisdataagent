from data_agent.uwm.traditional_daily_convenience import CHANNELS,build_daily_convenience_product

def fixture():return {'records':[{'place_id':'1','name':'便利店','raw_primary_class':'购物服务','raw_secondary_class':'便民商店/便利店','raw_tertiary_class':None,'admin_unit_id':'A','source_dataset':'poi','source_record_id':'1'}],'admin_units':[{'admin_unit_id':'A','county':'甲'}],'accessibility_rows':[{'admin_unit_id':'A','service_accessibility_score':0.5}],'source_artifacts':['x']}
def test_channels_and_two_views():
 assert set(CHANNELS)=={'daily_service_inventory','business_activity_inventory','strict_semantic_classification','administrative_distribution','category_diversity','classification_audit','exact_id_accessibility','relative_evidence_gap','commercial_coverage_proxy','operating_status','opening_hours','business_licence','revenue_sales_transactions','customer_visits','employment_positions','observed_employment_accessibility','service_capacity','household_consumption','business_vacancy','business_survival_churn','home_enterprise_potential','market_demand','entrepreneurship_success','land_value_rent','investment_return','causal_activation_effect','future_commercial_demand'}
 p=build_daily_convenience_product(**fixture());assert p['views']['daily_convenience']['demand_id']=='14';assert p['views']['business_activity_evidence']['demand_id']=='14'
def test_null_economic_fields_and_claim_boundaries():
 p=build_daily_convenience_product(**fixture());r=p['places'][0]
 for field in ('operating_status','opening_hours','employment_count','revenue','transaction_volume','customer_visits','service_capacity'):assert r[field] is None
 assert r['poi_presence_not_observed_business_operation'] is True
 assert r['company_poi_not_employment_count'] is True
 assert p['claim_boundary']['economic_performance_claim'] is False and p['fabricated_value_count']==0
