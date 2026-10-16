"""Export completed native runs to georeferenced 100m rasters and a report."""
from pathlib import Path
import hashlib,json,subprocess
import numpy as np,pandas as pd,rasterio
from affine import Affine
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from run_aam import HERE,dump

def main():
    config=json.loads((HERE/'prepared/configuration.json').read_text())
    results={};receipts={};hydros={}
    for s in ['L1','L2']:
        folder=HERE/'results'/s
        receipts[s]=json.loads((folder/'run_receipt.json').read_text())
        if receipts[s]['duration_seconds']!=18000:raise RuntimeError('not_a_complete_5h_run')
        results[s]=np.load(folder/'cell_results.npz')
        hydros[s]=pd.read_json(folder/'hydrograph.json');hydros[s].to_csv(folder/'hydrograph.csv',index=False)
    a=results['L1'];b=results['L2'];active=a['active_cells']
    assert np.array_equal(active,b['active_cells'])
    x,y=a['x'],a['y'];shape=(len(y)-1,len(x)-1)
    profile=dict(driver='GTiff',width=shape[1],height=shape[0],count=1,dtype='float32',
        crs='EPSG:32640',transform=Affine(100,0,float(x[0]),0,-100,float(y[0])),nodata=-9999.,
        compress='deflate',predictor=3,tiled=True,blockxsize=256,blockysize=256,BIGTIFF='IF_SAFER')
    def raster(path,values,description,times=None):
        values=np.atleast_2d(values);p=profile.copy();p['count']=len(values)
        with rasterio.open(path,'w',**p) as dst:
            for i,v in enumerate(values):
                full=np.full(shape,-9999.,dtype='float32');full.ravel()[active]=v
                dst.write(full,i+1)
                dst.set_band_description(i+1,f'{description}; t={times[i]}s' if times is not None else description)
                if times is not None:dst.update_tags(i+1,time_seconds=int(times[i]),time_minutes=float(times[i]/60))
            dst.update_tags(run_quality='passed' if all(r['quality_passed'] for r in receipts.values()) else 'FAILED: diagnostic only; consult run_receipt.json',
                interpretation='uncalibrated diagnostic physics simulation',units='m/s' if 'velocity' in description else 'm',grid_size_m=100)
    for s in ['L1','L2']:
        out=HERE/'results'/s;d=results[s]
        for key in ['maximum_depth_m','final_depth_m','maximum_velocity_mps']:
            raster(out/(key+'.tif'),d[key],key)
        frames=np.load(out/'depth_frames.npy',mmap_mode='r')
        raster(out/'depth_timeseries_5min.tif',frames,'depth_m',np.arange(len(frames))*300)
    comparison=HERE/'comparison';comparison.mkdir(exist_ok=True)
    delta=b['maximum_depth_m']-a['maximum_depth_m']
    finaldelta=b['final_depth_m']-a['final_depth_m']
    raster(comparison/'L2_minus_L1_maximum_depth_m.tif',delta,'L2 minus L1 maximum depth_m')
    raster(comparison/'L2_minus_L1_final_depth_m.tif',finaldelta,'L2 minus L1 final depth_m')
    metrics={'definition':'L2 minus L1; negative depth means less surface water in L2',
        'both_quality_passed':all(r['quality_passed'] for r in receipts.values()),
        'maximum_depth_reduction_m':float(-delta.min()),'maximum_depth_increase_m':float(delta.max()),
        'cells_reduced_ge_1mm':int((delta<=-.001).sum()),'cells_increased_ge_1mm':int((delta>=.001).sum()),
        'final_surface_volume_difference_m3':float(receipts['L2']['surface_final_volume_m3']-receipts['L1']['surface_final_volume_m3']),
        'pond_final_volume_m3':receipts['L2']['pond_final_volume_m3']}
    dump(comparison/'comparison_metrics.json',metrics)
    # Static review figures use raster pixels; no million-polygon GeoJSON.
    fig,axes=plt.subplots(1,3,figsize=(14,8),constrained_layout=True)
    images=[]
    for ax,s in zip(axes[:2],['L1','L2']):
        full=np.full(shape,np.nan);full.ravel()[active]=results[s]['maximum_depth_m']
        im=ax.imshow(full,extent=[x[0]/1000,x[-1]/1000,y[-1]/1000,y[0]/1000],vmin=0,vmax=1,cmap='Blues',interpolation='nearest')
        ax.set_title(f'{s} maximum surface depth');fig.colorbar(im,ax=ax,label='Depth (m); saturated at 1 m',shrink=.65)
    full=np.full(shape,np.nan);full.ravel()[active]=delta
    im=axes[2].imshow(full,extent=[x[0]/1000,x[-1]/1000,y[-1]/1000,y[0]/1000],cmap='RdBu_r',vmin=-.05,vmax=.05,interpolation='nearest')
    axes[2].set_title('L2 minus L1 maximum depth');fig.colorbar(im,ax=axes[2],label='Difference (m); saturated at +/- 0.05 m',shrink=.65)
    for ax in axes:ax.set_xlabel('Easting (km, UTM 40N)');ax.set_ylabel('Northing (km)')
    fig.suptitle('AAM / 100 m / 60 mm in 1 h + 4 h recession / uncalibrated diagnostic')
    fig.savefig(comparison/'AAM_L1_L2_depth_comparison.png',dpi=180);plt.close(fig)
    fig,axes=plt.subplots(2,1,figsize=(10,7),constrained_layout=True)
    for s in ['L1','L2']:
        h=hydros[s];axes[0].plot(h.time_seconds/3600,h.surface_storage_m3/1e6,label=s)
    axes[0].set(xlabel='Time (hours)',ylabel='Surface water (million m3)');axes[0].legend();axes[0].axvline(1,color='gray',ls='--')
    h=hydros['L2'];axes[1].plot(h.time_seconds/3600,h.pond_volume_m3,color='teal');axes[1].axhline(45000,color='gray',ls='--',label='Nominal capacity')
    axes[1].set(xlabel='Time (hours)',ylabel='L2 pond water (m3)');axes[1].legend()
    fig.savefig(comparison/'water_and_pond_hydrographs.png',dpi=180);plt.close(fig)
    quality='通过本次设置的数值检查' if metrics['both_quality_passed'] else '**未通过数值质量门控；以下为诊断计算，不应据此量化塘的减灾效果**'
    report=f'''# AAM 全行政区 L1/L2 一维—二维水动力计算报告

本次使用 EPA SWMM 5.2.4 计算管内水流，使用 ANUGA 求解二维地表浅水方程。实际完成两轮 18,000 秒计算，每轮前 1 小时均匀降雨 60mm/h，随后无雨退水 4 小时。结果{quality}。这两场计算没有训练或替代为世界模型。

## 1. 场景与范围

| 项目 | 本次设置 |
|---|---|
| 区域 | 69 个 AAM 行政区合并，全行政区；行政边界并非水文分水岭 |
| 格网 | EPSG:32640，100m，{len(active):,} 个有效像元，约 {len(active)*.01:,.2f} km² |
| 地形 | 客户 5m DTM 面积平均到 100m，再由邻格高程生成连续三角网顶点 |
| 真实求解精度 | 二维每 100m 像元分为两个有限体积三角形；没有宣称在原生 5m 网格求解 |
| L1 | 行政范围、DTM、现有排水管网，无显式塘库容 |
| L2 | 与 L1 相同，另将一个已确认相连的排口节点改为 45,000m³ 空塘 |
| 初始条件 | 地表、管网干，塘为空；求解器的极小初始湿润体积计入水量账 |
| 雨型 | 未核实到可用于 AAM 的一小时内雨型，使用已授权的均匀雨型 |
| 输出 | 每 5 分钟一帧，含初始时刻，共 61 帧；最大水深每耦合窗口更新 |

## 2. 为什么不开泵也能进塘

原始资产字段显示唯一相连管 SW_ASA_SAS_CNL_175402 为重力管：直径 1.4m，长约 84.42m，上游管底 197.199m，塘内排口管底 197.159m。上游水头高于塘水头时可以重力进水；水位升高后可能顶托乃至回流。没有证据证明进水必须依赖泵。两轮均使用这段管的原始高程，以避免把纠正该处高程的影响算成塘的作用。

塘底 194.0m，顶 200.8m，最大记录库容 45,000m³。由于实测水位—面积曲线缺失，以恒定等效面积 6,617.647m² × 6.8m 表示记录容量。这是容量约束的假设曲线，不是实测塘形。塘的原始平面面积约 11,700m²，不能直接乘 6.8m 后冒充记录容量。塘内原 DTM 没有真实塘底，因此库容单独放在 SWMM 中，满塘溢水回到地表，不凭空消失。

## 3. 数据与必要转换

完整参数、文件哈希及假设见 prepared/configuration.json，原生输入见 prepared/L1/model.inp 和 prepared/L2/model.inp。全部管线映射及排除记录见 prepared/link_mapping_and_adaptations.csv，节点映射见 prepared/node_mapping.csv。

采用毫米级端点坐标键，避免整米 PointCode 合并近邻节点形成自环；没有擅自连接未证实的管网断口。保留当前处理成果中的 DEM 推算高程、600mm 补值、逆坡和平坡。有效尺寸箱涵按矩形断面录入。短管按记录的数值设置适配，所有假设均与实测字段区分。

雨口采用等效开口参数，缺少实测过流曲线；管网糙率 0.013，地表糙率 0.035。缺少土壤率定资料，本轮下渗、蒸发、渗井能力均为零；不加入域外汇入。缺少单位明确的泵性能曲线和控制资料，未模拟主动泵送。其余水池与灌溉/供水设施未混入雨水模型。

## 4. 双向耦合和水量账

地表水经堰流/孔口流能力进入雨口；同一格中所有雨口共同使用该格实际可用水量，防止重复抽水。水量先从地表保守扣除，再通过原生 API 注入 SWMM。原生求解器逐步累计的节点溢水全部回注二维地表，湿地表水头反馈给节点。降雨只在二维加一次。

AAM 内排口是内部交换位置，不能视为无限外排损失。SWMM 为满足原生校验保留一个无连接、无来水的干占位排口，并逐窗口核实其流量为零。行政边界允许向外出流，不设海平面，不加入外部来水；实际净通量逐窗口记录。

| 数值指标 | L1 | L2 |
|---|---:|---:|
| SWMM 路由连续性误差 % | {receipts['L1']['swmm_routing_error_percent']:.6f} | {receipts['L2']['swmm_routing_error_percent']:.6f} |
| SWMM 未收敛步比例 % | {receipts['L1']['swmm_nonconverging_steps_percent']} | {receipts['L2']['swmm_nonconverging_steps_percent']} |
| 表面水量未通过窗口数 | {receipts['L1']['surface_failed_windows']} | {receipts['L2']['surface_failed_windows']} |
| 全系统残差占降雨 % | {receipts['L1']['whole_system_residual_percent_of_rain']:.6f} | {receipts['L2']['whole_system_residual_percent_of_rain']:.6f} |
| 期末地表水量 m³ | {receipts['L1']['surface_final_volume_m3']:,.3f} | {receipts['L2']['surface_final_volume_m3']:,.3f} |
| 期末管网水量（L2 含塘）m³ | {receipts['L1']['network_final_volume_m3']:,.3f} | {receipts['L2']['network_final_volume_m3']:,.3f} |

L2 期末塘内存水 {receipts['L2']['pond_final_volume_m3']:,.3f}m³。水深差图定义为 L2 减 L1，负数表示 L2 表面最大水深较小。该比较仅表示“补充现有塘资料”前后的模型差异，不能直接解释为新建工程效益。单格水深是 100m 范围的平均量，不能解读成具体道路或房屋内的精细水深。

## 5. 交付文件如何使用

- results/L1、results/L2：maximum_depth_m.tif 最大水深，final_depth_m.tif 5 小时期末水深，maximum_velocity_mps.tif 水深至少 1cm 时的格均流速最大值。
- depth_timeseries_5min.tif：61 波段，每波段带秒数标签，0 至 18,000 秒，每 300 秒一个波段；AAM 外 NoData=-9999。
- comparison：L2-L1 最大水深和期末水深差 GeoTIFF、对比图、水量与塘蓄水过程图。
- 每轮 run_receipt.json 为实际完成时间、输入哈希和质量结论；water_balance_windows.json 为逐窗口水量账；swmm.rpt 为原生报告。
- prepared：可复核的原生 INP、网格、节点/连接映射、参数及原始证据副本。smoke 与 native_probe 目录是诊断过程，不是最终 5 小时成果。

## 6. 适用范围

这是一组使用现有处理成果的未率定诊断模拟。它可以检查输入能否转换、模型能否运行以及增加一个空塘后的模型响应。管底多为 DEM 推算、部分管径补值、进水口能力和土壤资料不足，且 100m 地形平滑了道路/路缘/小洼地，故不能声称已得到工程实况、精确积水点或已验证防洪标准。详细数据问题沿用前期可行性评估，并在本次配置和映射中保留。
'''
    reportpath=HERE/'AAM_L1_L2_实际运行与结果说明.md';reportpath.write_text(report)
    subprocess.run(['pandoc',str(reportpath),'-o',str(reportpath.with_suffix('.docx'))],check=True)
    files=[]
    for folder in [HERE/'prepared',HERE/'results',HERE/'comparison']:
        for p in sorted(folder.rglob('*')):
            if p.is_file() and p.suffix in ['.tif','.inp','.json','.png','.csv','.npz']:
                h=hashlib.sha256()
                with p.open('rb') as f:
                    for chunk in iter(lambda:f.read(2**20),b''):h.update(chunk)
                files.append({'path':str(p.relative_to(HERE)),'bytes':p.stat().st_size,'sha256':h.hexdigest()})
    dump(HERE/'delivery_manifest.json',{'status':'completed','both_quality_passed':metrics['both_quality_passed'],'files':files})
    print(json.dumps(metrics,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
