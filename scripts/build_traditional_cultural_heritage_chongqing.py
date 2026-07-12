from __future__ import annotations
import argparse,json,sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from data_agent.uwm.traditional_cultural_heritage import build_cultural_heritage_product
def build_product(*,facility_product_path:Path,output_dir:Path):
 source=json.loads(facility_product_path.read_text())
 if source.get('schema')!='uwm.traditional_livability.facility_product.v1':raise ValueError('facility_product_schema_invalid')
 names={str(x['admin_code']):x.get('admin_name') for x in source.get('population_units',[]) if x.get('admin_code')};name_to_code={v:k for k,v in names.items() if v};admins=[{'admin_unit_id':k,'admin_name':v} for k,v in names.items() if k!='500000'];records=[];unmapped=0
 for x in source.get('facilities',[]):
  raw=x.get('admin_code');code=str(raw) if raw is not None else ''
  if code not in names:code=name_to_code.get(raw,'')
  if code not in names or code=='500000':code=None;unmapped+=1
  records.append({'place_id':f"{x.get('source_dataset_id')}:{x.get('source_record_id')}",'name':x.get('name'),'raw_primary_class':x.get('raw_primary_class'),'raw_secondary_class':x.get('raw_secondary_class'),'raw_tertiary_class':x.get('raw_tertiary_class'),'longitude':x.get('longitude'),'latitude':x.get('latitude'),'admin_unit_id':code,'source_dataset':x.get('source_dataset_id'),'source_record_id':x.get('source_record_id')})
 product=build_cultural_heritage_product(records=records,admin_units=admins,source_artifacts=[str(facility_product_path)]);confirmed=[x for x in product['places'] if x['evidence_tier']=='confirmed_cultural_place_evidence'];product['summary'].update({'unmapped_source_admin_count':unmapped,'confirmed_category_counts':dict(sorted(Counter(x['canonical_category'] for x in confirmed).items())),'source_inventory_complete':bool(source.get('source_manifest',{}).get('complete_inventory'))})
 if not product['summary']['source_inventory_complete']:product['production_blockers'].append('facility_inventory_sampling_not_complete')
 write_product(product,output_dir);return product
def write_product(product,out):
 out.mkdir(parents=True,exist_ok=True);bid=product['bundle_id'];payloads={'overview.json':{k:v for k,v in product.items() if k not in {'places','admin_units','channel_readiness'}},'places.json':{'schema':'traditional_livability.cultural_heritage_places.v1','bundle_id':bid,'places':product['places']},'admin_units.json':{'schema':'traditional_livability.cultural_heritage_admin_units.v1','bundle_id':bid,'admin_units':product['admin_units']},'channel_readiness.json':{'schema':'traditional_livability.cultural_heritage_readiness.v1','bundle_id':bid,'channel_readiness':product['channel_readiness']},'map.json':{'schema':'traditional_livability.cultural_heritage_map.v1','bundle_id':bid,'layers':layers(product['places'])}}
 for name,payload in payloads.items():tmp=out/f'.{name}.tmp';tmp.write_text(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')));tmp.replace(out/name)
def layers(rows):
 result=[]
 for tier,label in [('confirmed_cultural_place_evidence','明确文化场所证据'),('heritage_candidate_leads','遗产候选线索'),('excluded_ambiguous_records','歧义排除记录')]:
  fs=[{'type':'Feature','geometry':{'type':'Point','coordinates':[x['longitude'],x['latitude']]},'properties':{'place_id':x['place_id'],'name':x['name'],'canonical_category':x['canonical_category'],'evidence_tier':tier}} for x in rows if x['evidence_tier']==tier and x.get('longitude') is not None and x.get('latitude') is not None]
  result.append({'name':label,'type':'geojson','geojsonData':{'type':'FeatureCollection','features':fs}})
 return result
def main():
 p=argparse.ArgumentParser();p.add_argument('--facility-product',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args();r=build_product(facility_product_path=a.facility_product,output_dir=a.output_dir);print(json.dumps({'bundle_id':r['bundle_id'],'summary':r['summary'],'production_blockers':r['production_blockers']},ensure_ascii=False))
if __name__=='__main__':main()
