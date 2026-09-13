from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from data_agent.uwm.business_licence import build_business_licence_product
def build_product(*,daily_root:Path,output_dir:Path):
 o=json.loads((daily_root/'overview.json').read_text());p=json.loads((daily_root/'places.json').read_text());a=json.loads((daily_root/'admin_units.json').read_text());rows=[x for x in p['places'] if 'business_activity_evidence' in x['view_membership']];admins=[{'admin_unit_id':x['admin_unit_id'],'admin_name':x.get('county')} for x in a['admin_units']];product=build_business_licence_product(business_places=rows,admin_units=admins,source_artifacts=[str(daily_root/'overview.json'),str(daily_root/'places.json')]);product['summary']['source_demand14_bundle_id']=o['bundle_id'];write(product,output_dir);return product
def write(p,out):
 out.mkdir(parents=True,exist_ok=True);bid=p['bundle_id'];payloads={'overview.json':{k:v for k,v in p.items() if k not in {'business_places','admin_units','licence_channels','data_contracts','uwm_gate'}},'business_places.json':{'schema':'uwm.business_poi_evidence.v1','bundle_id':bid,'business_places':p['business_places']},'admin_units.json':{'schema':'uwm.business_licence_admin_units.v1','bundle_id':bid,'admin_units':p['admin_units']},'licence_channels.json':{'schema':'uwm.business_licence_channels.v1','bundle_id':bid,'licence_channels':p['licence_channels']},'data_contracts.json':{'schema':'uwm.business_licence_contracts.v1','bundle_id':bid,'data_contracts':p['data_contracts']},'uwm_gate.json':{'schema':'uwm.business_lifecycle_gate.v1','bundle_id':bid,'uwm_gate':p['uwm_gate']},'map.json':{'schema':'uwm.business_licence_map.v1','bundle_id':bid,'layers':[{'name':'企业与商业活动POI证据','type':'geojson','geojsonData':{'type':'FeatureCollection','features':[{'type':'Feature','geometry':{'type':'Point','coordinates':[x['longitude'],x['latitude']]},'properties':{'place_id':x['place_id'],'name':x['name'],'canonical_category':x['canonical_category']}} for x in p['business_places'] if x.get('longitude') is not None]}}]}}
 for n,x in payloads.items():tmp=out/f'.{n}.tmp';tmp.write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')));tmp.replace(out/n)
def main():
 q=argparse.ArgumentParser();q.add_argument('--daily-root',type=Path,required=True);q.add_argument('--output-dir',type=Path,required=True);a=q.parse_args();r=build_product(daily_root=a.daily_root,output_dir=a.output_dir);print(json.dumps({'bundle_id':r['bundle_id'],'summary':r['summary']},ensure_ascii=False))
if __name__=='__main__':main()
