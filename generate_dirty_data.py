import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon, Point, box
import os

def generate():
    print("正在生成用于演示的政务‘脏数据’...")
    
    # 1. 制造拓扑重叠 (Overlaps)
    # 地块 A 和 地块 B 故意重叠一部分
    poly_a = box(104.0, 30.0, 104.1, 30.1) # 104E, 30N
    poly_b = box(104.05, 30.0, 104.15, 30.1) # 故意重叠 50%
    poly_c = box(104.15, 30.0, 104.25, 30.1) # 正常邻接
    
    geoms = [poly_a, poly_b, poly_c]
    
    # 2. 制造非法字段值 (Invalid Values)
    # 标准应该是 ['水田', '旱地', '果园']
    # 我们塞入 '违章建筑' 和 '待定'
    data = {
        'GRID_ID': ['G001', 'G002', 'G003'],
        'DLMC': ['水田', '违章建筑', '待定'], # 包含违规值
        'Slope': [5.2, 28.5, 12.0],
        'Shape_Area': [1000.0, 1200.0, 800.0]
    }
    
    # 3. 设置非标坐标系 (Non-standard CRS)
    # 故意设为 EPSG:4326，而不是国标 4490
    gdf = gpd.GeoDataFrame(data, geometry=geoms, crs="EPSG:4326")
    
    # 4. 保存文件
    output_path = os.path.abspath("政务数据汇交样本_待治理.shp")
    gdf.to_file(output_path, encoding='utf-8')
    
    print(f"✅ 生成成功！")
    print(f"路径: {output_path}")
    print(f"包含缺陷:")
    print(f"  - [空间] 存在 1 处地块重叠 (G001 与 G002)")
    print(f"  - [语义] DLMC 字段包含非法值: '违章建筑', '待定'")
    print(f"  - [坐标] 当前为 WGS84 (EPSG:4326)，不符合国标 CGCS2000")

if __name__ == "__main__":
    generate()
