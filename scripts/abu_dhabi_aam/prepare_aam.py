"""Compile the customer's AAM GIS into auditable SWMM and ANUGA inputs.
Run with gisdataagent/.venv/bin/python. Customer files remain unchanged.
"""
from pathlib import Path
import json, hashlib, shutil
import numpy as np
import pandas as pd
import pyogrio, rasterio, shapely
from scipy.ndimage import distance_transform_edt
from scipy.spatial import cKDTree

HERE=Path(__file__).resolve().parent
AUDIT=Path('/Users/zhouning/gisdataagent/.tmp/aam_feasibility_20261016')
GDB=AUDIT/'stormwater.gdb'
def dump(path,obj):
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(2**20),b''):h.update(b)
    return h.hexdigest()
def nums(d,c,default=np.nan):
    if c not in d:return np.full(len(d),default)
    return pd.to_numeric(d[c],errors='coerce').to_numpy(float)
def read(layer):return pyogrio.read_dataframe(GDB,layer=layer)

def main():
    out=HERE/'prepared';out.mkdir(exist_ok=True)
    # Preserve the existing 5m->100m area-average product, then interpolate
    # continuous vertices. Fill outside-mask neighbours only for the mesh bed;
    # the active mask remains exactly the AAM cell-centre mask.
    with rasterio.open(AUDIT/'aam_dtm_100m_preview.tif') as src:
        z=src.read(1).astype(float);mask=z!=src.nodata;tr=src.transform
    ny,nx=z.shape
    nearest=distance_transform_edt(~mask,return_distances=False,return_indices=True)
    z[~mask]=z[tuple(nearest[:,~mask])]
    pad=np.pad(z,1,mode='edge')
    vertex=(pad[:-1,:-1]+pad[1:,:-1]+pad[:-1,1:]+pad[1:,1:])/4
    x=tr.c+np.arange(nx+1)*100; y=tr.f-np.arange(ny+1)*100
    np.savez_compressed(out/'grid.npz',x=x,y=y,values=vertex,land_mask=mask,cell_mean_dtm=z)
    def gridcell(xy):
        col=np.floor((xy[:,0]-x[0])/100).astype(int)
        row=np.floor((y[0]-xy[:,1])/100).astype(int)
        valid=(col>=0)&(col<nx)&(row>=0)&(row<ny)
        cells=np.clip(row,0,ny-1)*nx+np.clip(col,0,nx-1)
        valid &= mask.ravel()[cells]
        return cells,valid
    frames=[]
    for layer in ['PIPELINE','BOXCULVERT','GRATEDCHANNELDRAINAGE']:
        f=read(layer);f['source_layer']=layer
        if layer=='GRATEDCHANNELDRAINAGE':
            f['Diameter']=600.
        frames.append(f)
    d=pd.concat(frames,ignore_index=True)
    xy1=d[['StartX','StartY']].to_numpy(float);xy2=d[['EndX','EndY']].to_numpy(float)
    endpoint=np.vstack([xy1,xy2]);nn=len(d)
    # One millimetre spatial keys retain the source's sub-metre connectivity.
    # They avoid the thousands of self-loops caused by integer PointCode.
    coords,inv=np.unique(np.round(endpoint,3),axis=0,return_inverse=True)
    a,b=inv[:nn],inv[nn:];n=len(coords)
    source_z=np.r_[nums(d,'StartElev'),nums(d,'EndElev')]
    # Keep processed elevations generally. The unique measured gravity inlet
    # to the pond has explicit surveyed pipe inverts; same override in L1/L2.
    pondpipe=np.flatnonzero(d.UNITID.eq('SW_ASA_SAS_CNL_175402').to_numpy())
    assert len(pondpipe)==1
    k=int(pondpipe[0]);source_z[k]=197.199;source_z[nn+k]=197.159
    floor=np.full(n,np.inf);np.minimum.at(floor,inv,source_z)
    floor-=.30  # keep the processed pipe-to-chamber sump allowance
    pondnode=int(b[k]);floor[pondnode]=197.159
    nodecell,inside=gridcell(coords)
    coarse=z.ravel()[nodecell]
    ground=np.full(n,-np.inf)
    inlet=np.zeros(n,bool);outfall=np.zeros(n,bool);asset_counts={};match_counts={}
    tree=cKDTree(coords)
    for layer in ['INLET','MANHOLECHAMBER','SW_NODE','SW_JUNCTION','OUTFALL','PS_PUMP','SOAKAWAY','CHAMBER','SW_CAPPEDEND','SW_VALVE']:
        points=read(layer);asset_counts[layer]=len(points)
        pxy=np.c_[shapely.get_x(points.geometry.values),shapely.get_y(points.geometry.values)]
        dist,idx=tree.query(pxy);ok=dist<=.02
        match_counts[layer]={'matched_within_2cm':int(ok.sum()),'unmatched':int((~ok).sum())}
        gz=nums(points,'GroundElev');valid=ok&np.isfinite(gz)
        np.maximum.at(ground,idx[valid],gz[valid])
        if layer=='INLET':inlet[idx[ok]]=True
        if layer=='OUTFALL':outfall[idx[ok]]=True
    # Missing chamber rims use the nearest supplied 5m endpoint sample.
    sampled=np.load(AUDIT/'pipe_endpoints_dtm5m.npy')
    endpoint_ground=np.full(n,-np.inf)
    np.maximum.at(endpoint_ground,inv[np.r_[np.arange(177318),nn+np.arange(177318)]],sampled)
    missing=~np.isfinite(ground)
    ground[missing]=np.where(np.isfinite(endpoint_ground[missing]),endpoint_ground[missing],coarse[missing])
    rim=np.maximum(ground,floor+.10)
    diameter=nums(d,'Diameter')/1000
    diameter=np.where(np.isfinite(diameter)&(diameter>0),diameter,.6)
    geom1=diameter.copy();geom2=np.zeros(nn);shape=np.full(nn,'CIRCULAR',dtype='<U12')
    box=d.source_layer.eq('BOXCULVERT').to_numpy();w=nums(d,'WIDTH')/1000;h=nums(d,'CULVERT_HIGHT')/1000
    validbox=box&np.isfinite(w)&np.isfinite(h)&(w>0)&(h>0)
    shape[validbox]='RECT_CLOSED';geom1[validbox]=h[validbox];geom2[validbox]=w[validbox]
    channel=d.source_layer.eq('GRATEDCHANNELDRAINAGE').to_numpy()
    shape[channel]='RECT_OPEN';geom1[channel]=nums(d,'CHANNEL_DEPTH')[channel];geom2[channel]=nums(d,'CHANNEL_WIDTH')[channel]
    # FullDepth must at least contain the largest connected conduit crown.
    crowns=np.full(n,-np.inf)
    np.maximum.at(crowns,a,source_z[:nn]+geom1);np.maximum.at(crowns,b,source_z[nn:]+geom1)
    native_rim=np.maximum(rim,crowns)
    lengths=nums(d,'LineLength');length=np.maximum(lengths,.10)
    selfloop=a==b;valid=(~selfloop)&np.isfinite(source_z[:nn])&np.isfinite(source_z[nn:])&np.isfinite(length)
    # Do not introduce fake pump Q-H curves or an unbounded soakaway sink.
    # Pressure lines remain passive closed conduits; no active pump is added.
    edits=pd.DataFrame({'source_layer':d.source_layer,'source_unitid':d.UNITID,'start_node':a,'end_node':b,
        'original_length_m':lengths,'native_length_m':length,'self_loop_after_1mm_key':selfloop,
        'included':valid,'native_shape':shape,'height_or_diameter_m':geom1,'width_m':geom2,
        'processed_start_invert_m':nums(d,'StartElev'),'native_start_invert_m':source_z[:nn],
        'processed_end_invert_m':nums(d,'EndElev'),'native_end_invert_m':source_z[nn:]})
    edits.to_csv(out/'link_mapping_and_adaptations.csv',index=False)
    pd.DataFrame({'native_node':np.arange(n),'x_m':coords[:,0],'y_m':coords[:,1],
        'invert_m':floor,'processed_rim_m':ground,'native_rim_m':native_rim,
        'inlet_capture':inlet,'physical_outfall_as_surface_exchange':outfall,
        'full_grid_cell':nodecell,'inside_active_grid':inside}).to_csv(out/'node_mapping.csv',index=False)
    # All real SWMM outfalls lie within AAM. They are interior junctions with
    # surface exchange, never external losses. One unconnected dry engine-only
    # outfall satisfies SWMM's syntax validator; it has no links or inflows.
    names=np.array([f'N{i:06d}' for i in range(n)])
    capture=(inlet|outfall)&inside
    opening=np.where(capture,.36,0.);width=4*np.sqrt(opening)
    for scenario in ['L1','L2']:
        folder=out/scenario;folder.mkdir(exist_ok=True)
        f=floor.copy();r=native_rim.copy();op=opening.copy();ww=width.copy()
        if scenario=='L2':f[pondnode]=194.;r[pondnode]=200.8;op[pondnode]=0.;ww[pondnode]=0.
        with (folder/'model.inp').open('w') as stream:
            def write(s):stream.write(s+'\n')
            write('[TITLE]\nAAM diagnostic coupled model; rain only on ANUGA surface; 100m; 60mm/1h + 4h recession')
            write('[OPTIONS]\nFLOW_UNITS CMS\nFLOW_ROUTING DYNWAVE\nLINK_OFFSETS DEPTH\nSTART_DATE 10/16/2026\nSTART_TIME 00:00:00\nREPORT_START_DATE 10/16/2026\nREPORT_START_TIME 00:00:00\nEND_DATE 10/16/2026\nEND_TIME 05:00:00\nREPORT_STEP 00:05:00\nWET_STEP 00:00:30\nDRY_STEP 00:00:30\nROUTING_STEP 5\nVARIABLE_STEP 0.75\nMINIMUM_STEP 0.05\nLENGTHENING_STEP 1\nMIN_SURFAREA 1.167\nMAX_TRIALS 20\nHEAD_TOLERANCE 0.005\nSURCHARGE_METHOD SLOT\nINERTIAL_DAMPING PARTIAL\nALLOW_PONDING NO\nSKIP_STEADY_STATE NO\nTHREADS 8')
            write('[JUNCTIONS]\n;; Name Invert MaxDepth InitDepth Surcharge PondedArea')
            for i in range(n):
                if scenario=='L2' and i==pondnode:continue
                write(f'{names[i]} {f[i]:.6f} {r[i]-f[i]:.6f} 0 0 0')
            write('[OUTFALLS]\nENGINE_DRY_SENTINEL 0 FREE NO')
            if scenario=='L2':write(f'[STORAGE]\n{names[pondnode]} 194 6.8 0 TABULAR POND_AREA 0 0\n[CURVES]\nPOND_AREA STORAGE 0 6617.64705882353\nPOND_AREA 6.8 6617.64705882353')
            write('[CONDUITS]\n;; Name From To Length Manning InOffset OutOffset InitFlow MaxFlow')
            for j in np.flatnonzero(valid):
                write(f'C{j:06d} {names[a[j]]} {names[b[j]]} {length[j]:.6f} 0.013 {max(0,source_z[j]-f[a[j]]):.6f} {max(0,source_z[nn+j]-f[b[j]]):.6f} 0 0')
            write('[XSECTIONS]')
            for j in np.flatnonzero(valid):write(f'C{j:06d} {shape[j]} {geom1[j]:.6f} {geom2[j]:.6f} 0 0 1')
            write('[REPORT]\nINPUT NO\nCONTROLS NO\nFLOWSTATS YES\nSUBCATCHMENTS NONE\nNODES ALL\nLINKS ALL')
            write('[COORDINATES]')
            for i in range(n):write(f'{names[i]} {coords[i,0]:.3f} {coords[i,1]:.3f}')
            write('ENGINE_DRY_SENTINEL 0 0')
        # The native node order differs in L2 (storage follows junctions and
        # outfalls), so run-time indices must be resolved from these names.
        np.savez_compressed(folder/'interfaces.npz',names=names,full_cells=nodecell,
            inside=inside,rim_m=r,opening_area_m2=op,crest_width_m=ww,
            pond_logical_index=np.array(pondnode),xy=coords)
    config={'schema':'aam.native_coupled.v1','domain':'union of all 69 AAM administrative districts',
        'crs':'EPSG:32640','grid_spacing_m':100,'source_dtm_spacing_m':5,'grid_columns':nx,'grid_rows':ny,
        'active_cells':int(mask.sum()),'grid_area_m2':int(mask.sum())*10000,
        'grid_mask':'cell centres within administrative union; boundary pixelisation at 100m',
        'bed_method':'5m DTM area-mean to 100m; adjacent-cell means interpolated to continuous mesh vertices',
        'rainfall':{'method':'uniform; no verified Al Ain within-hour temporal distribution available',
                    'rate_mm_per_hour':60,'rain_duration_seconds':3600,'recession_seconds':14400,
                    'total_duration_seconds':18000,'total_depth_mm':60,'applied_once':'ANUGA surface only'},
        'initial_conditions':'dry surface and pipes; L2 pond empty',
        'surface_manning_n':.035,'pipe_manning_n':.013,'inlet_opening_area_m2':.36,'inlet_cd':.61,
        'inlet_assumption':'one equivalent 0.36m2 opening per spatially matched inlet/outfall node; no surveyed grate-rating curves',
        'infiltration':'zero, no calibrated soil or soakaway capacity supplied','evaporation':'zero',
        'external_inflow':'none; administrative boundary is not a hydrological catchment divide',
        'lateral_boundary':'outward-only transmissive: extrapolate state, remove inward normal velocity; no imposed sea stage',
        'physical_outfalls':'inside domain; represented as junction/surface interfaces, all overflow returns to 2D',
        'engine_only_outfall':'one isolated, unconnected dry sentinel, zero inflow; required by SWMM validator, no physical drainage',
        'pumps':'no active pumping; capacity units, Q-H curves and controls absent; passive pressure lines retained',
        'pond':{'logical_node':pondnode,'node_name':str(names[pondnode]),'x_m':349606.193314,'y_m':2677365.143906,
                'storage_location':'existing connected pipe endpoint, within pond footprint','bottom_m':194,'crest_m':200.8,
                'capacity_m3':45000,'equivalent_area_m2':45000/6.8,'curve':'constant equivalent area constrained by total capacity; actual stage-area survey unavailable',
                'surface_connection':'pipe-only inflow; full-pond overflow returned to its surface cell; no invented pump or surface inlet',
                'rain':'rain applied to unchanged footprint cells in both scenarios; no separate pond rainfall',
                'gravity_pipe':'SW_ASA_SAS_CNL_175402','pipe_diameter_m':1.4,
                'pipe_upstream_invert_m':197.199,'pipe_downstream_invert_m':197.159,
                'shared_baseline_local_override':'these two surveyed inverts used in BOTH scenarios instead of DEM-calculated inversions'},
        'network':{'source_pipelines':177318,'source_boxculverts':487,'source_grated_channels':2,
                   'native_links':int(valid.sum()),'native_nodes_without_sentinel':n,
                   'excluded_self_loops_1mm':int(selfloop.sum()),'lengths_raised_to_0_1m':int((lengths<.1).sum()),
                   'boxculverts_with_native_rectangular_dimensions':int(validbox.sum()),'boxculverts_assumed_0_6m_circular_missing_dimensions':int((box&~validbox).sum()),
                   'node_connectivity':'1mm endpoint spatial keys; no integer-metre PointCode; no unverified gap snapping',
                   'native_rims_raised_to_conduit_crown':int((crowns>rim+1e-6).sum()),
                   'point_inventory':asset_counts,'point_matches':match_counts,
                   'active_inlet_or_outfall_nodes':int(capture.sum()),'outside_active_grid_nodes':int((~inside).sum())},
        'quality_scope':'uncalibrated diagnostic physics runs with processed elevations and infilled diameters; not an engineering risk certification',
        'sources':json.loads((AUDIT/'source_archives.json').read_text()),
        'grid_sha256':sha(out/'grid.npz'),
        'model_sha256':{s:sha(out/s/'model.inp') for s in ['L1','L2']}}
    dump(out/'configuration.json',config)
    for f in ['aam_boundary.gpkg','aam_pond.gpkg','dtm_coverage.json','pond_dtm_check.json','pond_connected_nodes.json','source_archives.json']:
        shutil.copy2(AUDIT/f,out/f)
    pd.DataFrame({'start_seconds':[0,3600],'end_seconds':[3600,18000],'intensity_mm_per_hour':[60,0]}).to_csv(HERE/'rainfall_sources'/'rainfall.csv',index=False)
    print(json.dumps(config['network'],ensure_ascii=False),flush=True)

if __name__=='__main__':main()
