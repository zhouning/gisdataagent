#!/usr/bin/env python3
"""Run the installed SWMM 5.2.4 and ANUGA on the customer Mussafah_00 data.

Preparation uses the GIS Python environment; execution uses anuga-venv.
Source INPs are immutable. All changes, interface assumptions, grid and
source checksums are recorded in configuration.json. No surrogate is used.
"""
from __future__ import annotations

import argparse
import ctypes as C
import hashlib
import json
import math
import re
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path('/Users/zhouning/Downloads/阿布扎比/flood/解决方案_20260924/下一阶段推进_20260925/正式场景编译_20260926')
WORK = Path('/Users/zhouning/.tmp/mussafah00_coupled')
SCENARIOS = {
    'L1': ('MUSSAFAH_SOURCE_MODEL_L1_PROXY', '既有管网'),
    'L2': ('MUSSAFAH_SOURCE_MODEL_L2_PROXY', '既有管网 + 边界内现状塘（当前清单为 0）'),
    'PARSONS': ('MUSSAFAH_L2PLUS_A_PARSONS_REPORT_PO2', 'Parsons PO-2 / STO-PO3：PMP5 泵送入塘'),
    'B1': ('actual_review_v2/B1', '地块 167073：450 mm 进水管 + 150 mm 出水管'),
    'B2': ('actual_review_v2/B2', '地块 167073：450 mm 进水管 + 300 mm 出水管'),
    'L2B6': ('five_state/L2plusB', 'L2+B：六座地下箱涵（不含 Parsons）'),
    'L2AB': ('five_state/L2plusAplusB', 'L2+A+B：Parsons + 六座地下箱涵'),
}


def dump(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def sections(path):
    result, section = {}, ''
    for raw in Path(path).read_text().splitlines():
        line = raw.split(';')[0].strip()
        if line.startswith('['):
            section = line.upper()
            result[section] = []
        elif line:
            result.setdefault(section, []).append(line.split())
    return result


def prepare(args):
    from shapely.geometry import Point, shape
    from shapely import contains_xy
    from scipy.ndimage import binary_dilation
    from scipy.spatial import cKDTree

    base = np.load(args.work / 'grid/terrain_grid_mussafah_full.npz')
    x, y = base['x'], base['y']
    mask = base['land_mask'].copy()
    xx, yy = np.meshgrid((x[:-1]+x[1:])/2, (y[:-1]+y[1:])/2)
    meta = json.loads((args.work/'grid/grid_metadata_mussafah_full.json').read_text())
    boundary = shape(json.loads(Path(meta['land_mask_source']).read_text())['features'][0]['geometry'])
    design = json.loads((args.source / 'actual_review_v2/design.json').read_text())
    pond_mask = contains_xy(shape(design['footprint_geometry_utm']), xx, yy) & mask
    # Same assessment support in every scenario: intended storage water is
    # reported separately, never credited as disappearing floodwater.
    evaluation_mask = mask & ~pond_mask
    rows = []
    forcing_hashes = []
    for key, (relative, label) in SCENARIOS.items():
        out = args.work/'prepared'/key
        out.mkdir(parents=True, exist_ok=True)
        source = args.source/relative/'Mussafah_00.inp'
        sec = sections(source)
        forcing_hash = hashlib.sha256(json.dumps({s: sec.get(s) for s in ('[INFLOWS]','[TIMESERIES]','[OUTFALLS]')},sort_keys=True).encode()).hexdigest()
        forcing_hashes.append(forcing_hash)
        coordinates = {r[0]: list(map(float,r[1:3])) for r in sec['[COORDINATES]']}
        scenario_mask = mask & ~pond_mask if key in ('B1','B2') else mask.copy()
        np.savez_compressed(out/'grid.npz', x=x, y=y, values=base['values'], land_mask=scenario_mask, evaluation_mask=evaluation_mask)
        cells = np.flatnonzero(scenario_mask)
        tree = cKDTree(np.c_[xx.ravel()[cells], yy.ravel()[cells]])
        bindings, excluded, seen, rim_deltas = [], [], set(), []
        nx = mask.shape[1]
        for table in ('[JUNCTIONS]', '[STORAGE]'):
            for r in sec.get(table, []):
                name = r[0]
                if name not in coordinates:
                    excluded.append({'node':name,'reason':'no_coordinate'}); continue
                px, py = coordinates[name]
                if not boundary.covers(Point(px,py)):
                    excluded.append({'node':name,'reason':'outside_assessment_catchment_retained_in_1d'}); continue
                rim = float(r[1])+float(r[2])
                surcharge = float(r[4]) if table == '[JUNCTIONS]' else 0.
                is_pond = name in ('OPT-B-167073','STO-PO3')
                if name == 'OPT-B-167073':
                    # Open basin below its rim belongs exclusively to 1D
                    # Storage. 2D cells stop at the basin perimeter; each
                    # perimeter segment exchanges over the actual design rim.
                    perimeter = binary_dilation(pond_mask) & scenario_mask
                    targets = list(map(int,np.flatnonzero(perimeter)))
                else:
                    col = int(math.floor((px-x[0])/5))
                    row = int(math.floor((y[0]-py)/5))
                    if 0<=row<mask.shape[0] and 0<=col<nx and scenario_mask[row,col]:
                        targets = [row*nx+col]
                    else:
                        distance, index = tree.query([px,py])
                        if distance > 7.1:
                            excluded.append({'node':name,'reason':'no_active_cell_within_one_diagonal','distance_m':float(distance)}); continue
                        targets = [int(cells[index])]
                seen.add(name)
                for cell in targets:
                    row,col = divmod(cell,nx)
                    terrain = float(base['values'][row:row+2,col:col+2].mean())
                    rim_deltas.append(abs(rim-terrain))
                    # Pressure junctions and wet wells have no demonstrated
                    # surface inlet; transfer native flooding only.
                    capture = table == '[JUNCTIONS]' and not name.startswith(('PMP','J-'))
                    capture = capture or is_pond
                    bindings.append({'node':name,'cell':cell,'rim_m':rim,'surcharge_m':surcharge,
                        'terrain_m':terrain,'node_type':table,'capture_enabled':capture,
                        'opening_area_m2':5.0 if is_pond else .5,
                        'crest_width_m':5.0 if is_pond else 4*math.sqrt(.5),
                        'overflow_share':1/len(targets), 'pond':is_pond})
        # Disable one-dimensional surface ponding only at coupled junctions.
        # Uncoupled cross-boundary assets keep their source behavior.
        current, derived = '', []
        for raw in source.read_text().splitlines():
            text = raw.split(';')[0].strip()
            if text.startswith('['): current=text.upper()
            values=text.split()
            if current=='[JUNCTIONS]' and values and values[0] in seen:
                values += ['0']*max(0,6-len(values)); values[5]='0'; raw=' '.join(values)
            if current=='[OPTIONS]' and values:
                settings={'MAX_TRIALS':str(args.max_trials),'MINIMUM_STEP':'0.01',
                          'ROUTING_STEP':str(args.routing_step),'SURCHARGE_METHOD':args.surcharge,
                          'MIN_SURFAREA':'0'}
                if values[0].upper() in settings: raw=values[0]+' '+settings[values[0].upper()]
            derived.append(raw)
        (out/'model.inp').write_text('\n'.join(derived)+'\n')
        configuration = {'key':key,'label':label,'source_inp':str(source),'source_sha256':sha(source),
            'model_sha256':sha(out/'model.inp'),'grid_sha256':sha(out/'grid.npz'),
            'forcing_sha256':forcing_hash,'flow_units':'LPS','forcing':'646 consultant-supplied node inflow hydrographs; no duplicate 2D rainfall',
            'boundary':'reflective computational catchment divide; no surveyed 2D lateral hydrograph available',
            'surface_manning_n':.035,'coupling_seconds':args.step,'output_seconds':300,
            'duration_seconds':args.duration,'source_resolution_m':5,'bindings':bindings,'excluded_nodes':excluded,
            'unique_coupled_nodes':len(seen),'inlet_parameters':'0.5 m2 opening, Cd 0.61; equivalent opening assumption pending inlet survey',
            'rim_terrain_difference_gt_0_5m':int(sum(v>.5 for v in rim_deltas)),
            'terrain_modification':'none; B pond footprint excluded from 2D, storage below rim represented once in SWMM',
            'pond_representation':'SWMM Storage + source pipe/pump connections; B perimeter surface exchange, Parsons point overflow/capture at source coordinate',
            'numerical_changes':{'coupled_junction_ponded_area_m2':0,'MAX_TRIALS':args.max_trials,'MINIMUM_STEP':.01,
                                 'ROUTING_STEP':args.routing_step,'SURCHARGE_METHOD':args.surcharge},
            'common_assessment_cells':int(evaluation_mask.sum()),'source_catchment_area_m2':float(boundary.area),
            'design':design if key in ('B1','B2') else None}
        dump(out/'configuration.json',configuration)
        rows.append({k:configuration[k] for k in ('key','unique_coupled_nodes','common_assessment_cells','forcing_sha256')})
    if len(set(forcing_hashes)) != 1: raise RuntimeError('scenario_forcing_mismatch')
    dump(args.work/'prepared/manifest.json',rows)
    print(json.dumps(rows,ensure_ascii=False))


def mesh(grid):
    """Two real finite-volume triangles per active 5 m cell."""
    x,y,mask = grid['x'],grid['y'],grid['land_mask']
    ny,nx = mask.shape
    active = np.flatnonzero(mask)
    row,col = np.divmod(active,nx)
    nw=row*(nx+1)+col; ne=nw+1; sw=nw+nx+1; se=sw+1
    triangles=np.stack([np.c_[sw,se,nw],np.c_[se,ne,nw]],axis=1).reshape(-1,3)
    used,inverse=np.unique(triangles,return_inverse=True)
    vr,vc=np.divmod(used,nx+1)
    coords=np.c_[x[vc]-x[0],y[vr]-y[-1]]
    return coords,inverse.reshape(-1,3),np.repeat(np.arange(len(active)),2),grid['values'].ravel()[used],active


class Native:
    def __init__(self, work, inp, out):
        self.lib=C.CDLL(str(ROOT/'external_models/swmm-5.2.4/build-local/lib/libswmm5.dylib'),mode=C.RTLD_GLOBAL)
        for name,argtypes,restype in [
            ('swmm_getVersion',[],C.c_int),('swmm_open',[C.c_char_p]*3,C.c_int),
            ('swmm_start',[C.c_int],C.c_int),('swmm_getIndex',[C.c_int,C.c_char_p],C.c_int),
            ('swmm_getCount',[C.c_int],C.c_int),('swmm_getValue',[C.c_int,C.c_int],C.c_double),
            ('swmm_setValue',[C.c_int,C.c_int,C.c_double],None),
            ('swmm_stride',[C.c_int,C.POINTER(C.c_double)],C.c_int),
            ('swmm_end',[],C.c_int),('swmm_report',[],C.c_int),('swmm_close',[],C.c_int),
            ('swmm_getMassBalErr',[C.POINTER(C.c_float)]*3,C.c_int)]:
            f=getattr(self.lib,name);f.argtypes=argtypes;f.restype=restype
        if self.lib.swmm_getVersion()!=52004: raise RuntimeError('SWMM_5_2_4_required_for_bridge')
        self.bridge=C.CDLL(str(work/'swmm_coupling_api.dylib'))
        self.bridge.mussafah_flood_volume_m3.argtypes=[C.c_int]
        self.bridge.mussafah_flood_volume_m3.restype=C.c_double
        self.bridge.mussafah_surface_head.argtypes=[C.c_int,C.c_double,C.c_double,C.c_int]
        self.bridge.mussafah_surface_head.restype=None
        self.check(self.lib.swmm_open(str(inp).encode(),str(out/'swmm_dynamic.rpt').encode(),str(out/'swmm_dynamic.out').encode()))
        self.check(self.lib.swmm_start(1))
        if int(self.lib.swmm_getValue(8,0))!=4: raise RuntimeError('LPS_model_required')

    def check(self,code):
        if code: raise RuntimeError(f'SWMM_error_{code}')

    def close(self):
        self.check(self.lib.swmm_end())
        a,b,c=C.c_float(),C.c_float(),C.c_float()
        self.check(self.lib.swmm_getMassBalErr(C.byref(a),C.byref(b),C.byref(c)))
        self.check(self.lib.swmm_report()); self.check(self.lib.swmm_close())
        return float(b.value)


def capture_volumes(stage, depth, node_head, bindings, cells, dt, available):
    """Crest-gated weir/orifice capture, with one shared water budget per cell."""
    rim=np.array([b['rim_m'] for b in bindings])
    crest=np.maximum(stage[cells]-rim,0.)
    difference=np.maximum(stage[cells]-np.maximum(node_head,rim),0.)
    width=np.array([b['crest_width_m'] for b in bindings])
    area=np.array([b['opening_area_m2'] for b in bindings])
    q=np.minimum(1.7*width*crest**1.5,.61*area*np.sqrt(2*9.80665*difference))
    q*=np.array([b['capture_enabled'] for b in bindings]) & (depth[cells]>1e-6)
    volumes=q*dt
    total=np.bincount(cells,weights=volumes,minlength=len(available))
    scale=np.minimum(1.,np.divide(available,total,out=np.ones_like(total),where=total>0))
    return volumes*scale[cells]


def run(args):
    import anuga
    from anuga.coordinate_transforms.geo_reference import Geo_reference
    from pyproj import Transformer

    prepared=args.work/'prepared'/args.scenario
    config=json.loads((prepared/'configuration.json').read_text())
    config['duration_seconds']=args.duration
    config['coupling_seconds']=args.step
    native_sections=sections(prepared/'model.inp')
    coupled_ids={b['node'] for b in config['bindings']}
    if any(float(r[5]) != 0 for r in native_sections['[JUNCTIONS]'] if r[0] in coupled_ids):
        raise RuntimeError('coupled_junction_surface_storage_must_be_zero')
    out=args.work/args.output_collection/args.scenario
    if (out/'delivery_summary.json').exists(): raise RuntimeError('completed_output_exists_use_new_work_directory')
    out.mkdir(parents=True,exist_ok=True)
    dump(out/'configuration.json',config)
    dump(out/'progress.json',{'status':'building_mesh','completed_seconds':0,'duration_seconds':args.duration})
    grid=np.load(prepared/'grid.npz')
    xy,tri,tocell,elevation,active=mesh(grid)
    domain=anuga.Domain(xy,tri,geo_reference=Geo_reference(40,float(grid['x'][0]),float(grid['y'][-1])))
    domain.set_name('mussafah00_coupled');domain.set_datadir(str(out))
    domain.set_quantity('elevation',elevation);domain.set_quantity('stage',elevation)
    domain.set_quantity('friction',config['surface_manning_n'])
    domain.set_boundary({'exterior':anuga.Reflective_boundary(domain)})
    # Smoothing affects the optional vertex export only; cell outputs below
    # use native centroid volumes, and the SWW retains centroid quantities.
    domain.set_store_vertices_uniquely(False)
    rate=anuga.Rate_operator(domain,rate=0.)
    n=len(active); areas=np.bincount(tocell,weights=domain.areas,minlength=n)
    if not np.allclose(areas,25): raise RuntimeError('5m_cell_area_mismatch')
    full_to_compact=np.full(grid['land_mask'].size,-1,dtype=int);full_to_compact[active]=np.arange(n)
    bindings=config['bindings']; cells=np.array([full_to_compact[b['cell']] for b in bindings])
    if np.any(cells<0): raise RuntimeError('interface_outside_numerical_mesh')
    swmm=Native(args.work,prepared/'model.inp',out)
    ids=sorted({b['node'] for b in bindings}); lookup={name:i for i,name in enumerate(ids)}
    nodeidx=np.array([swmm.lib.swmm_getIndex(2,name.encode()) for name in ids],dtype=int)
    if np.any(nodeidx<0): raise RuntimeError('missing_swmm_node')
    binder=np.array([lookup[b['node']] for b in bindings])
    share=np.array([b['overflow_share'] for b in bindings])
    flood=lambda: np.array([swmm.bridge.mussafah_flood_volume_m3(int(i)) for i in nodeidx])
    head=lambda: np.array([swmm.lib.swmm_getValue(304,int(i)) for i in nodeidx])
    cumulative=flood();previous_flux=float(domain.get_boundary_flux_integral())
    records=[]; snapshots=[]; hydro=[]; native_node_frames=[]; maximum=np.zeros(n)
    assessment=grid['evaluation_mask'].ravel()[active]
    maximum_areas={str(h):0. for h in (.01,.05,.15,.3,.5)}
    last_store=float(domain.get_water_volume());start_wall=time.monotonic()
    stageq=domain.quantities['stage'];zq=domain.quantities['elevation']
    snapshots_dir=out/'temporal_snapshots';snapshots_dir.mkdir(exist_ok=True)
    depth_path=out/'depth_frames.npy'
    output_frames=args.duration//300
    depth_frames=np.lib.format.open_memmap(depth_path,mode='w+',dtype='float32',shape=(output_frames,n))
    evaluate=iter(domain.evolve(yieldstep=args.step,outputstep=300,finaltime=args.duration,skip_initial_step=True))
    for tick in range(args.duration//args.step):
        # Native triangle depths/volumes, not a raster elevation subtraction
        # that could invent wet cells on a dry sloping triangle.
        tri_depth=np.maximum(stageq.centroid_values-zq.centroid_values,0.)
        available=np.bincount(tocell,weights=tri_depth*domain.areas,minlength=n)
        stage=np.bincount(tocell,weights=stageq.centroid_values*domain.areas,minlength=n)/areas
        cell_depth=available/areas
        heads=head()
        capture=capture_volumes(stage,cell_depth,heads[binder],bindings,cells,args.step,available)
        withdrawal=np.bincount(cells,weights=capture,minlength=n)
        retained=1.-np.divide(withdrawal,available,out=np.zeros(n),where=available>0)
        retained=np.maximum(retained,0.)
        # Conservative operator split: remove actual water before feeding it
        # into SWMM. No negative rate can be clipped after 1D has received it.
        stageq.centroid_values[:]=zq.centroid_values+tri_depth*retained[tocell]
        for q in ('xmomentum','ymomentum'): domain.quantities[q].centroid_values[:]*=retained[tocell]
        domain.fractional_step_volume_integral-=float(capture.sum())
        node_capture=np.bincount(binder,weights=capture,minlength=len(ids))
        for j,index in enumerate(nodeidx):
            swmm.lib.swmm_setValue(306,int(index),float(node_capture[j]/args.step*1000))
        # Feed the wet surface head back to the native junction surcharge
        # threshold, so elevated surface water can restrain network overflow.
        for b,cell,index in zip(bindings,cells,nodeidx[binder]):
            if b['node_type']=='[JUNCTIONS]':
                swmm.bridge.mussafah_surface_head(int(index),float(stage[cell]),b['surcharge_m'],int(cell_depth[cell]>1e-6))
        elapsed=C.c_double()
        swmm.check(swmm.lib.swmm_stride(args.step,C.byref(elapsed)))
        seconds=(tick+1)*args.step
        reported=elapsed.value*86400
        if abs(reported-seconds)>.001 and not (seconds==args.duration and reported==0):
            raise RuntimeError(f'native_clock_mismatch:{reported}:{seconds}')
        current=flood();overflow=np.maximum(current-cumulative,0.);cumulative=current
        inject=np.bincount(cells,weights=overflow[binder]*share,minlength=n)
        rate.set_rate((inject/args.step/areas)[tocell])
        previous_source=float(rate.cumulative_influx)
        yielded=float(next(evaluate))
        if abs(yielded-seconds)>.001: raise RuntimeError('ANUGA_clock_mismatch')
        applied=float(rate.cumulative_influx)-previous_source
        storage=float(domain.get_water_volume())
        flux=float(domain.get_boundary_flux_integral());delta_flux=flux-previous_flux;previous_flux=flux
        residual=storage-last_store-(applied-capture.sum())-delta_flux
        exchange_difference=applied-inject.sum()
        passed=abs(residual)<=max(.001,abs(applied)*1e-7) and abs(exchange_difference)<=max(.001,abs(inject.sum())*1e-7)
        records.append({'window_index':tick,'start_seconds':seconds-args.step,'end_seconds':seconds,
            'total_swmm_to_anuga_m3':float(inject.sum()),'total_anuga_to_swmm_m3':float(capture.sum()),
            'surface_storage_end_m3':storage,'surface_mass_balance_residual_m3':float(residual),
            'boundary_net_inflow_m3':float(delta_flux),'exchange_application_difference_m3':float(exchange_difference),
            'quality_passed':bool(passed)})
        last_store=storage
        depth=np.bincount(tocell,weights=np.maximum(stageq.centroid_values-zq.centroid_values,0.)*domain.areas,minlength=n)/areas
        if not np.all(np.isfinite(depth)): raise RuntimeError('non_finite_surface_state')
        maximum=np.maximum(maximum,depth)
        for threshold in maximum_areas:
            maximum_areas[threshold]=max(maximum_areas[threshold],float(np.count_nonzero((depth>=float(threshold)) & assessment)*25))
        if seconds%300==0:
            index=seconds//300-1
            depth_frames[index]=depth
            snapshots.append({'index':index,'time_seconds':seconds,'time_minutes':seconds/60,'path':f'temporal_snapshots/surface_depth_t{index:03d}.geojson'})
            hydro.append({'time_seconds':seconds,'surface_storage_m3':storage,'inundated_area_ge_0_01m2':float(np.sum((depth>=.01)&assessment)*25),'maximum_depth_m':float(depth[assessment].max())})
            native_node_frames.append([[swmm.lib.swmm_getValue(p,int(i)) for p in (303,304,305)] for i in nodeidx])
        if seconds%1800==0 or tick==0:
            progress={'status':'running','completed_seconds':seconds,'duration_seconds':args.duration,
                'percent':seconds/args.duration*100,'wall_seconds':round(time.monotonic()-start_wall,1),
                'surface_storage_m3':storage,'quality_failed_windows':sum(not r['quality_passed'] for r in records)}
            dump(out/'progress.json',progress);print(json.dumps(progress),flush=True)
    routing_error=swmm.close()
    depth_frames.flush()
    np.savez_compressed(out/'cell_results.npz',active_cells=active,maximum_depth_m=maximum,x=grid['x'],y=grid['y'],assessment_mask=assessment)
    np.savez_compressed(out/'node_results.npz',node_ids=ids,states=np.asarray(native_node_frames),cumulative_overflow_m3=cumulative)
    rpt=(out/'swmm_dynamic.rpt').read_text(errors='replace')
    match=re.search(r'% of Steps Not Converging\s*:\s*([\d.]+)',rpt)
    not_converging=float(match.group(1)) if match else None
    continuity_ok=abs(routing_error)<=1.
    quality=all(r['quality_passed'] for r in records) and continuity_ok and not_converging is not None and not_converging<=1.
    receipt={'schema':'mussafah00.native_coupling.v2','run_id':f'mussafah00-{args.scenario}-native-v2',
        'status':'completed','quality_passed':quality,'window_seconds':args.step,
        'interface_bindings':bindings,'unique_swmm_nodes':len(ids),'windows':records,
        'swmm_routing_continuity_error_percent':routing_error,'swmm_nonconverging_steps_percent':not_converging,
        'overflow_integration':'native NodeStats.volFlooded, integrated at every SWMM routing step',
        'surface_capture':'conservative withdrawal before native SWMM API inflow',
        'head_feedback':'wet surface stage updates native junction surcharge threshold',
        'source_configuration_sha256':sha(out/'configuration.json')}
    dump(out/'bidirectional_coupling_receipt.json',receipt)
    dump(out/'progress.json',{'status':'exporting','completed_seconds':args.duration,'duration_seconds':args.duration})
    project=Transformer.from_crs(32640,4326,always_xy=True)
    nx=grid['land_mask'].shape[1]
    rings={}
    for compact in np.flatnonzero(maximum>=.01):
        row,col=divmod(int(active[compact]),nx)
        ring=[(grid['x'][col],grid['y'][row]),(grid['x'][col+1],grid['y'][row]),(grid['x'][col+1],grid['y'][row+1]),(grid['x'][col],grid['y'][row+1]),(grid['x'][col],grid['y'][row])]
        rings[int(compact)]=[list(project.transform(*p)) for p in ring]
    def layer(values,seconds=None):
        features=[]
        for compact in np.flatnonzero(values>=.01):
            props={'cell_id':int(active[compact]),'depth_m':float(values[compact]),'maximum_depth_m':float(values[compact]),'cell_size_m':5,'assessment_cell':bool(assessment[compact])}
            if seconds is not None: props['time_minutes']=seconds/60
            features.append({'type':'Feature','properties':props,'geometry':{'type':'Polygon','coordinates':[rings[int(compact)]]}})
        return {'type':'FeatureCollection','features':features}
    # Compact GeoJSON, not indented megabytes per frame.
    for row,values in zip(snapshots,depth_frames):
        (out/row['path']).write_text(json.dumps(layer(values,row['time_seconds']),separators=(',',':')))
    (out/'maximum_depth_wgs84.geojson').write_text(json.dumps(layer(maximum),separators=(',',':')))
    dump(out/'temporal_snapshots/manifest.json',{'snapshots':snapshots,'output_interval_seconds':300})
    dump(out/'hydrograph.json',hydro)
    dump(out/'delivery_summary.json',{'schema':'mussafah00.native_1d2d.v2','status':'completed',
        'solver':'EPA SWMM 5.2.4 + ANUGA 2D','run_id':receipt['run_id'],
        'domain':{'area_m2':config['source_catchment_area_m2'],'active_land_cells':n,'cell_size_m':5,'triangle_count':len(tri),
            'simulation_duration_hours':args.duration/3600,'output_step_minutes':5,
            'bounds_epsg32640':[float(grid['x'][0]),float(grid['y'][-1]),float(grid['x'][-1]),float(grid['y'][0])]},
        'results':{'maximum_depth_m':float(maximum[assessment].max()),'inundated_area_ge_0_01m2':maximum_areas['0.01'],
            'peak_simultaneous_inundated_area_m2':maximum_areas,'maximum_depth_envelope_area_ge_0_01m2':float(np.sum((maximum>=.01)&assessment)*25),
            'final_surface_storage_m3':storage,'final_inundated_area_ge_0_01m2':hydro[-1]['inundated_area_ge_0_01m2']},
        'coupling':{'interface_count':len(bindings),'unique_node_count':len(ids),'window_count':len(records),'exchange_window_seconds':args.step,
            'total_swmm_to_anuga_m3':sum(r['total_swmm_to_anuga_m3'] for r in records),
            'total_anuga_to_swmm_m3':sum(r['total_anuga_to_swmm_m3'] for r in records),'quality_passed':quality},
        'quality_gates':{'passed':quality,'swmm_continuity_error_percent':routing_error,'nonconverging_steps_percent':not_converging,
            'surface_failed_windows':sum(not r['quality_passed'] for r in records)},
        'model_configuration':{k:v for k,v in config.items() if k not in ('bindings','design')},
        'outputs':{'native_sww':'mussafah00_coupled.sww'},
        'claim_boundary':'真实求解；当前模型文件入流情景。入水口尺寸和无流二维外边界为明示假设，未按实测校准；不代表施工许可或最低成本结论。'})
    dump(out/'progress.json',{'status':'completed','completed_seconds':args.duration,'duration_seconds':args.duration,'quality_passed':quality})
    print(json.dumps({'scenario':args.scenario,'completed':True,'quality_passed':quality,'routing_error_percent':routing_error,'nonconverging_percent':not_converging}),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--scenario',choices=list(SCENARIOS),default='L1')
    parser.add_argument('--source',type=Path,default=SOURCE)
    parser.add_argument('--work',type=Path,default=WORK)
    parser.add_argument('--output-collection',default='real_runs')
    parser.add_argument('--duration',type=int,default=172800)
    parser.add_argument('--step',type=int,default=60)
    parser.add_argument('--routing-step',type=float,default=.25)
    parser.add_argument('--max-trials',type=int,default=80)
    parser.add_argument('--surcharge',choices=['EXTRAN','SLOT'],default='SLOT')
    args=parser.parse_args()
    if args.duration%300 or 300%args.step: parser.error('duration must align 300 s; coupling step must divide 300 s')
    if args.prepare: prepare(args)
    else:
        try: run(args)
        except Exception as exc:
            dump(args.work/args.output_collection/args.scenario/'progress.json',{'status':'failed','error':f'{type(exc).__name__}: {exc}'})
            raise


if __name__=='__main__': main()
