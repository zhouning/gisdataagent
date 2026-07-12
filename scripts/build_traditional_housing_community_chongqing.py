from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from data_agent.uwm.traditional_housing_community import build_housing_community_product

def build_product(*,morphology_path:Path,district_population_path:Path,population_proxy_path:Path,output_dir:Path):
 m=json.loads(morphology_path.read_text());d=json.loads(district_population_path.read_text());p=json.loads(population_proxy_path.read_text())
 if m.get('schema')!='uwm.building_floor_morphology.v1':raise ValueError('morphology_schema_invalid')
 if d.get('schema')!='uwm.chongqing_district_population_stats.v1':raise ValueError('district_population_schema_invalid')
 if p.get('schema')!='uwm.population_downscaling_fitted_proxy.v1':raise ValueError('population_proxy_schema_invalid')
 product=build_housing_community_product(morphology_rows=m.get('admin_morphology_rows',[]),population_proxy_rows=p.get('admin_rows',[]),district_rows=d.get('district_rows',[]),source_artifacts=[str(morphology_path),str(district_population_path),str(population_proxy_path)])
 product['summary'].update({'source_building_record_count':m.get('source_building_record_count'),'parsed_building_geometry_count':m.get('parsed_building_geometry_count'),'assigned_building_count':m.get('assigned_building_count'),'unassigned_building_count':m.get('unassigned_building_count'),'total_floor_count_proxy':m.get('total_floor_count'),'max_floor':m.get('max_floor')})
 write_product(product,output_dir);return product

def write_product(product,out):
 out.mkdir(parents=True,exist_ok=True);bid=product['bundle_id'];payloads={
 'overview.json':{k:v for k,v in product.items() if k not in {'admin_units','channel_readiness','evidence_sources'}},
 'admin_units.json':{'schema':'traditional_livability.housing_community_admin_units.v1','bundle_id':bid,'admin_units':product['admin_units']},
 'channel_readiness.json':{'schema':'traditional_livability.housing_community_readiness.v1','bundle_id':bid,'channel_readiness':product['channel_readiness']},
 'evidence_sources.json':{'schema':'traditional_livability.housing_community_sources.v1','bundle_id':bid,'evidence_sources':product['evidence_sources']},
 'map.json':{'schema':'traditional_livability.housing_community_map.v1','bundle_id':bid,'layers':map_layers(product['admin_units'])}}
 for name,payload in payloads.items():
  temp=out/f'.{name}.tmp';temp.write_text(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')));temp.replace(out/name)

def map_layers(rows):
 def features(view):
  return [{'type':'Feature','geometry':None,'properties':{'admin_unit_id':r['admin_unit_id'],'county':r.get('county'),'township':r.get('township'),'view':view,'relative_evidence_gap_rank':r['relative_housing_community_evidence_gap_rank']}} for r in rows]
 return [{'name':'建筑形态语境','type':'geojson','geojsonData':{'type':'FeatureCollection','features':features('building_morphology_context')}},{'name':'人口语境','type':'geojson','geojsonData':{'type':'FeatureCollection','features':features('population_context')}},{'name':'住房证据就绪度','type':'geojson','geojsonData':{'type':'FeatureCollection','features':features('housing_evidence_readiness')}}]

def main():
 q=argparse.ArgumentParser();q.add_argument('--morphology',type=Path,required=True);q.add_argument('--district-population',type=Path,required=True);q.add_argument('--population-proxy',type=Path,required=True);q.add_argument('--output-dir',type=Path,required=True);a=q.parse_args();r=build_product(morphology_path=a.morphology,district_population_path=a.district_population,population_proxy_path=a.population_proxy,output_dir=a.output_dir);print(json.dumps({'bundle_id':r['bundle_id'],'summary':r['summary'],'production_blockers':r['production_blockers']},ensure_ascii=False))
if __name__=='__main__':main()
