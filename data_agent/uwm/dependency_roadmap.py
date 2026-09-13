from __future__ import annotations
import hashlib,json
from copy import deepcopy
PHASES=('phase_0_operate_verified_capabilities','phase_1_data_and_crosswalk_foundation','phase_2_kernel_calibration','phase_3_independent_verification','phase_4_decision_product_release')
DOMAINS={'housing':['housing_state_inventory','household_transition_observations','housing_intervention_registry'],'culture':['authoritative_heritage_register','cultural_asset_condition_timeseries','cultural_activity_and_intervention_registry'],'economy':['authoritative_licence_lifecycle','employment_transaction_or_revenue_evidence','economic_intervention_registry'],'resilience':['hazard_exposure_observations','response_capacity_inventory','propagation_and_recovery_timeseries'],'environment':['environment_intervention_response_evidence','environment_spatial_propagation_evidence','temperature_vegetation_temporal_calibration']}
def validate_task_graph(tasks):
 ids={x['task_id'] for x in tasks}
 if len(ids)!=len(tasks):raise ValueError('duplicate_task_id')
 for x in tasks:
  for p in x.get('prerequisite_task_ids',[]):
   if p not in ids:raise ValueError('missing_task_reference')
   if p==x['task_id']:raise ValueError('self_dependency')
 graph={x['task_id']:x.get('prerequisite_task_ids',[]) for x in tasks};visiting=set();done=set()
 def visit(n):
  if n in visiting:raise ValueError('dependency_cycle')
  if n in done:return
  visiting.add(n)
  for p in graph[n]:visit(p)
  visiting.remove(n);done.add(n)
 for n in graph:visit(n)
 return True
def _task(tid,domain,phase,kind,prereqs,status,source_ids=()):
 return {'task_id':tid,'domain':domain,'phase':phase,'task_type':kind,'title':tid.replace('_',' '),'status':status,'priority_rank':None,'prerequisite_task_ids':list(prereqs),'blocking_evidence':[] if status in {'ready','verified'} else ['verified_prerequisites_missing'],'source_bundle_ids':list(source_ids),'completion_evidence_requirements':['immutable_source_artifact','explicit_schema_and_scope','fabricated_value_count_zero'],'verification_gate':'independent_verification_required' if phase in PHASES[2:] else 'source_evidence_verification','allowed_next_claim':None,'owner_role':None,'spatial_scope':None,'temporal_scope':None,'capital_budget':None,'operating_budget':None,'implementation_duration':None,'start_date':None,'completion_date':None,'responsible_agency':None,'expected_benefit':None,'investment_return':None,'policy_effect':None,'limitations':{'task_priority_not_need_or_investment_priority':True,'roadmap_task_not_approved_project':True}}
def build_dependency_roadmap(*,demand24):
 if demand24.get('fabricated_value_count')!=0:raise ValueError('demand24_fabricated_values')
 source_ids=[x['bundle_id'] for x in demand24.get('source_products',[]) if x.get('bundle_id')]
 tasks=[]
 for x in demand24.get('source_products',[]):tasks.append(_task('operate_'+x['domain_id'],x['domain_id'],PHASES[0],'operate_verified_capability',[],'verified',[x['bundle_id']]))
 shared=['authoritative_spatial_crosswalk','longitudinal_intervention_registry','held_out_evaluation_protocol','source_bundle_lineage_monitoring','investment_evidence_contract']
 for tid in shared:tasks.append(_task(tid,'shared',PHASES[1],'shared_foundation',[],'ready',source_ids))
 chains={}
 for domain,foundations in DOMAINS.items():
  ids=[]
  for tid in foundations:tasks.append(_task(tid,domain,PHASES[1],'data_foundation',[],'ready',source_ids));ids.append(tid)
  kernel=domain+'_kernel_calibration';verify=domain+'_kernel_independent_verification';release=domain+'_dynamic_decision_release'
  tasks.append(_task(kernel,domain,PHASES[2],'kernel_calibration',ids+['authoritative_spatial_crosswalk','longitudinal_intervention_registry','held_out_evaluation_protocol'],'blocked',source_ids));tasks.append(_task(verify,domain,PHASES[3],'independent_verification',[kernel],'blocked',source_ids));tasks.append(_task(release,domain,PHASES[4],'decision_product_release',[verify,'investment_evidence_contract'],'blocked',source_ids));chains[domain]=ids+[kernel,verify,release]
 validate_task_graph(tasks)
 children={x['task_id']:set() for x in tasks}
 for x in tasks:
  for p in x['prerequisite_task_ids']:children[p].add(x['task_id'])
 def descendants(tid):
  seen=set();stack=list(children[tid])
  while stack:
   n=stack.pop()
   if n in seen:continue
   seen.add(n);stack.extend(children[n])
  return len(seen)
 ordered=sorted(tasks,key=lambda x:(-descendants(x['task_id']),PHASES.index(x['phase']),x['task_id']))
 for rank,x in enumerate(ordered,1):x['priority_rank']=rank
 digest={'input':demand24.get('bundle_id'),'tasks':tasks};bid='dependency-roadmap-'+hashlib.sha256(json.dumps(digest,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:20]
 return {'schema':'uwm.dependency_aware_implementation_roadmap.v1','bundle_id':bid,'input_bundle_id':demand24.get('bundle_id'),'summary':{'task_count':len(tasks),'verified_task_count':sum(x['status']=='verified' for x in tasks),'ready_task_count':sum(x['status']=='ready' for x in tasks),'blocked_task_count':sum(x['status']=='blocked' for x in tasks),'kernel_calibration_task_count':sum(x['task_type']=='kernel_calibration' for x in tasks)},'tasks':sorted(tasks,key=lambda x:x['task_id']),'dependency_graph':{x['task_id']:x['prerequisite_task_ids'] for x in tasks},'domain_chains':chains,'gates':{'status_machine':['blocked','ready','in_progress','verification_required','verified','deferred'],'automatic_in_progress':False,'language_model_status_promotion':False,'phase4_requires_verified_phase3':True},'source_bundle_ids':source_ids,'claim_boundary':{'max_claim_level':'evidence_dependency_and_verification_gated_implementation_roadmap','roadmap_not_approved_program':True,'task_priority_not_policy_urgency':True,'task_priority_not_investment_return':True,'missing_budget_dates_and_owners_remain_null':True},'fabricated_value_count':0}
