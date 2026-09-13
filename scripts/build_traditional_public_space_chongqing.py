from __future__ import annotations
import argparse,json,sys
from collections import Counter
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from data_agent.uwm.traditional_public_space import build_public_space_product

def build_product(*,facility_product_path:Path,output_dir:Path)->dict[str,Any]:
 source=json.loads(facility_product_path.read_text(encoding='utf-8'))
 if source.get('schema')!='uwm.traditional_livability.facility_product.v1':raise ValueError('facility_product_schema_invalid')
 names={str(x['admin_code']):x.get('admin_name') for x in source.get('population_units',[]) if x.get('admin_code')};codes={v:k for k,v in names.items() if v}
 admins=[{'admin_unit_id':k,'county':v} for k,v in names.items() if k!='500000']
 records=[];unmapped_admin=0
 for x in source.get('facilities',[]):
  raw=x.get('admin_code');code=str(raw) if raw is not None else ''
  if code not in names:code=codes.get(raw,'')
  if code not in names or code=='500000':code=None;unmapped_admin+=1
  records.append({'space_id':f"{x.get('source_dataset_id')}:{x.get('source_record_id')}",'name':x.get('name'),'raw_primary_class':x.get('raw_primary_class'),'raw_secondary_class':x.get('raw_secondary_class'),'raw_tertiary_class':x.get('raw_tertiary_class'),'longitude':x.get('longitude'),'latitude':x.get('latitude'),'admin_unit_id':code,'source_dataset':x.get('source_dataset_id'),'source_record_id':x.get('source_record_id')})
 product=build_public_space_product(records=records,admin_units=admins,source_artifacts=[str(facility_product_path)])
 product['summary'].update({'source_facility_count':len(records),'unmapped_source_admin_count':unmapped_admin,'eligible_category_counts':dict(sorted(Counter(x['canonical_space_category'] for x in product['spaces']).items())),'exclusion_reason_counts':dict(sorted(Counter(x['classification_reason'] for x in product['excluded_records']).items()))})
 if not source.get('source_manifest',{}).get('complete_inventory'):product['production_blockers'].append('facility_inventory_sampling_not_complete')
 product['production_blockers']=sorted(set(product['production_blockers']));_write(product,output_dir);return product

def _write(p,out):
 out.mkdir(parents=True,exist_ok=True);bid=p['bundle_id'];payloads={'overview.json':{k:v for k,v in p.items() if k not in {'spaces','excluded_records','admin_units','channel_readiness'}},'spaces.json':{'schema':'traditional_livability.public_spaces.v1','bundle_id':bid,'spaces':p['spaces'],'excluded_records':p['excluded_records']},'admin_units.json':{'schema':'traditional_livability.public_space_admin_units.v1','bundle_id':bid,'admin_units':p['admin_units']},'channel_readiness.json':{'schema':'traditional_livability.public_space_readiness.v1','bundle_id':bid,'channel_readiness':p['channel_readiness']},'map.json':{'schema':'traditional_livability.public_space_map.v1','bundle_id':bid,'layers':_layers(p['spaces'])}}
 for name,data in payloads.items():
  temp=out/f'.{name}.tmp';temp.write_text(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')),encoding='utf-8');temp.replace(out/name)
def _layers(spaces):
 features=[{'type':'Feature','geometry':{'type':'Point','coordinates':[x['longitude'],x['latitude']]},'properties':{'space_id':x['space_id'],'name':x['name'],'canonical_space_category':x['canonical_space_category'],'admin_unit_id':x['admin_unit_id']}} for x in spaces if x.get('longitude') is not None and x.get('latitude') is not None]
 return [{'name':'公共空间证据','type':'geojson','geojsonData':{'type':'FeatureCollection','features':features}}]
def main():
 p=argparse.ArgumentParser();p.add_argument('--facility-product',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args();r=build_product(facility_product_path=a.facility_product,output_dir=a.output_dir);print(json.dumps({'bundle_id':r['bundle_id'],'summary':r['summary'],'production_blockers':r['production_blockers']},ensure_ascii=False))
if __name__=='__main__':main()
