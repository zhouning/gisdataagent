from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from data_agent.uwm.ai_demand_implementation_ledger import build_ai_demand_implementation_ledger
from data_agent.uwm.digital_readiness import build_digital_readiness_product
def build_product(*,repo_root:Path,output_dir:Path):
 ledger=build_ai_demand_implementation_ledger(repo_root=repo_root);caps=[]
 for group in ('livability_scenarios','customer_ai_demands'):
  for x in ledger[group]:
   existing=[a['path'] for a in x.get('evidence_artifact_checks',[]) if a.get('exists')]
   if x.get('implementation_status') not in {'production_verified','implemented_evidence_bounded'} or not existing:continue
   overview=next((p for p in existing if p.endswith('/overview.json')),None);schema=bundle=None
   if overview:
    d=json.loads((repo_root/overview).read_text());schema=d.get('schema');bundle=d.get('bundle_id')
   caps.append({'capability_id':f"{group}:{x['id']}",'capability_type':'verified_product','status':'verified','product_schema':schema,'bundle_id':bundle,'api_prefix':None,'evidence_artifacts':existing,'verification_status':'evidence_artifacts_present','technology_route':'uwm_calibrated_or_gated' if x.get('primary_route')=='uwm_livability' else 'traditional_gis_or_orchestration','max_claim_level':x.get('max_supported_claim'),'production_blockers':x.get('production_blockers',[]),'source_trace':existing})
 p=build_digital_readiness_product(platform_capabilities=caps,source_artifacts=['data_agent/uwm/ai_demand_implementation_ledger.py']);write(p,output_dir);return p
def write(p,out):
 out.mkdir(parents=True,exist_ok=True);bid=p['bundle_id'];payloads={'overview.json':{k:v for k,v in p.items() if k not in {'platform_capabilities','infrastructure_channels','data_contracts','uwm_gate'}},'platform_capabilities.json':{'schema':'uwm.platform_digital_capabilities.v1','bundle_id':bid,'platform_capabilities':p['platform_capabilities']},'infrastructure_channels.json':{'schema':'uwm.smart_infrastructure_channels.v1','bundle_id':bid,'infrastructure_channels':p['infrastructure_channels']},'data_contracts.json':{'schema':'uwm.smart_infrastructure_data_contracts.v1','bundle_id':bid,'data_contracts':p['data_contracts']},'uwm_gate.json':{'schema':'uwm.digital_infrastructure_gate.v1','bundle_id':bid,'uwm_gate':p['uwm_gate']},'map.json':{'schema':'uwm.digital_readiness_map.v1','bundle_id':bid,'layers':[]}}
 for n,x in payloads.items():tmp=out/f'.{n}.tmp';tmp.write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')));tmp.replace(out/n)
def main():
 q=argparse.ArgumentParser();q.add_argument('--repo-root',type=Path,required=True);q.add_argument('--output-dir',type=Path,required=True);a=q.parse_args();r=build_product(repo_root=a.repo_root,output_dir=a.output_dir);print(json.dumps({'bundle_id':r['bundle_id'],'summary':r['summary']},ensure_ascii=False))
if __name__=='__main__':main()
