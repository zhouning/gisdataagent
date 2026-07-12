import pytest
from data_agent.uwm.dependency_roadmap import build_dependency_roadmap, validate_task_graph

def demand24():
 return {'bundle_id':'d24','fabricated_value_count':0,'source_products':[{'domain_id':'public_space','bundle_id':'p','fabricated_value_count':0,'max_claim_level':'inventory','source_artifacts':['p.json']},{'domain_id':'environment','bundle_id':'e','fabricated_value_count':0,'technology_route':'uwm_calibrated_dynamic','max_claim_level':'observed_and_temporal','source_artifacts':['e.json']}],'dynamic_channels':{'environment':{'technology_route':'uwm_calibrated_dynamic'},'housing':{'technology_route':'uwm_closed_gate'},'culture':{'technology_route':'uwm_closed_gate'},'economy':{'technology_route':'uwm_closed_gate'},'resilience':{'technology_route':'uwm_closed_gate'}},'dependency_graph':{'housing':['housing_stock_state','household_transitions'],'culture':['asset_condition'],'economy':['licences'],'resilience':['hazards','recovery'],'investment':['costs','benefits']}}

def test_task_contract_status_and_boundaries():
 p=build_dependency_roadmap(demand24=demand24())
 assert p['schema']=='uwm.dependency_aware_implementation_roadmap.v1'
 assert p['fabricated_value_count']==0
 statuses={x['status'] for x in p['tasks']};assert statuses<={'blocked','ready','in_progress','verification_required','verified','deferred'}
 phase0=[x for x in p['tasks'] if x['phase']=='phase_0_operate_verified_capabilities'];assert phase0 and all(x['status']=='verified' for x in phase0)
 kernels=[x for x in p['tasks'] if x['task_type']=='kernel_calibration'];assert kernels and all(x['status']=='blocked' for x in kernels)
 assert all(x['capital_budget'] is None and x['implementation_duration'] is None and x['responsible_agency'] is None for x in p['tasks'])
 assert p['claim_boundary']['roadmap_not_approved_program'] is True

def test_graph_validation_rejects_cycles():
 with pytest.raises(ValueError,match='cycle'):
  validate_task_graph([{'task_id':'a','prerequisite_task_ids':['b']},{'task_id':'b','prerequisite_task_ids':['a']}])
