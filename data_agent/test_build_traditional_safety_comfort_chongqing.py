import json,subprocess,sys
from pathlib import Path
from scripts.build_traditional_safety_comfort_chongqing import build_product

def sources(root):
 m=root/'mobility.json';e=root/'environment.json';f=root/'facility.json'
 m.write_text(json.dumps({'schema':'traditional_livability.mobility_admin_units.v1','bundle_id':'m','admin_units':[{'admin_unit_id':'甲区|甲镇|1','county':'甲区','township':'甲镇','road_segment_count':10,'service_accessibility_score':0.4,'centroid':{'longitude':106.5,'latitude':29.5}}]},ensure_ascii=False))
 e.write_text(json.dumps({'schema':'uwm.gee_admin_environment_proxy.v1','time_range':{'start':'2024-07-01','end':'2024-07-07'},'admin_environment_rows':[{'admin_id':'env-1','county':'甲区','township':'甲镇','longitude':106.5,'latitude':29.5,'temperature_2m_mean_c':28,'wind_speed_10m_ms':1.1,'cams_pm25_ugm3':30}]},ensure_ascii=False))
 f.write_text(json.dumps({'schema':'uwm.traditional_livability.facility_product.v1','facilities':[{'source_dataset_id':'poi','source_record_id':'1','canonical_class':'public_safety.facility','admin_code':'500101','name':'消防站','longitude':106.6,'latitude':29.6}]} ,ensure_ascii=False));return m,e,f
def test_builder_keeps_environment_reference_only_and_writes_five_files(tmp_path):
 m,e,f=sources(tmp_path);out=tmp_path/'out';r=build_product(mobility_path=m,environment_path=e,facility_path=f,output_dir=out)
 assert {x.name for x in out.iterdir()}=={'overview.json','admin_units.json','channel_readiness.json','evidence_sources.json','map.json'}
 assert len({json.loads(x.read_text())['bundle_id'] for x in out.iterdir()})==1
 assert r['evidence_sources'][1]['join_status']=='reference_only'
 assert r['admin_units'][0]['meteorology_context']['available'] is False
 assert r['summary']['environment_reference_row_count']==1
 assert r['fabricated_value_count']==0
def test_direct_cli(tmp_path):
 m,e,f=sources(tmp_path);out=tmp_path/'cli';c=subprocess.run([sys.executable,'scripts/build_traditional_safety_comfort_chongqing.py','--mobility',str(m),'--environment',str(e),'--facility-product',str(f),'--output-dir',str(out)],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True);assert c.returncode==0,c.stderr
