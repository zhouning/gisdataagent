"""Actual EPA SWMM 5.2.4 + ANUGA finite-volume AAM runs (no surrogate).
Run with external_models/anuga-venv/bin/python; preparation uses GIS Python.
"""
from pathlib import Path
import argparse, ctypes as C, hashlib, json, re, time, traceback
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=Path('/Users/zhouning/gisdataagent')
def dump(path,obj):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n');tmp.replace(p)
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(2**20),b''):h.update(b)
    return h.hexdigest()

class Native:
    def __init__(self,scenario,out,names):
        # Final overnight runs use the same installed library as the completed
        # 600s coupled trial. Experimental probe builds are not auto-selected.
        self.library=ROOT/'external_models/swmm-5.2.4/build-local/lib/libswmm5.dylib'
        self.lib=C.CDLL(str(self.library),mode=C.RTLD_GLOBAL)
        for name,types,res in [('swmm_open',[C.c_char_p]*3,C.c_int),('swmm_start',[C.c_int],C.c_int),
            ('swmm_getIndex',[C.c_int,C.c_char_p],C.c_int),('swmm_stride',[C.c_int,C.POINTER(C.c_double)],C.c_int),
            ('swmm_end',[],C.c_int),('swmm_report',[],C.c_int),('swmm_close',[],C.c_int),
            ('swmm_getVersion',[],C.c_int),('swmm_getMassBalErr',[C.POINTER(C.c_float)]*3,C.c_int)]:
            f=getattr(self.lib,name);f.argtypes=types;f.restype=res
        assert self.lib.swmm_getVersion()==52004
        self.bridge=C.CDLL(str(HERE/'aam_swmm_bridge.dylib'))
        iarr=np.ctypeslib.ndpointer(dtype=np.int32,flags='C_CONTIGUOUS')
        darr=np.ctypeslib.ndpointer(dtype=np.float64,flags='C_CONTIGUOUS')
        self.bridge.aam_state.argtypes=[C.c_int,iarr,darr,darr,darr]
        self.bridge.aam_forcing.argtypes=[C.c_int,iarr,darr,darr,iarr]
        self.bridge.aam_storage_m3.restype=C.c_double
        self.bridge.aam_sentinel_flow_cms.argtypes=[C.c_int];self.bridge.aam_sentinel_flow_cms.restype=C.c_double
        self.check(self.lib.swmm_open(str(HERE/'prepared'/scenario/'model.inp').encode(),str(out/f'AAM_{scenario}_1D.rpt').encode(),str(out/f'AAM_{scenario}_1D.out').encode()))
        self.check(self.lib.swmm_start(1))
        self.ids=np.array([self.lib.swmm_getIndex(2,name.encode()) for name in names],dtype=np.int32)
        if np.any(self.ids<0):raise RuntimeError('missing_native_node')
        self.sentinel=self.lib.swmm_getIndex(2,b'ENGINE_DRY_SENTINEL')
        self.head=np.zeros(len(names));self.flood=np.zeros(len(names));self.vol=np.zeros(len(names))
        self.state()
    def check(self,code):
        if code:raise RuntimeError(f'SWMM error {code}; inspect swmm.rpt')
    def state(self):
        self.bridge.aam_state(len(self.ids),self.ids,self.head,self.flood,self.vol)
    def force(self,q,heads,wet):
        self.bridge.aam_forcing(len(self.ids),self.ids,np.ascontiguousarray(q),np.ascontiguousarray(heads),np.ascontiguousarray(wet,dtype=np.int32))
    def stride(self,dt):
        elapsed=C.c_double();self.check(self.lib.swmm_stride(dt,C.byref(elapsed)));self.state();return elapsed.value*86400
    def storage(self):return self.bridge.aam_storage_m3()
    def close(self):
        self.check(self.lib.swmm_end())
        a,b,c=C.c_float(),C.c_float(),C.c_float()
        self.check(self.lib.swmm_getMassBalErr(C.byref(a),C.byref(b),C.byref(c)))
        self.check(self.lib.swmm_report());self.check(self.lib.swmm_close());return b.value

def mesh(grid):
    x,y,mask=grid['x'],grid['y'],grid['land_mask'];ny,nx=mask.shape
    active=np.flatnonzero(mask);row,col=np.divmod(active,nx)
    nw=row*(nx+1)+col;ne=nw+1;sw=nw+nx+1;se=sw+1
    triangles=np.stack([np.c_[sw,se,nw],np.c_[se,ne,nw]],axis=1).reshape(-1,3)
    used,inverse=np.unique(triangles,return_inverse=True);vr,vc=np.divmod(used,nx+1)
    return np.c_[x[vc]-x[0],y[vr]-y[-1]],inverse.reshape(-1,3),grid['values'].ravel()[used],active

def run(args):
    import anuga
    from anuga.coordinate_transforms.geo_reference import Geo_reference
    from anuga.abstract_2d_finite_volumes.generic_boundary_conditions import Transmissive_boundary
    class OutwardBoundary(Transmissive_boundary):
        """Zero-gradient outgoing state; reflect incoming normal momentum.
        Reflection of inward velocity yields zero incoming mass flux; simply
        setting boundary inward velocity to zero would still admit water.
        No prescribed external stage is introduced at an administrative edge.
        """
        def evaluate_segment(self,domain,segment_edges):
            super().evaluate_segment(domain,segment_edges)
            ids=segment_edges;v=domain.boundary_cells[ids];e=domain.boundary_edges[ids]
            n1=domain.normals[v,2*e];n2=domain.normals[v,2*e+1]
            qx=domain.quantities['xmomentum'].boundary_values
            qy=domain.quantities['ymomentum'].boundary_values
            un=qx[ids]*n1+qy[ids]*n2
            incoming=np.minimum(un,0.)
            qx[ids]-=2*incoming*n1;qy[ids]-=2*incoming*n2
    out=HERE/args.collection/args.scenario
    out.mkdir(parents=True,exist_ok=True)
    if (out/'run_receipt.json').exists():raise RuntimeError('completed_run_exists_use_new_collection')
    config=json.loads((HERE/'prepared/configuration.json').read_text())
    start=time.monotonic()
    def progress(status,seconds=0,**extra):
        item={'status':status,'scenario':args.scenario,'completed_seconds':seconds,
              'duration_seconds':args.duration,'percent':seconds/args.duration*100,
              'wall_seconds':round(time.monotonic()-start,1),**extra}
        dump(out/'progress.json',item);print(json.dumps(item),flush=True)
    progress('building_mesh')
    grid=np.load(HERE/'prepared/grid.npz');xy,tri,elevation,active=mesh(grid)
    domain=anuga.Domain(xy,tri,geo_reference=Geo_reference(40,float(grid['x'][0]),float(grid['y'][-1]),hemisphere='northern',epsg=32640))
    domain.set_name(f'AAM_{args.scenario}_2D');domain.set_datadir(str(out))
    domain.set_store(True);domain.set_store_centroids(True)
    domain.set_store_vertices_uniquely(False)
    domain.minimum_storable_height=0.
    domain.max_size=50_000_000_000
    domain.set_omp_num_threads(args.threads)
    domain.set_quantity('elevation',elevation);domain.set_quantity('stage',elevation)
    domain.set_quantity('friction',config['surface_manning_n'])
    domain.set_boundary({'exterior':OutwardBoundary(domain)})
    rate=anuga.Rate_operator(domain,rate=0.)
    del xy,tri,elevation
    n=len(active);nt=2*n
    # Triangles are stored consecutively per raster cell and each is 5000m2.
    if not np.allclose(domain.areas,5000.):raise RuntimeError('triangle_area_mismatch')
    cellarea=10000.
    full_to_compact=np.full(grid['land_mask'].size,-1,dtype=np.int32);full_to_compact[active]=np.arange(n)
    interface=np.load(HERE/'prepared'/args.scenario/'interfaces.npz')
    cells=full_to_compact[interface['full_cells']].copy()
    # A few pipeline endpoints fall in boundary pixels whose centres are just
    # outside AAM. Bind them to their closest active 100m cell, never drop water.
    remap=[]
    if np.any(cells<0):
        from scipy.spatial import cKDTree
        row,col=np.divmod(active,grid['land_mask'].shape[1])
        centres=np.c_[(grid['x'][col]+grid['x'][col+1])/2,(grid['y'][row]+grid['y'][row+1])/2]
        bad=np.flatnonzero(cells<0);dist,new=cKDTree(centres).query(interface['xy'][bad])
        if np.any(dist>142):raise RuntimeError('boundary_endpoint_too_far_from_active_grid')
        cells[bad]=new
        remap=[{'node':str(interface['names'][i]),'distance_m':float(d),'compact_cell':int(c)} for i,d,c in zip(bad,dist,new)]
    dump(out/'boundary_interface_remapping.json',remap)
    rim=interface['rim_m'];opening=interface['opening_area_m2'];width=interface['crest_width_m']
    pond=int(interface['pond_logical_index']);swmm=Native(args.scenario,out,interface['names'])
    cumulative=swmm.flood.copy();nativeinitial=swmm.storage()
    stageq=domain.quantities['stage'];zq=domain.quantities['elevation']
    maximum=np.zeros(n);maximum_velocity=np.zeros(n)
    frames=np.lib.format.open_memmap(out/'depth_frames.npy',mode='w+',dtype='float32',shape=(args.duration//300+1,n));frames[0]=0
    node_frames=np.lib.format.open_memmap(out/'node_head_frames.npy',mode='w+',dtype='float32',shape=(args.duration//300+1,len(cells)));node_frames[0]=swmm.head
    records=[];hydro=[];laststore=float(domain.get_water_volume());previousflux=float(domain.get_boundary_flux_integral())
    rainfall=totalcapture=totaloverflow=totalflux=0.;maximum_native_residual=0.
    evaluate=iter(domain.evolve(yieldstep=args.step,outputstep=300,finaltime=args.duration,skip_initial_step=False))
    if abs(float(next(evaluate)))>.001:raise RuntimeError('ANUGA_initial_output_clock_mismatch')
    progress('running',mesh_triangles=nt,native_nodes=len(cells),mesh_build_seconds=round(time.monotonic()-start,1))
    last_progress=time.monotonic()
    try:
        for tick in range(args.duration//args.step):
            t0=tick*args.step;t1=t0+args.step
            depth_tri=np.maximum(stageq.centroid_values-zq.centroid_values,0.)
            available=depth_tri.reshape(n,2).sum(axis=1)*5000.
            depth=available/cellarea
            stage=stageq.centroid_values.reshape(n,2).mean(axis=1)
            crest=np.maximum(stage[cells]-rim,0.)
            dh=np.maximum(stage[cells]-np.maximum(swmm.head,rim),0.)
            capture=np.minimum(1.7*width*crest**1.5,.61*opening*np.sqrt(2*9.80665*dh))*args.step
            capture*=depth[cells]>1e-6
            demand=np.bincount(cells,weights=capture,minlength=n)
            factor=np.minimum(1.,np.divide(available,demand,out=np.ones(n),where=demand>0))
            capture*=factor[cells]
            withdrawal=np.bincount(cells,weights=capture,minlength=n)
            retained=np.maximum(0.,1-np.divide(withdrawal,available,out=np.zeros(n),where=available>0))
            stageq.centroid_values[:]=zq.centroid_values+depth_tri*np.repeat(retained,2)
            for key in ['xmomentum','ymomentum']:domain.quantities[key].centroid_values[:]*=np.repeat(retained,2)
            vcap=float(capture.sum());domain.fractional_step_volume_integral-=vcap
            swmm.force(capture/args.step,stage[cells],depth[cells]>1e-6)
            nativeclock=swmm.stride(args.step)
            if abs(nativeclock-t1)>.001 and not (t1==18000 and nativeclock==0):raise RuntimeError(f'native_clock_mismatch {nativeclock} {t1}')
            overflow=np.maximum(swmm.flood-cumulative,0.);cumulative[:]=swmm.flood
            inject=np.bincount(cells,weights=overflow,minlength=n);vover=float(overflow.sum())
            rainrate=60/1000/3600 if t0<3600 else 0.
            vrain=rainrate*cellarea*n*args.step
            rate.set_rate(np.repeat(inject/(args.step*cellarea)+rainrate,2))
            source_before=float(rate.cumulative_influx);actual=float(next(evaluate))
            if abs(actual-t1)>.001:raise RuntimeError('surface_clock_mismatch')
            applied=float(rate.cumulative_influx)-source_before
            storage=float(domain.get_water_volume());flux=float(domain.get_boundary_flux_integral())
            deltaflux=flux-previousflux;previousflux=flux
            residual=storage-laststore-(applied-vcap)-deltaflux
            exchange=applied-vrain-vover
            native_storage=swmm.storage()
            totalcapture+=vcap;totaloverflow+=vover;rainfall+=vrain;totalflux+=deltaflux
            native_residual=native_storage-nativeinitial-totalcapture+totaloverflow
            maximum_native_residual=max(maximum_native_residual,abs(native_residual))
            sentinel=swmm.bridge.aam_sentinel_flow_cms(swmm.sentinel)
            if abs(sentinel)>1e-12:raise RuntimeError('engine_sentinel_has_flow')
            passed=abs(residual)<=max(.01,abs(applied)*1e-7) and abs(exchange)<=max(.01,abs(applied)*1e-7)
            records.append({'start_seconds':t0,'end_seconds':t1,'rain_m3':vrain,'surface_to_network_m3':vcap,
                'network_to_surface_m3':vover,'surface_storage_m3':storage,'network_storage_m3':native_storage,
                'pond_storage_m3':float(swmm.vol[pond]) if args.scenario=='L2' else 0.,
                'boundary_net_inflow_m3':deltaflux,'surface_residual_m3':residual,
                'source_application_residual_m3':exchange,'network_cumulative_residual_m3':native_residual,
                'surface_quality_passed':bool(passed)})
            laststore=storage
            depth=np.maximum(stageq.centroid_values-zq.centroid_values,0.).reshape(n,2).mean(axis=1)
            if not np.all(np.isfinite(depth)) or np.max(depth)>500:raise RuntimeError('invalid_surface_depth')
            maximum=np.maximum(maximum,depth)
            qx=domain.quantities['xmomentum'].centroid_values.reshape(n,2).mean(axis=1)
            qy=domain.quantities['ymomentum'].centroid_values.reshape(n,2).mean(axis=1)
            velocity=np.divide(np.hypot(qx,qy),depth,out=np.zeros(n),where=depth>=.01)
            maximum_velocity=np.maximum(maximum_velocity,velocity)
            if t1%300==0:
                frames[t1//300]=depth;node_frames[t1//300]=swmm.head
                hydro.append({'time_seconds':t1,'surface_storage_m3':storage,'network_storage_m3':native_storage,
                    'pond_volume_m3':float(swmm.vol[pond]) if args.scenario=='L2' else 0.,
                    'pond_stage_m':float(swmm.head[pond]) if args.scenario=='L2' else None,
                    'rain_cumulative_m3':rainfall,'surface_to_network_cumulative_m3':totalcapture,
                    'network_to_surface_cumulative_m3':totaloverflow,'boundary_net_inflow_cumulative_m3':totalflux,
                    'maximum_depth_m':float(depth.max()),'area_ge_0_05m_km2':int((depth>=.05).sum())*.01,
                    'area_ge_0_15m_km2':int((depth>=.15).sum())*.01,
                    'whole_system_residual_m3':storage+native_storage-nativeinitial-rainfall-totalflux})
                frames.flush();node_frames.flush();dump(out/'hydrograph.json',hydro)
            if tick==0 or t1==args.duration or time.monotonic()-last_progress>=40:
                progress('running',t1,surface_storage_m3=storage,network_storage_m3=native_storage,
                    pond_storage_m3=float(swmm.vol[pond]) if args.scenario=='L2' else 0.,
                    surface_failed_windows=sum(not r['surface_quality_passed'] for r in records),
                    network_residual_m3=native_residual,maximum_depth_m=float(depth.max()))
                last_progress=time.monotonic();dump(out/'water_balance_windows.json',records)
    except BaseException:
        dump(out/'water_balance_windows.json',records)
        progress('failed',int(domain.get_time()),error=traceback.format_exc())
        try:swmm.close()
        except Exception:pass
        raise
    routing_error=swmm.close();frames.flush();node_frames.flush()
    report=(out/f'AAM_{args.scenario}_1D.rpt').read_text(errors='replace')
    m=re.search(r'% of Steps Not Converging\s*:\s*([\d.]+)',report)
    nonconverging=float(m.group(1)) if m else None
    surface_ok=all(r['surface_quality_passed'] for r in records)
    whole_residual=storage+native_storage-nativeinitial-rainfall-totalflux
    native_relative=abs(native_residual)/max(totalcapture,1)*100
    quality=surface_ok and abs(routing_error)<=1 and native_relative<=1 and nonconverging is not None and nonconverging<=1
    np.savez_compressed(out/'cell_results.npz',active_cells=active,maximum_depth_m=maximum,
        maximum_velocity_mps=maximum_velocity,final_depth_m=depth,x=grid['x'],y=grid['y'])
    np.savez_compressed(out/'node_results.npz',node_ids=interface['names'],final_head_m=swmm.head,
        final_volume_m3=swmm.vol,cumulative_overflow_m3=cumulative)
    receipt={'schema':'aam.native_coupled.v1','status':'completed','quality_passed':quality,
        'scenario':args.scenario,'solver':'EPA SWMM 5.2.4 + ANUGA 2D finite-volume shallow-water',
        'swmm_library':str(swmm.library),'swmm_library_sha256':sha(swmm.library),
        'coupling_bridge_sha256':sha(HERE/'aam_swmm_bridge.dylib'),
        'native_1d_binary':f'AAM_{args.scenario}_1D.out',
        'native_1d_report':f'AAM_{args.scenario}_1D.rpt',
        'native_2d_netcdf':f'AAM_{args.scenario}_2D.sww',
        'native_output_interval_seconds':300,
        'duration_seconds':args.duration,'coupling_seconds':args.step,'output_seconds':300,
        'active_cells':n,'triangle_count':nt,'grid_spacing_m':100,'native_node_count':len(cells),
        'rainfall_volume_m3':rainfall,'surface_to_network_volume_m3':totalcapture,'network_to_surface_volume_m3':totaloverflow,
        'surface_final_volume_m3':storage,'network_final_volume_m3':native_storage,
        'pond_final_volume_m3':float(swmm.vol[pond]) if args.scenario=='L2' else 0.,
        'boundary_net_inflow_m3':totalflux,'whole_system_residual_m3':whole_residual,
        'whole_system_residual_percent_of_rain':whole_residual/max(rainfall,1)*100,
        'swmm_routing_error_percent':routing_error,'network_residual_percent_of_captured_water':native_relative,
        'maximum_network_residual_m3':maximum_native_residual,'swmm_nonconverging_steps_percent':nonconverging,
        'surface_failed_windows':sum(not r['surface_quality_passed'] for r in records),
        'maximum_depth_m':float(maximum.max()),'maximum_depth_envelope_area_ge_0_15m_km2':int((maximum>=.15).sum())*.01,
        'maximum_velocity_mps':float(maximum_velocity.max()),'wall_seconds':time.monotonic()-start,
        'native_inp_sha256':sha(HERE/'prepared'/args.scenario/'model.inp'),'grid_sha256':sha(HERE/'prepared/grid.npz'),
        'conservation':'rain applied once; conservative surface withdrawal; native cumulative flooding returned in full; no physical external SWMM sink',
        'head_feedback':'wet surface stages update native junction surcharge depths',
        'maximum_sampling':'every coupling window, not every internal solver substep',
        'interpretation':'uncalibrated diagnostic; use only with configuration assumptions and data limitations'}
    dump(out/'run_receipt.json',receipt);dump(out/'water_balance_windows.json',records)
    progress('completed',args.duration,quality_passed=quality,receipt=receipt)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--scenario',choices=['L1','L2'],required=True)
    p.add_argument('--collection',default='results');p.add_argument('--duration',type=int,default=18000)
    p.add_argument('--step',type=int,default=30);p.add_argument('--threads',type=int,default=8)
    args=p.parse_args()
    if args.duration%300 or args.duration%args.step or 300%args.step:raise ValueError('duration and step must align with 300s output')
    run(args)
