import json,subprocess,sys
from pathlib import Path
from scripts.build_traditional_public_space_chongqing import build_product

def source(path):
 p=path/'facility.json';p.write_text(json.dumps({'schema':'uwm.traditional_livability.facility_product.v1','bundle_id':'f','facilities':[{'name':'公园','source_record_id':'1','source_dataset_id':'poi','raw_primary_class':'旅游景点','raw_secondary_class':'公园','raw_tertiary_class':None,'admin_code':'500101','longitude':106.5,'latitude':29.5},{'name':'网吧','source_record_id':'2','source_dataset_id':'poi','raw_primary_class':'体育休闲服务','raw_secondary_class':'娱乐场所','raw_tertiary_class':'网吧','admin_code':'500101','longitude':106.6,'latitude':29.6},{'name':'博物馆','source_record_id':'3','source_dataset_id':'poi','raw_primary_class':'旅游景点','raw_secondary_class':'博物馆','raw_tertiary_class':None,'admin_code':'万州区','longitude':106.7,'latitude':29.7}],'population_units':[{'admin_code':'500101','admin_name':'万州区'},{'admin_code':'500102','admin_name':'涪陵区'}],'source_manifest':{'complete_inventory':False}},ensure_ascii=False));return p
def test_builder_writes_five_files_and_exclusion_statistics(tmp_path):
 out=tmp_path/'out';r=build_product(facility_product_path=source(tmp_path),output_dir=out)
 assert {p.name for p in out.iterdir()}=={'overview.json','spaces.json','admin_units.json','channel_readiness.json','map.json'}
 assert len({json.loads(p.read_text())['bundle_id'] for p in out.iterdir()})==1
 assert r['summary']['eligible_space_count']==2 and r['summary']['excluded_record_count']==1
 assert r['summary']['exclusion_reason_counts']['commercial_or_ambiguous_recreation_excluded']==1
 assert r['fabricated_value_count']==0
 assert 'facility_inventory_sampling_not_complete' in r['production_blockers']
def test_builder_supports_direct_cli(tmp_path):
 out=tmp_path/'cli';c=subprocess.run([sys.executable,'scripts/build_traditional_public_space_chongqing.py','--facility-product',str(source(tmp_path)),'--output-dir',str(out)],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
 assert c.returncode==0,c.stderr
