"""Copy and checksum the actual native output bytes. No raster conversion."""
from pathlib import Path
import datetime,hashlib,json,shutil,struct,zipfile
import numpy as np
from netCDF4 import Dataset
HERE=Path(__file__).resolve().parent
dest=HERE/'原生计算结果_可拷贝'
dest.mkdir(exist_ok=True)
files=[];runs={};validation={}
for scenario in ['L1','L2']:
    source=HERE/'results'/scenario
    receipt=json.loads((source/'run_receipt.json').read_text())
    if receipt.get('duration_seconds')!=18000:raise RuntimeError('incomplete simulation')
    runs[scenario]=receipt
    out=source/f'AAM_{scenario}_1D.out'
    with out.open('rb') as f:
        header=struct.unpack('<7i',f.read(28));f.seek(-24,2);footer=struct.unpack('<6i',f.read(24))
    if header[0]!=516114522 or footer[-1]!=516114522 or footer[-2]!=0:raise RuntimeError('invalid or unfinished SWMM binary')
    if header[1]!=52004 or header[4]!=191737 or header[5]!=177802 or footer[3]!=60:raise RuntimeError(f'native output dimensions/periods unexpected: {header}, {footer}')
    sww=source/f'AAM_{scenario}_2D.sww'
    with Dataset(sww) as ds:
        times=np.asarray(ds.variables['time'][:]);names=list(ds.variables)
        if len(times)!=61 or not np.allclose(times,np.arange(61)*300):raise RuntimeError('incomplete SWW time sequence')
        for variable in ['volumes','x','y','elevation','stage','xmomentum','ymomentum','elevation_c','stage_c','xmomentum_c','ymomentum_c']:
            if variable not in names:raise RuntimeError('missing native variable '+variable)
        if ds.variables['volumes'].shape[0]!=2688898:raise RuntimeError('wrong SWW mesh')
        validation[scenario]={'swmm_version':header[1],'swmm_nodes':header[4],'swmm_links':header[5],
            'swmm_periods':footer[3],'swmm_error_code':footer[-2],'sww_timesteps':len(times),
            'sww_first_time_s':float(times[0]),'sww_last_time_s':float(times[-1]),
            'sww_native_variables':names,'sww_data_model':ds.data_model,
            'quality_passed':receipt['quality_passed']}
    folder=dest/scenario;folder.mkdir(exist_ok=True)
    pairs=[(out,folder/out.name),(sww,folder/sww.name),
        (source/f'AAM_{scenario}_1D.rpt',folder/f'AAM_{scenario}_1D.rpt'),
        (HERE/'prepared'/scenario/'model.inp',folder/f'AAM_{scenario}_1D.inp'),
        (source/'run_receipt.json',folder/'run_receipt.json'),
        (source/'water_balance_windows.json',folder/'water_balance_windows.json')]
    for original,target in pairs:
        shutil.copy2(original,target)
        a=hashlib.sha256();b=hashlib.sha256()
        with original.open('rb') as f:
            for chunk in iter(lambda:f.read(4*1024**2),b''):a.update(chunk)
        with target.open('rb') as f:
            for chunk in iter(lambda:f.read(4*1024**2),b''):b.update(chunk)
        if a.digest()!=b.digest():raise RuntimeError('copy checksum mismatch')
        files.append({'path':str(target.relative_to(dest)),'bytes':target.stat().st_size,'sha256':a.hexdigest()})
mapping=dest/'配套参数与标识';mapping.mkdir(exist_ok=True)
for name in ['configuration.json','node_mapping.csv','link_mapping_and_adaptations.csv','grid.npz','aam_boundary.gpkg','aam_pond.gpkg']:
    shutil.copy2(HERE/'prepared'/name,mapping/name)
readme='''AAM 一维—二维水动力模型原生计算结果

L1：AAM 全行政区 + 既有排水管网 + 客户 5m DTM（100m 计算网格）。
L2：同一基线 + 一个初始为空的已确认雨水塘。
模拟过程：前 1 小时均匀降雨 60mm/h；随后 4 小时无雨，总时长 5 小时。

L1、L2 文件夹中：
1. AAM_Lx_1D.out：EPA SWMM 5.2.4 原生二进制结果。节点、管段全量输出，每 300 秒一帧，共 60 帧（300 至 18000 秒）。
2. AAM_Lx_1D.rpt：同轮 SWMM 原生文本报告。
3. AAM_Lx_2D.sww：ANUGA 原生 SWW/NetCDF 文件，含 61 帧（0 至 18000 秒，每 300 秒）。包含原生三角网连接、坐标、底床高程、水位和两个方向动量；*_c 为求解器原生单元中心量。
4. AAM_Lx_1D.inp：配套一维原生输入，保留节点/管段标识。降雨与双向交换由外部耦合驱动施加，单独重跑该 INP 不会复现本次耦合事件。
5. run_receipt.json 和 water_balance_windows.json：实际运行与质量记录。数值不达标也保留原生结果，不能将“文件完整”误读成“物理精度已验证”。

结果文件均为求解器直接写出，复制时逐文件核对 SHA-256；没有将 GeoTIFF、图片或插值结果冒充原生计算结果。

坐标：EPSG:32640（WGS84 / UTM 40N），水平与高程单位米；SWMM 流量单位 CMS（m³/s）。SWW 的 x、y 是局部坐标，绝对位置按文件内 xllcorner、yllcorner、zone、hemisphere 属性恢复。
二维网格：每个有效 100m 方格分为两个有限体积三角形，共 2,688,898 个三角形。配套 grid.npz 有全域 100m 方格掩膜及坐标轴；按掩膜的行优先有效方格顺序，每相邻两个三角形对应一个 100m 方格。
二维水深可由原生单元中心 stage_c 减 elevation_c 得到；原生动量除以水深可计算速度，干单元须作零水深处理。

读取：.out 使用兼容 EPA SWMM 5.2.4 的结果读取工具；.sww 使用 ANUGA 或支持 NetCDF 的工具，按原生网格结构读取。文件拷贝到其他电脑后，不依赖本机绝对路径即可读取。
'''
(dest/'请先阅读_原生结果说明.txt').write_text(readme)
manifest={'schema':'aam.native_handoff.v1','created_at':datetime.datetime.now().astimezone().isoformat(),
    'native_files_preserved_byte_for_byte':True,'both_quality_passed':all(r['quality_passed'] for r in runs.values()),
    'validation':validation,'files':files}
(dest/'原生文件完整性与质量.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
zip_path=HERE/'AAM_L1_L2_原生计算结果_100m_60mm1h_退水4h.zip'
temp=zip_path.with_suffix('.zip.partial')
with zipfile.ZipFile(temp,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as archive:
    for path in sorted(dest.rglob('*')):
        if path.is_file():archive.write(path,str(Path(dest.name)/path.relative_to(dest)))
temp.replace(zip_path)
print(json.dumps({'status':'completed','native_package':str(zip_path),'uncompressed_folder':str(dest),
    'bytes':zip_path.stat().st_size,'both_quality_passed':manifest['both_quality_passed']},ensure_ascii=False),flush=True)
