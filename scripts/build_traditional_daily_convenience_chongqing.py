from __future__ import annotations
import argparse,json,sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from data_agent.uwm.traditional_daily_convenience import build_daily_convenience_product
def build_product(*,facility_path:Path,accessibility_path:Path,output_dir:Path):
 f=json.loads(facility_path.read_text());a=json.loads(accessibility_path.read_text())
 if f.get('schema')!='uwm.traditional_livability.facility_product.v1':raise ValueError('facility_schema_invalid')
 if a.get('schema')!='traditional_livability.mobility_admin_units.v1':raise ValueError('accessibility_schema_invalid')
 names={str(x['admin_code']):x.get('admin_name') for x in f.get('population_units',[]) if x.get('admin_code')};codes={v:k for k,v in names.items() if v};admins=[{'admin_unit_id':k,'county':v,'township':None} for k,v in names.items() if k!='500000'];records=[];unmapped=0
 for x in f.get('facilities',[]):
  raw=x.get('admin_code');code=str(raw) if raw is not None else ''
  if code not in names:code=codes.get(raw,'')
  if code not in names or code=='500000':code=None;unmapped+=1
  records.append({'place_id':f"{x.get('source_dataset_id')}:{x.get('source_record_id')}",'name':x.get('name'),'raw_primary_class':x.get('raw_primary_class'),'raw_secondary_class':x.get('raw_secondary_class'),'raw_tertiary_class':x.get('raw_tertiary_class'),'longitude':x.get('longitude'),'latitude':x.get('latitude'),'admin_unit_id':code,'source_dataset':x.get('source_dataset_id'),'source_record_id':x.get('source_record_id')})
 product=build_daily_convenience_product(records=records,admin_units=admins,accessibility_rows=a.get('admin_units',[]),source_artifacts=[str(facility_path),str(accessibility_path)])
 daily=[x for x in product['places'] if 'daily_convenience' in x['view_membership']];business=[x for x in product['places'] if 'business_activity_evidence' in x['view_membership']]
 product['summary'].update({'source_facility_count':len(records),'daily_convenience_place_count':len(daily),'business_activity_place_count':len(business),'exact_accessibility_match_count':sum(x['service_accessibility_context']['exact_id_match'] for x in product['admin_units']),'unmapped_source_admin_count':unmapped,'daily_category_counts':dict(sorted(Counter(x['canonical_category'] for x in daily).items())),'business_category_counts':dict(sorted(Counter(x['canonical_category'] for x in business).items())),'bank_branch_count':sum(x['canonical_category']=='bank_branch' for x in daily),'atm_access_point_count':sum(x['canonical_category']=='atm_access_point' for x in daily)})
 if not f.get('source_manifest',{}).get('complete_inventory'):product['production_blockers'].append('facility_inventory_sampling_not_complete')
 if product['summary']['exact_accessibility_match_count']==0:product['production_blockers'].append('county_facility_to_township_accessibility_exact_id_missing')
 product['production_blockers']=sorted(set(product['production_blockers']));_write(product,output_dir);return product
def _write(p,out):
 out.mkdir(parents=True,exist_ok=True);bid=p['bundle_id'];payloads={'overview.json':{k:v for k,v in p.items() if k not in {'places','excluded_records','admin_units','channel_readiness'}},'places.json':{'schema':'traditional_livability.daily_convenience_places.v1','bundle_id':bid,'places':p['places'],'excluded_records':p['excluded_records']},'admin_units.json':{'schema':'traditional_livability.daily_convenience_admin_units.v1','bundle_id':bid,'admin_units':p['admin_units']},'channel_readiness.json':{'schema':'traditional_livability.daily_convenience_readiness.v1','bundle_id':bid,'channel_readiness':p['channel_readiness']},'map.json':{'schema':'traditional_livability.daily_convenience_map.v1','bundle_id':bid,'layers':_layers(p['places'])}}
 for name,d in payloads.items():temp=out/f'.{name}.tmp';temp.write_text(json.dumps(d,ensure_ascii=False,sort_keys=True,separators=(',',':')));temp.replace(out/name)
def _layers(rows):
 def layer(view,name):
  features=[{'type':'Feature','geometry':{'type':'Point','coordinates':[x['longitude'],x['latitude']]},'properties':{'place_id':x['place_id'],'name':x['name'],'canonical_category':x['canonical_category'],'view':view}} for x in rows if view in x['view_membership'] and x.get('longitude') is not None]
  return {'name':name,'type':'geojson','geojsonData':{'type':'FeatureCollection','features':features}}
 return [layer('daily_convenience','日常便利证据'),layer('business_activity_evidence','商业活动证据')]
def main():
 p=argparse.ArgumentParser();p.add_argument('--facility-product',type=Path,required=True);p.add_argument('--accessibility',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);x=p.parse_args();r=build_product(facility_path=x.facility_product,accessibility_path=x.accessibility,output_dir=x.output_dir);print(json.dumps({'bundle_id':r['bundle_id'],'summary':r['summary'],'production_blockers':r['production_blockers']},ensure_ascii=False))
if __name__=='__main__':main()
