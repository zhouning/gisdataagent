from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from data_agent.uwm.dependency_roadmap import build_dependency_roadmap
def build_product(*,impact_root:Path,output_dir:Path):
 o=json.loads((impact_root/'overview.json').read_text());s=json.loads((impact_root/'source_products.json').read_text());d=json.loads((impact_root/'dependency_graph.json').read_text());ids={o.get('bundle_id'),s.get('bundle_id'),d.get('bundle_id')}
 if len(ids)!=1 or None in ids:raise ValueError('demand24_bundle_mismatch')
 source={'bundle_id':o['bundle_id'],'fabricated_value_count':o.get('fabricated_value_count'),'source_products':s['source_products'],'dynamic_channels':o['dynamic_channels'],'dependency_graph':d['dependency_graph']};p=build_dependency_roadmap(demand24=source);write(p,output_dir);return p
def write(p,out):
 out.mkdir(parents=True,exist_ok=True);bid=p['bundle_id'];payloads={'overview.json':{k:v for k,v in p.items() if k not in {'tasks','dependency_graph','domain_chains','gates'}},'tasks.json':{'schema':'uwm.implementation_roadmap_tasks.v1','bundle_id':bid,'tasks':p['tasks']},'dependency_graph.json':{'schema':'uwm.implementation_roadmap_dependencies.v1','bundle_id':bid,'dependency_graph':p['dependency_graph']},'domain_chains.json':{'schema':'uwm.implementation_roadmap_domains.v1','bundle_id':bid,'domain_chains':p['domain_chains']},'gates.json':{'schema':'uwm.implementation_roadmap_gates.v1','bundle_id':bid,'gates':p['gates']},'map.json':{'schema':'uwm.implementation_roadmap_map.v1','bundle_id':bid,'layers':[]}}
 for n,x in payloads.items():tmp=out/f'.{n}.tmp';tmp.write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')));tmp.replace(out/n)
def main():
 q=argparse.ArgumentParser();q.add_argument('--impact-root',type=Path,required=True);q.add_argument('--output-dir',type=Path,required=True);a=q.parse_args();r=build_product(impact_root=a.impact_root,output_dir=a.output_dir);print(json.dumps({'bundle_id':r['bundle_id'],'summary':r['summary']},ensure_ascii=False))
if __name__=='__main__':main()
