from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from data_agent.uwm.traditional_safety_comfort import build_safety_comfort_product
def build_product(*,mobility_path:Path,environment_path:Path,facility_path:Path,output_dir:Path):
 mobility=json.loads(mobility_path.read_text());environment=json.loads(environment_path.read_text());facility=json.loads(facility_path.read_text())
 if mobility.get('schema')!='traditional_livability.mobility_admin_units.v1':raise ValueError('mobility_schema_invalid')
 rows=mobility.get('admin_units',[]);admins=[{'admin_unit_id':x['admin_unit_id'],'county':x.get('county'),'township':x.get('township')} for x in rows]
 mobility_rows=[{'admin_unit_id':x['admin_unit_id'],'road_segment_count':x.get('road_segment_count'),'service_accessibility_score':x.get('service_accessibility_score')} for x in rows]
 env_rows=environment.get('admin_environment_rows',[]);safety=[x for x in facility.get('facilities',[]) if x.get('canonical_class')=='public_safety.facility']
 product=build_safety_comfort_product(admin_units=admins,mobility_rows=mobility_rows,meteorology_rows=[],air_quality_rows=[],public_safety_facilities=[],evidence_sources=[{'source_id':'mobility','source_spatial_unit':'township','source_spatial_unit_count':len(rows),'source_time_range':None,'join_key':'admin_unit_id','target_spatial_unit':'township','target_join_key':'admin_unit_id','crosswalk_available':False},{'source_id':'environment','source_spatial_unit':'environment_admin_point','source_spatial_unit_count':len(env_rows),'source_time_range':environment.get('time_range'),'join_key':'admin_id','target_spatial_unit':'township','target_join_key':'admin_unit_id','crosswalk_available':False},{'source_id':'public_safety_facility','source_spatial_unit':'point','source_spatial_unit_count':len(safety),'source_time_range':None,'join_key':'admin_code','target_spatial_unit':'township','target_join_key':'admin_unit_id','crosswalk_available':False}])
 product['summary'].update({'mobility_admin_unit_count':len(rows),'environment_reference_row_count':len(env_rows),'observed_public_safety_facility_count':len(safety),'joined_environment_row_count':0,'joined_public_safety_facility_count':0})
 product['production_blockers']=sorted(set(product['production_blockers']+['environment_admin_crosswalk_missing','public_safety_facility_to_township_crosswalk_missing']))
 _write(product,rows,env_rows,safety,output_dir);return product
def _write(p,mobility,environment,safety,out):
 out.mkdir(parents=True,exist_ok=True);bid=p['bundle_id'];payloads={'overview.json':{k:v for k,v in p.items() if k not in {'admin_units','channel_readiness','evidence_sources'}},'admin_units.json':{'schema':'traditional_livability.safety_comfort_admin_units.v1','bundle_id':bid,'admin_units':p['admin_units']},'channel_readiness.json':{'schema':'traditional_livability.safety_comfort_readiness.v1','bundle_id':bid,'channel_readiness':p['channel_readiness']},'evidence_sources.json':{'schema':'traditional_livability.safety_comfort_sources.v1','bundle_id':bid,'evidence_sources':p['evidence_sources']},'map.json':{'schema':'traditional_livability.safety_comfort_map.v1','bundle_id':bid,'layers':_layers(mobility,environment,safety)}}
 for name,d in payloads.items():
  temp=out/f'.{name}.tmp';temp.write_text(json.dumps(d,ensure_ascii=False,sort_keys=True,separators=(',',':')));temp.replace(out/name)
def _layers(mobility,environment,safety):
 def feature(lon,lat,props):return {'type':'Feature','geometry':{'type':'Point','coordinates':[lon,lat]},'properties':props}
 mobility_features=[feature(x['centroid']['longitude'],x['centroid']['latitude'],{'admin_unit_id':x['admin_unit_id'],'layer_meaning':'network_context_not_road_safety'}) for x in mobility if x.get('centroid',{}).get('longitude') is not None]
 environment_features=[feature(x['longitude'],x['latitude'],{'source_admin_id':x.get('admin_id'),'temperature_2m_mean_c':x.get('temperature_2m_mean_c'),'wind_speed_10m_ms':x.get('wind_speed_10m_ms'),'pm25_ug_m3':x.get('cams_pm25_ugm3'),'layer_meaning':'reference_only_environment_context'}) for x in environment if x.get('longitude') is not None]
 safety_features=[feature(x['longitude'],x['latitude'],{'name':x.get('name'),'layer_meaning':'observed_facility_not_emergency_coverage'}) for x in safety if x.get('longitude') is not None]
 return [{'name':'路网上下文','type':'geojson','geojsonData':{'type':'FeatureCollection','features':mobility_features}},{'name':'环境参考上下文','type':'geojson','geojsonData':{'type':'FeatureCollection','features':environment_features}},{'name':'消防设施观察点','type':'geojson','geojsonData':{'type':'FeatureCollection','features':safety_features}}]
def main():
 p=argparse.ArgumentParser();p.add_argument('--mobility',type=Path,required=True);p.add_argument('--environment',type=Path,required=True);p.add_argument('--facility-product',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args();r=build_product(mobility_path=a.mobility,environment_path=a.environment,facility_path=a.facility_product,output_dir=a.output_dir);print(json.dumps({'bundle_id':r['bundle_id'],'summary':r['summary'],'production_blockers':r['production_blockers']},ensure_ascii=False))
if __name__=='__main__':main()
