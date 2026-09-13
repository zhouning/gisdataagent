import json,subprocess,sys
from pathlib import Path
from scripts.build_traditional_daily_convenience_chongqing import build_product
def sources(root):
 f=root/'facility.json';a=root/'access.json'
 f.write_text(json.dumps({'schema':'uwm.traditional_livability.facility_product.v1','facilities':[{'name':'便利店','source_record_id':'1','source_dataset_id':'poi','raw_primary_class':'购物服务','raw_secondary_class':'便民商店/便利店','raw_tertiary_class':None,'admin_code':'500101','longitude':106.5,'latitude':29.5},{'name':'银行','source_record_id':'2','source_dataset_id':'poi','raw_primary_class':'金融保险服务','raw_secondary_class':'银行','raw_tertiary_class':None,'admin_code':'500101','longitude':106.6,'latitude':29.6},{'name':'ATM','source_record_id':'3','source_dataset_id':'poi','raw_primary_class':'金融保险服务','raw_secondary_class':'自动提款机','raw_tertiary_class':None,'admin_code':'500101','longitude':106.7,'latitude':29.7},{'name':'公司','source_record_id':'4','source_dataset_id':'poi','raw_primary_class':'公司企业','raw_secondary_class':'公司','raw_tertiary_class':None,'admin_code':'500101','longitude':106.8,'latitude':29.8},{'name':'KTV','source_record_id':'5','source_dataset_id':'poi','raw_primary_class':'休闲娱乐','raw_secondary_class':'ktv','raw_tertiary_class':None,'admin_code':'500101','longitude':106.9,'latitude':29.9}],'population_units':[{'admin_code':'500101','admin_name':'万州区'},{'admin_code':'500102','admin_name':'涪陵区'}],'source_manifest':{'complete_inventory':False}},ensure_ascii=False))
 a.write_text(json.dumps({'schema':'traditional_livability.mobility_admin_units.v1','admin_units':[{'admin_unit_id':'万州区|甲镇|1','service_accessibility_score':0.5}]},ensure_ascii=False));return f,a
def test_builder_writes_five_files_and_preserves_exact_id_zero_match(tmp_path):
 f,a=sources(tmp_path);out=tmp_path/'out';r=build_product(facility_path=f,accessibility_path=a,output_dir=out)
 assert {x.name for x in out.iterdir()}=={'overview.json','places.json','admin_units.json','channel_readiness.json','map.json'};assert len({json.loads(x.read_text())['bundle_id'] for x in out.iterdir()})==1
 assert r['summary']['daily_convenience_place_count']==3 and r['summary']['business_activity_place_count']==1
 assert r['summary']['exact_accessibility_match_count']==0
 assert r['summary']['bank_branch_count']==1 and r['summary']['atm_access_point_count']==1
 assert r['fabricated_value_count']==0 and 'facility_inventory_sampling_not_complete' in r['production_blockers']
def test_cli(tmp_path):
 f,a=sources(tmp_path);out=tmp_path/'cli';c=subprocess.run([sys.executable,'scripts/build_traditional_daily_convenience_chongqing.py','--facility-product',str(f),'--accessibility',str(a),'--output-dir',str(out)],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True);assert c.returncode==0,c.stderr
