#!/usr/bin/env python3
from pathlib import Path
import json, hashlib, subprocess, re, sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from compile_mussafah_formal_scenarios import parse_external_inflow_report

SRC=Path('/private/tmp/hydraulic_model_export_inspect/Hydraulic Model Data Export/SWMM_Export/Mussafah_00.inp')
EXE=Path('/Users/zhouning/gisdataagent/external_models/swmm-5.2.4/build-local/bin/runswmm')
OUT=Path('/Users/zhouning/Downloads/阿布扎比/flood/解决方案_20260924/下一阶段推进_20260925/正式场景编译_20260926/MUSSAFAH_L2PLUS_B_AUTONOMOUS_PARCEL_167073')

def spans(lines):
 starts=[]
 for i,l in enumerate(lines):
  s=l.strip().upper()
  if s.startswith('[') and s.endswith(']'): starts.append((s,i))
 d={}
 for j,(n,i) in enumerate(starts): d[n]=(i+1, starts[j+1][1] if j+1<len(starts) else len(lines))
 return d

def replace(lines,name,fn):
 s,e=spans(lines)[name]; return lines[:s]+fn(lines[s:e])+lines[e:]

def add_before_end(body, rows):
 out=list(body)
 while out and not out[-1].strip(): out.pop()
 out += rows
 out.append('\n')
 return out

def sha(p):
 h=hashlib.sha256(); h.update(p.read_bytes()); return h.hexdigest()

def compile_inp(dest):
 lines=SRC.read_text(encoding='utf-8',errors='replace').splitlines(keepends=True)
 # Start from L1 proxy: remove planned Parsons chain.
 lines=replace(lines,'[PUMPS]',lambda b:[x for x in b if not (x.strip() and x.split()[0]=='PMP5')])
 for sec in ('[CONDUITS]','[XSECTIONS]','[LOSSES]'):
  lines=replace(lines,sec,lambda b:[x for x in b if not (x.strip() and x.split()[0]=='1235')])
 lines=replace(lines,'[STORAGE]',lambda b:[x for x in b if not (x.strip() and x.split()[0]=='STO-PO3')])
 lines=replace(lines,'[CURVES]',lambda b:[x for x in b if not (x.strip() and x.split()[0]=='STO-PO3_Curve')])
 lines=replace(lines,'[CONTROLS]',lambda b:[x for x in b if 'STO-PO3' not in x and 'PMP5' not in x and x.strip().upper() not in {'PRIORITY 1','PRIORITY 2'}])
 lines=replace(lines,'[COORDINATES]',lambda b:[x for x in b if not (x.strip() and x.split()[0] in {'STO-PO3','PMP5_Junction'})])
 # Real parcel 167073: Makani objectid 167073, centroid in EPSG:32640; nearest model nodes CB4512/CB4513.
 lines=replace(lines,'[STORAGE]',lambda b:add_before_end(b,[
  'OPT-B-167073 2.000 1.000 0 TABULAR OPT-B-167073_CURVE 0 0 0 0 0\n']))
 lines=replace(lines,'[CURVES]',lambda b:add_before_end(b,[
  'OPT-B-167073_CURVE Storage 0.000 1936.0\n',
  'OPT-B-167073_CURVE 1.000 2500.0\n']))
 lines=replace(lines,'[CONDUITS]',lambda b:add_before_end(b,[
  'OPT-B-167073-IN CB4512 OPT-B-167073 54.0 0.012 0 0.450 0 0\n',
  'OPT-B-167073-OUT OPT-B-167073 CB4513 62.0 0.012 0 0.450 0 0\n']))
 lines=replace(lines,'[XSECTIONS]',lambda b:add_before_end(b,[
  'OPT-B-167073-IN CIRCULAR 0.450 0 0 0 1\n',
  'OPT-B-167073-OUT CIRCULAR 0.450 0 0 0 1\n']))
 lines=replace(lines,'[COORDINATES]',lambda b:add_before_end(b,[
  'OPT-B-167073 248778.575951 2695430.070142\n']))
 dest.parent.mkdir(parents=True,exist_ok=True); dest.write_text(''.join(lines),encoding='utf-8')

def report_section(text,title):
 hs=list(re.finditer(r'(?m)^[ \t]*\*{3,}[^\n]*\n[ \t]*([^\n*]+)\n[ \t]*\*{3,}[^\n]*',text))
 for i,m in enumerate(hs):
  if m.group(1).strip().startswith(title): return text[m.start():hs[i+1].start() if i+1<len(hs) else len(text)]
 return ''

def parse(rpt):
 t=rpt.read_text(errors='replace'); sec=report_section(t,'Flow Routing Continuity'); nf=report_section(t,'Node Flooding Summary')
 num=lambda pat: (float(m.group(1)) if (m:=re.search(pat,t,re.I)) else None)
 def second(label):
  m=re.search(rf'^[ \t]*{re.escape(label)}[ \t.]+([-+0-9.Ee]+)[ \t]+([-+0-9.Ee]+)[ \t]*$',sec,re.I|re.M); return float(m.group(2)) if m else None
 rows=[]
 for l in nf.splitlines():
  m=re.match(r'^\s*(\S+)\s+([-+0-9.Ee]+)\s+([-+0-9.Ee]+)\s+\d+\s+\d+:\d+\s+([-+0-9.Ee]+)\s+([-+0-9.Ee]+)\s*$',l)
  if m: rows.append({'node_id':m.group(1),'hours_flooded':float(m.group(2)),'max_rate_lps':float(m.group(3)),'flood_volume_m3':float(m.group(4))*1000,'max_ponded_depth_m':float(m.group(5))})
 vm=re.search(r'Continuity Error\s*\(%\)\s*\.+\s*([-+0-9.Ee]+)',sec,re.I)
 nconv=num(r'% of Steps Not Converging\s*:\s*([-+0-9.Ee]+)')
 return {'solver':'EPA SWMM 5.2.4','analysis':{'flow_units':'LPS','routing':'DYNWAVE','ponding_allowed':bool(re.search(r'Ponding Allowed\s*\.\s*YES',t,re.I))},'routing':{'external_inflow_million_litre':second('External Inflow'),'external_outflow_million_litre':second('External Outflow'),'flooding_loss_million_litre':second('Flooding Loss'),'continuity_error_percent':float(vm.group(1)) if vm else None},'convergence':{'steps_not_converging_percent':nconv},'node_flooding':{'flooded_node_count':len(rows),'total_flood_volume_m3':sum(x['flood_volume_m3'] for x in rows),'maximum_ponded_depth_m':max([x['max_ponded_depth_m'] for x in rows],default=0),'rows':rows},'quality':{'warnings':len(re.findall(r'^\s*WARNING\s+\d+',t,re.I|re.M)),'errors':len(re.findall(r'^\s*ERROR\s+\d+',t,re.I|re.M)),'report_completed':bool(re.search(r'Analysis ended on:',t))}}

def main():
 OUT.mkdir(parents=True,exist_ok=True); inp=OUT/'Mussafah_00.inp'; rpt=OUT/'Mussafah_00.rpt'; out=OUT/'Mussafah_00.out'
 compile_inp(inp)
 p=subprocess.run([str(EXE),str(inp),str(rpt),str(out)],capture_output=True,text=True,timeout=1200)
 parsed=parse_external_inflow_report(rpt.read_text(encoding='utf-8', errors='replace')) if rpt.exists() else {}
 receipt={'scenario_id':'MUSSAFAH_L2PLUS_B_AUTONOMOUS_PARCEL_167073','status':'completed_actual_swmm' if p.returncode==0 and parsed.get('quality',{}).get('report_completed_without_errors') else 'failed_actual_swmm','engineering_admitted':False,'source_scope':'Mussafah_00 Parsons package','solver_run':{'returncode':p.returncode,'stdout_tail':p.stdout[-1000:],'stderr_tail':p.stderr[-1000:]},'input':{'path':str(inp),'sha256':sha(inp),'planned_pond_included':False,'candidate':{'parcel_objectid':'167073','gisid':'10004394906','land_use':'Industrial / showroom','planning_status':'conditional','construction_status':'Not Constructed','ownership_type':'PERMANENT','calculated_area_m2':11004.05686875,'pond_top_area_m2':2500.0,'pond_depth_m':1.0,'side_slope_h_over_v':3.0,'derived_stage_curve_volume_m3':2212.0,'centroid_epsg32640':[248778.575951,2695430.070142],'nearest_upstream_node':'CB4512','downstream_node':'CB4513','connection_type':'gravity_inlet_and_controlled_gravity_outlet','building_intersection_count':0,'road_centerline_intersection_count':0,'utility_overlap_count':0},'representation':{'one_d':'Storage OPT-B-167073 with two 450 mm conduits CB4512→pond→CB4513','two_d':'not included in this actual SWMM run; no 2D benefit claimed','dtm_modified':False},'execution':{'report':str(rpt),'output':str(out),'parsed_report':parsed}}}
 (OUT/'scenario_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(receipt,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
