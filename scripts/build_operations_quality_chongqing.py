from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from data_agent.uwm.operations_quality import build_operations_quality_product
CAPS=[('structured_logging','structured_logging',['data_agent/observability.py']),('trace_context','trace_context',['data_agent/observability.py']),('pipeline_trace','pipeline_trace',['frontend/src/components/datapanel/ObservabilityTab.tsx']),('api_metrics','api_metrics',['data_agent/observability.py']),('prometheus_metrics','prometheus_metrics',['data_agent/observability.py']),('workflow_status','workflow_status',['data_agent/api/quality_routes.py']),('quality_rule_execution','quality_rule_execution',['data_agent/api/quality_routes.py']),('quality_trends','quality_trends',['data_agent/api/quality_routes.py']),('alert_engine','alert_engine',['data_agent/observability.py']),('database_pool_metrics','database_pool_metrics',['data_agent/observability.py']),('llm_invocation_metrics','llm_invocation_metrics',['data_agent/observability.py']),('agent_run_logs','agent_run_logs',['frontend/src/components/datapanel/AgentRunLogsTab.tsx']),('bundle_availability_checks','bundle_availability_checks',['data_agent/uwm/ai_demand_implementation_ledger.py']),('fail_closed_product_gates','fail_closed_product_gates',['data_agent/uwm/resilience_kernel.py'])]
def build_product(*,repo_root:Path,output_dir:Path):
 caps=[]
 for cid,ctype,paths in CAPS:
  existing=[p for p in paths if (repo_root/p).is_file()]
  if existing:caps.append({'capability_id':cid,'capability_type':ctype,'status':'implemented_capability','evidence_paths':existing,'max_claim_level':'platform_operation_capability_only','limitations':['capability_not_observed_customer_service_result']})
 p=build_operations_quality_product(platform_operations=caps,source_artifacts=[x for c in caps for x in c['evidence_paths']]);write(p,output_dir);return p
def write(p,out):
 out.mkdir(parents=True,exist_ok=True);bid=p['bundle_id'];payloads={'overview.json':{k:v for k,v in p.items() if k not in {'platform_operations','customer_channels','data_contracts','uwm_gate'}},'platform_operations.json':{'schema':'uwm.platform_operations_evidence.v1','bundle_id':bid,'platform_operations':p['platform_operations']},'customer_channels.json':{'schema':'uwm.customer_operations_channels.v1','bundle_id':bid,'customer_channels':p['customer_channels']},'data_contracts.json':{'schema':'uwm.customer_operations_contracts.v1','bundle_id':bid,'data_contracts':p['data_contracts']},'uwm_gate.json':{'schema':'uwm.operations_world_model_gate.v1','bundle_id':bid,'uwm_gate':p['uwm_gate']},'map.json':{'schema':'uwm.operations_quality_map.v1','bundle_id':bid,'layers':[]}}
 for n,x in payloads.items():tmp=out/f'.{n}.tmp';tmp.write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')));tmp.replace(out/n)
def main():
 q=argparse.ArgumentParser();q.add_argument('--repo-root',type=Path,required=True);q.add_argument('--output-dir',type=Path,required=True);a=q.parse_args();r=build_product(repo_root=a.repo_root,output_dir=a.output_dir);print(json.dumps({'bundle_id':r['bundle_id'],'summary':r['summary']},ensure_ascii=False))
if __name__=='__main__':main()
