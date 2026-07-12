import pytest
from data_agent.uwm.resilience_kernel import build_resilience_kernel_product,validate_resilience_graph

def test_fail_closed_kernel_contract():
 nodes=[{'node_id':'n1','admin_unit_id':'1','admin_name':'A','network_context':{'road_node_count':2},'public_service_context':{},'emergency_facility_context':{'fire_station_count':1},'environment_context':{'pm25':20},'source_trace':['x']}]
 edges=[]
 p=build_resilience_kernel_product(nodes=nodes,edges=edges,dependency_chain=['hazard_exposure_observations'],source_artifacts=['x'])
 assert p['schema']=='uwm.resilience_kernel_foundation.v1'
 assert len(p['evidence_gates'])==7
 assert all(p['current_rollout'][k]=='closed' for k in ('disturbance_transition_status','hazard_propagation_status','response_capacity_status','recovery_transition_status','intervention_effect_status','counterfactual_status'))
 assert p['current_rollout']['future_trajectory'] is None
 assert p['fabricated_value_count']==0
 forbidden={'resilience_score','vulnerability_score','hazard_loss','expected_damage','mortality','response_effectiveness','recovery_time','recovery_probability','intervention_benefit','robustness_score'}
 assert forbidden.isdisjoint(p['state'][0]) and forbidden.isdisjoint(p['current_rollout'])

def test_graph_requires_provenance_and_null_parameter():
 good=[{'source_node_id':'a','target_node_id':'b','edge_type':'administrative_adjacency','edge_provenance':'verified_boundary_adjacency','shared_boundary_or_network_basis':'boundary','propagation_parameter':None}]
 assert validate_resilience_graph(good)
 with pytest.raises(ValueError,match='propagation_parameter'):
  validate_resilience_graph([{**good[0],'propagation_parameter':.5}])
 with pytest.raises(ValueError,match='provenance'):
  validate_resilience_graph([{**good[0],'edge_provenance':None}])
