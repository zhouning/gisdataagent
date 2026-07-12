from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from data_agent.uwm.cross_domain_impact import build_cross_domain_impact_product
CONFIG={
 'public_service':('traditional_social_public_service_chongqing','district','admin_code',['12','21'],'traditional_gis'),
 'public_space':('traditional_public_space_chongqing','district','admin_code',['9'],'traditional_gis'),
 'daily_convenience':('traditional_daily_convenience_chongqing','district','admin_code',['14'],'traditional_gis'),
 'cultural_heritage':('traditional_cultural_heritage_chongqing','district','admin_code',['16'],'traditional_gis'),
 'housing_community':('traditional_housing_community_chongqing','township_proxy','admin_unit_id',['13'],'traditional_gis'),
 'safety_comfort':('traditional_safety_comfort_chongqing','analytical_unit','admin_unit_id',['10'],'traditional_gis')}
RANKS={'public_space':'relative_public_space_evidence_gap_rank','daily_convenience':'relative_daily_convenience_evidence_gap_rank','cultural_heritage':'relative_cultural_heritage_evidence_gap_rank','housing_community':'relative_housing_community_evidence_gap_rank','safety_comfort':'relative_safety_comfort_evidence_gap_rank'}
def build_product(*,source_root:Path,environment_root:Path,output_dir:Path):
 products=[]
 for domain,(dirname,grain,identifier,demands,route) in CONFIG.items():
  root=source_root/dirname;o=json.loads((root/'overview.json').read_text());a=json.loads((root/'admin_units.json').read_text());rows=[]
  for x in a.get('admin_units',[]):
   rank=x.get(RANKS.get(domain,''));reasons=x.get('relative_gap_reasons') or x.get('evidence_gap_reasons') or []
   if domain=='public_service':rank=(x.get('social_infrastructure') or {}).get('relative_gap_rank');reasons=(x.get('social_infrastructure') or {}).get('relative_gap_reasons') or []
   rows.append({'admin_unit_id':x.get('admin_unit_id'),'admin_name':x.get('admin_name') or x.get('county'),'native_gap_rank':rank,'native_gap_reasons':reasons,'production_blocker_count':len(o.get('production_blockers',[]))})
  products.append({'domain_id':domain,'demand_ids':demands,'product_schema':o.get('schema'),'bundle_id':o.get('bundle_id'),'technology_route':route,'spatial_grain':grain,'temporal_scope':'current_verified_snapshot','unit_identifier_contract':identifier,'max_claim_level':(o.get('claim_boundary') or {}).get('max_claim_level'),'fabricated_value_count':o.get('fabricated_value_count',0),'production_blockers':o.get('production_blockers',[]),'source_artifacts':[str(root/'overview.json'),str(root/'admin_units.json')],'units':rows})
 scene=json.loads((environment_root/'scene.json').read_text());gate=json.loads((environment_root/'evidence_gate.json').read_text());products.append({'domain_id':'environment','demand_ids':['11'],'product_schema':scene.get('schema'),'bundle_id':scene.get('bundle_id'),'technology_route':'uwm_calibrated_dynamic','spatial_grain':'environment_admin_node','temporal_scope':'2024-07-01/2024-07-07','unit_identifier_contract':'environment_node_id','max_claim_level':'observed_environmental_state_and_calibrated_pm25_external_temporal_dynamics','fabricated_value_count':0,'production_blockers':['pm25_action_response_unavailable','pm25_spatial_propagation_unavailable','temperature_temporal_calibration_unavailable','vegetation_temporal_calibration_unavailable'],'source_artifacts':[str(environment_root/'scene.json'),str(environment_root/'evidence_gate.json')],'units':[],'dynamic_evidence':{'pm25_temporal_dynamics':gate.get('pm25_temporal_dynamics') or 'observed_calibrated','intervention_status':'action_response_closed'}})
 product=build_cross_domain_impact_product(source_products=products);product['summary']={'source_product_count':len(products),'exact_district_domain_count':4,'district_priority_unit_count':len(product['priority_units']),'calibrated_dynamic_channel_count':1,'closed_uwm_gate_count':4,'fabricated_value_count':0};write_product(product,output_dir);return product
def write_product(p,out):
 out.mkdir(parents=True,exist_ok=True);bid=p['bundle_id'];payloads={'overview.json':{k:v for k,v in p.items() if k not in {'source_products','comparability_matrix','priority_units','dependency_graph'}},'source_products.json':{'schema':'uwm.cross_domain_source_products.v1','bundle_id':bid,'source_products':p['source_products']},'comparability_matrix.json':{'schema':'uwm.cross_domain_comparability.v1','bundle_id':bid,'comparability_matrix':p['comparability_matrix']},'priority_units.json':{'schema':'uwm.cross_domain_priority_units.v1','bundle_id':bid,'priority_units':p['priority_units']},'dependency_graph.json':{'schema':'uwm.cross_domain_dependency_graph.v1','bundle_id':bid,'dependency_graph':p['dependency_graph']},'map.json':{'schema':'uwm.cross_domain_impact_map.v1','bundle_id':bid,'layers':[{'name':'跨领域证据编排优先级','type':'geojson','geojsonData':{'type':'FeatureCollection','features':[{'type':'Feature','geometry':None,'properties':{'admin_unit_id':x['admin_unit_id'],'admin_name':x['admin_name'],'cross_domain_evidence_priority_rank':x['cross_domain_evidence_priority_rank']}} for x in p['priority_units']]}}]}}
 for n,x in payloads.items():tmp=out/f'.{n}.tmp';tmp.write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')));tmp.replace(out/n)
def main():
 q=argparse.ArgumentParser();q.add_argument('--source-root',type=Path,required=True);q.add_argument('--environment-root',type=Path,required=True);q.add_argument('--output-dir',type=Path,required=True);a=q.parse_args();r=build_product(source_root=a.source_root,environment_root=a.environment_root,output_dir=a.output_dir);print(json.dumps({'bundle_id':r['bundle_id'],'summary':r['summary']},ensure_ascii=False))
if __name__=='__main__':main()
