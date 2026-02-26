import geopandas as gpd
import numpy as np
import os
import random
from shapely.geometry import Polygon

def generate_realistic_dirty_data():
    source_path = "斑竹村10000.shp"
    output_path = "斑竹村_治理演示样本.shp"
    
    if not os.path.exists(source_path):
        print(f"错误: 找不到源文件 {source_path}")
        return

    print(f"正在读取源数据: {source_path}...")
    gdf = gpd.read_file(source_path)
    
    # 为了演示流畅，只取前 200 个图斑
    # 这样既保留了真实的空间格局，又不会让计算太慢
    sample_gdf = gdf.head(200).copy()
    print(f"提取前 {len(sample_gdf)} 个图斑进行处理...")

    # ==========================================
    # 1. 制造拓扑重叠 (Artificial Overlaps)
    # ==========================================
    # 随机选择 3 个图斑，使其向外膨胀 2 米
    # 这会模拟数字化过程中常见的"压盖"错误
    indices_to_overlap = np.random.choice(sample_gdf.index, size=3, replace=False)
    print(f"正在制造拓扑重叠错误 (图斑索引: {indices_to_overlap})...")
    
    for idx in indices_to_overlap:
        original_geom = sample_gdf.geometry.loc[idx]
        # 缓冲 5 单位 (米)
        buffered_geom = original_geom.buffer(5.0) 
        sample_gdf.at[idx, 'geometry'] = buffered_geom
        
        # 标记一下，方便演示时核对
        sample_gdf.at[idx, 'Note'] = '人工制造重叠'

    # ==========================================
    # 2. 制造属性违规 (Invalid Attributes)
    # ==========================================
    # 国标通常是 ['水田', '旱地', '果园', '有林地']
    # 插入一些典型的非标值
    invalid_values = ['待确认', '批而未供', '违章占地', '荒草地(非标)']
    indices_to_corrupt = np.random.choice(sample_gdf.index, size=5, replace=False)
    print(f"正在制造属性合规错误 (图斑索引: {indices_to_corrupt})...")
    
    for i, idx in enumerate(indices_to_corrupt):
        bad_val = invalid_values[i % len(invalid_values)]
        sample_gdf.at[idx, 'DLMC'] = bad_val

    # ==========================================
    # 3. 篡改坐标系 (CRS Tampering)
    # ==========================================
    # 很多汇交数据最大的问题就是坐标系是 WGS84 而不是 CGCS2000
    print("正在篡改坐标系为 EPSG:4326 (WGS84)...")
    if sample_gdf.crs:
        sample_gdf = sample_gdf.to_crs(epsg=4326)
    else:
        sample_gdf.set_crs(epsg=4326, inplace=True)

    # ==========================================
    # 4. 保存结果
    # ==========================================
    output_abs_path = os.path.abspath(output_path)
    # 解决中文路径/编码问题
    sample_gdf.to_file(output_abs_path, encoding='utf-8')
    
    print("\n" + "="*50)
    print(f"✅ 逼真演示数据已生成: {output_abs_path}")
    print("="*50)
    print("包含以下治理挑战:")
    print("1. [空间错误] 存在 3 处真实的边界重叠 (模拟数字化误差)")
    print("2. [数据合规] 存在 5 处非法地类值 (如 '待确认', '违章占地')")
    print("3. [坐标合规] 坐标系已被篡改为 WGS84 (需转为 CGCS2000/WebMercator)")
    print("="*50)

if __name__ == "__main__":
    generate_realistic_dirty_data()
