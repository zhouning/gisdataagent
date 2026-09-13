from data_agent.uwm.operations_quality import build_operations_quality_product

def test_operations_and_customer_sla_are_separate():
 caps=[{'capability_id':'logging','capability_type':'structured_logging','status':'implemented','evidence_paths':['data_agent/observability.py'],'max_claim_level':'logging_capability'}]
 p=build_operations_quality_product(platform_operations=caps,source_artifacts=['observability.py'])
 assert p['schema']=='uwm.operations_service_quality_readiness.v1'
 assert p['summary']['platform_operation_capability_count']==1
 assert all(x['status']=='unavailable' and x['value'] is None for x in p['customer_channels'].values())
 assert all(v=='closed' for v in p['uwm_gate']['mechanisms'].values())
 assert p['claim_boundary']['internal_threshold_not_customer_contract_sla'] is True
 assert p['fabricated_value_count']==0
 forbidden={'customer_sla_compliance_rate','service_availability_rate','mttr','mtbf','customer_satisfaction_score','ticket_closure_rate','root_cause_distribution','maintenance_cost','failure_recurrence_probability','operations_performance_rank','sla_breach_prediction'}
 assert forbidden.isdisjoint(p)
