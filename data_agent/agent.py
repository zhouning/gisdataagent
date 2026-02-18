from google.adk.agents.llm_agent import Agent
from google.adk.agents import LlmAgent, BaseAgent, SequentialAgent
from google.adk.tools import VertexAiSearchTool
from datetime import date
import geopandas as gpd
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.font_manager as fm
import seaborn as sns
import os
import math
import uuid
import folium
from folium import plugins
from pysal.explore import esda
from pysal.lib import weights
import contextily as cx
import yaml
from sb3_contrib import MaskablePPO

# Import modules
from . import drl_engine
from .FFI import ffi as calculate_ffi

# Load prompts from YAML file
PROMPTS_FILE = os.path.join(os.path.dirname(__file__), 'prompts.yaml')
with open(PROMPTS_FILE, 'r', encoding='utf-8') as f:
    prompts = yaml.safe_load(f)

def _configure_fonts():
    """Configure Matplotlib to use Chinese-compatible fonts based on OS."""
    import platform
    system = platform.system()
    font_names = []
    if system == 'Windows':
        font_names = ['SimHei', 'Microsoft YaHei', 'SimSun']
    elif system == 'Darwin':
        font_names = ['Arial Unicode MS', 'PingFang SC']
    else:
        font_names = ['WenQuanYi Micro Hei']
        
    available_fonts = set(f.name for f in fm.fontManager.ttflist)
    selected_font = next((f for f in font_names if f in available_fonts), None)
    if selected_font:
        plt.rcParams['font.sans-serif'] = [selected_font] + plt.rcParams['font.sans-serif']
        plt.rcParams['axes.unicode_minus'] = False
        print(f"Visualization font configured: {selected_font}")

def _generate_output_path(prefix: str, extension: str = "png") -> str:
    """Generates a unique output file path to avoid overwriting."""
    unique_id = uuid.uuid4().hex[:8]
    filename = f"{prefix}_{unique_id}.{extension}"
    return os.path.abspath(filename)

def _resolve_path(file_path: str) -> str:
    """Helper to resolve paths correctly."""
    if os.path.isabs(file_path): return file_path
    if os.path.exists(file_path): return os.path.abspath(file_path)
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), file_path))

def _load_spatial_data(file_path: str) -> gpd.GeoDataFrame:
    """
    Robustly loads spatial data from SHP, GeoJSON, or CSV.
    For CSV, auto-detects geometry columns (lon/lat, x/y).
    """
    path = _resolve_path(file_path)
    ext = os.path.splitext(path)[1].lower()
    
    if ext == '.csv':
        df = pd.read_csv(path)
        # Auto-detect geometry columns
        cols = [c.lower() for c in df.columns]
        x_col, y_col = None, None
        
        # Priority 1: lng/lat
        if 'lng' in cols and 'lat' in cols: x_col, y_col = df.columns[cols.index('lng')], df.columns[cols.index('lat')]
        elif 'lon' in cols and 'lat' in cols: x_col, y_col = df.columns[cols.index('lon')], df.columns[cols.index('lat')]
        elif 'longitude' in cols and 'latitude' in cols: x_col, y_col = df.columns[cols.index('longitude')], df.columns[cols.index('latitude')]
        # Priority 2: x/y (Projected)
        elif 'x' in cols and 'y' in cols: x_col, y_col = df.columns[cols.index('x')], df.columns[cols.index('y')]
        
        if x_col and y_col:
            gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df[x_col], df[y_col]))
            # Assume WGS84 for lat/lon, undefined for x/y (user must reproject)
            if 'lat' in y_col.lower(): gdf.set_crs(epsg=4326, inplace=True)
            return gdf
        else:
            raise ValueError("CSV must contain 'lat'/'lon' or 'x'/'y' columns to be spatialized.")
            
    else:
        # GeoJSON, SHP, GPKG, etc.
        return gpd.read_file(path)

def _plot_land_use_result(gdf, land_use_types, title, output_path):
    """Helper function for visualizing land use results."""
    _configure_fonts()
    OTHER, FARMLAND, FOREST = drl_engine.OTHER, drl_engine.FARMLAND, drl_engine.FOREST
    cmap = {OTHER: '#D3D3D3', FARMLAND: '#FFD700', FOREST: '#228B22'}
    gdf_plot = gdf.copy()
    gdf_plot['color'] = [cmap.get(t, '#333333') for t in land_use_types]
    fig, ax = plt.subplots(1, 1, figsize=(10, 10))
    gdf_plot.plot(ax=ax, color=gdf_plot['color'], edgecolor='none')
    ax.set_title(title, fontsize=15)
    ax.set_axis_off()
    patches = [mpatches.Patch(color='#FFD700', label='耕地'), mpatches.Patch(color='#228B22', label='林地'), mpatches.Patch(color='#D3D3D3', label='其他')]
    ax.legend(handles=patches, loc='lower right', fontsize=12)
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()

def drl_model(data_path: str) -> str:
    """使用深度强化学习模型进行布局优化。"""
    try:
        # Load data using standard loader (handles formatting)
        # Note: drl_engine expects a file path, so we ensure we pass a valid path.
        # If it's a CSV, engineer_spatial_features would have already converted it to SHP.
        res_data_path = _resolve_path(data_path)
        
        model_path = os.path.join(os.path.dirname(__file__), 'land_use_model_v2.zip')
        env = drl_engine.LandUseOptEnv(res_data_path, max_swaps=100)
        model = MaskablePPO.load(model_path)
        obs, info = env.reset()
        terminated, truncated = False, False
        while not (terminated or truncated):
            masks = env.action_masks()
            if not masks.any(): break
            action, _ = model.predict(obs, action_masks=masks, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(action)

        out_map = _generate_output_path("optimized_map")
        _plot_land_use_result(env.gdf, env.land_use, "基于 PPO v2 的耕地布局优化", out_map)
        
        # Use short field name 'Opt_Type' for Shapefile compatibility
        out_shp = _generate_output_path("optimized_data", "shp")
        gdf_out = env.gdf.copy()
        gdf_out['Opt_Type'] = env.land_use
        gdf_out.to_file(out_shp)
        
        summary = f"Optimization Complete.\nSwaps: {info.get('completed_swaps', 0)}\nResult SHP: {out_shp}\nVisualization: {out_map}"
        return {"output_path": out_map, "optimized_data_path": out_shp, "summary": summary}
    except Exception as e: return f"Error: {str(e)}"

def visualize_optimization_comparison(original_data_path: str, optimized_data_path: str) -> str:
    """生成优化前后对比图。"""
    try:
        _configure_fonts()
        # Use new loader
        gdf_orig = _load_spatial_data(original_data_path)
        gdf_opt = _load_spatial_data(optimized_data_path)
        
        OTHER, FARMLAND, FOREST = drl_engine.OTHER, drl_engine.FARMLAND, drl_engine.FOREST
        
        def map_dlmc(val):
            if val in {'旱地', '水田'}: return FARMLAND
            if val in {'果园', '有林地'}: return FOREST
            return OTHER
            
        initial = gdf_orig['DLMC'].apply(map_dlmc).values
        final = gdf_opt['Opt_Type'].values 
        
        cmap = {OTHER: '#D3D3D3', FARMLAND: '#FFD700', FOREST: '#228B22'}
        fig, axes = plt.subplots(1, 3, figsize=(26, 8))
        
        gdf_orig['c'] = [cmap[t] for t in initial]
        gdf_orig.plot(ax=axes[0], color=gdf_orig['c'], edgecolor='none')
        axes[0].set_title('优化前现状 (Before)', fontsize=16, fontweight='bold')
        axes[0].set_axis_off()
        
        gdf_opt['c'] = [cmap[t] for t in final]
        gdf_opt.plot(ax=axes[1], color=gdf_opt['c'], edgecolor='none')
        axes[1].set_title('优化后布局 (After)', fontsize=16, fontweight='bold')
        axes[1].set_axis_off()
        
        # Type Legend
        patches_type = [
            mpatches.Patch(color='#FFD700', label='耕地'),
            mpatches.Patch(color='#228B22', label='林地'),
            mpatches.Patch(color='#D3D3D3', label='其他'),
        ]
        axes[0].legend(handles=patches_type, loc='lower left', fontsize=11, title="用地类型")

        change = np.zeros(len(gdf_orig), dtype=np.int8)
        change[(initial == FARMLAND) & (final == FOREST)] = 1
        change[(initial == FOREST) & (final == FARMLAND)] = 2
        diff_colors = {0: '#F0F0F0', 1: '#FF4444', 2: '#4488FF'}
        gdf_orig['diff_c'] = [diff_colors[c] for c in change]
        gdf_orig.plot(ax=axes[2], color=gdf_orig['diff_c'], edgecolor='none')
        axes[2].set_title('空间置换差异图 (Swap Map)', fontsize=16, fontweight='bold')
        axes[2].set_axis_off()
        
        # Change Legend
        n_f2l = int((change == 1).sum())
        n_l2f = int((change == 2).sum())
        patches_diff = [
            mpatches.Patch(color='#F0F0F0', label='未变化'),
            mpatches.Patch(color='#FF4444', label=f'耕地 -> 林地 ({n_f2l}块)\n(退耕还林/坡度优化)'),
            mpatches.Patch(color='#4488FF', label=f'林地 -> 耕地 ({n_l2f}块)\n(宜耕资源开发)'),
        ]
        axes[2].legend(handles=patches_diff, loc='center left', bbox_to_anchor=(1, 0.5), fontsize=11, title="置换类型说明")
        
        out_path = _generate_output_path("comparison")
        plt.tight_layout()
        plt.savefig(out_path, dpi=300, bbox_inches='tight')
        plt.close()
        return f"Comparison visualization saved to {out_path}"
    except Exception as e: return f"Error: {str(e)}"

def visualize_interactive_map(original_data_path: str, optimized_data_path: str) -> str:
    """Generate multi-layer interactive map."""
    try:
        # Load and Reproject
        gdf_orig = _load_spatial_data(original_data_path).to_crs(epsg=4326)
        gdf_opt = _load_spatial_data(optimized_data_path).to_crs(epsg=4326)
        
        # Prepare Data for Logic
        OTHER, FARMLAND, FOREST = drl_engine.OTHER, drl_engine.FARMLAND, drl_engine.FOREST
        
        def map_dlmc(val):
            if val in {'旱地', '水田', '耕地'}: return FARMLAND
            if val in {'果园', '有林地', '林地'}: return FOREST
            return OTHER
            
        # Add integer type columns for styling
        gdf_orig['Type_Int'] = gdf_orig['DLMC'].apply(map_dlmc)
        gdf_opt['Type_Int'] = gdf_opt['Opt_Type'] 
        
        # Calculate Diff
        change_mask = np.zeros(len(gdf_orig), dtype=np.int8)
        initial = gdf_orig['Type_Int'].values
        final = gdf_opt['Type_Int'].values
        change_mask[(initial == FARMLAND) & (final == FOREST)] = 1 # Farm->Forest (Red)
        change_mask[(initial == FOREST) & (final == FARMLAND)] = 2 # Forest->Farm (Blue)
        
        gdf_diff = gdf_orig.copy()
        gdf_diff['Change_Type'] = change_mask
        # Filter diff layer
        gdf_diff = gdf_diff[gdf_diff['Change_Type'] > 0]
        
        # Setup Map
        center = [gdf_orig.geometry.centroid.y.mean(), gdf_orig.geometry.centroid.x.mean()]
        m = folium.Map(location=center, zoom_start=14, tiles='CartoDB positron')
        
        # Styles
        def style_type(feature):
            t = feature['properties']['Type_Int']
            color = '#808080' # Other
            if t == FARMLAND: color = '#FFD700' # Gold
            elif t == FOREST: color = '#228B22' # ForestGreen
            return {'fillColor': color, 'color': 'black', 'weight': 0.5, 'fillOpacity': 0.6}
            
        def style_diff(feature):
            c = feature['properties']['Change_Type']
            color = 'gray'
            if c == 1: color = '#FF4444' # Red
            elif c == 2: color = '#4488FF' # Blue
            return {'fillColor': color, 'color': color, 'weight': 1, 'fillOpacity': 0.8}

        # Tooltip fields
        tooltip_fields = ['DLMC', 'Slope', 'Shape_Area']

        # Layers
        folium.GeoJson(
            gdf_orig,
            name='优化前现状 (Before)',
            style_function=style_type,
            tooltip=folium.GeoJsonTooltip(fields=tooltip_fields, aliases=['地类:', '坡度:', '面积:']),
            show=False 
        ).add_to(m)
        
        folium.GeoJson(
            gdf_opt,
            name='优化后布局 (After)',
            style_function=style_type,
            tooltip=folium.GeoJsonTooltip(fields=['Opt_Type', 'Slope'], aliases=['优化类型(1耕2林):', '坡度:']),
            show=True 
        ).add_to(m)
        
        if not gdf_diff.empty:
            folium.GeoJson(
                gdf_diff,
                name='空间置换差异 (Changes)',
                style_function=style_diff,
                tooltip=folium.GeoJsonTooltip(fields=['DLMC', 'Slope', 'Change_Type'], 
                                             aliases=['原类型:', '坡度:', '变化(1退耕2开垦):']),
                show=True
            ).add_to(m)
            
        folium.LayerControl(collapsed=False).add_to(m)
        
        legend_html = '''
        <div style="position: fixed; bottom: 50px; left: 50px; z-index:9999; font-size:12px;
        background-color: white; padding: 10px; border: 1px solid grey; border-radius: 5px;">
        <b>图例说明</b><br>
        <i style="background:#FFD700;width:10px;height:10px;display:inline-block;margin-right:5px"></i>耕地<br>
        <i style="background:#228B22;width:10px;height:10px;display:inline-block;margin-right:5px"></i>林地<br>
        <br><b>变化差异层</b><br>
        <i style="background:#FF4444;width:10px;height:10px;display:inline-block;margin-right:5px"></i>退耕还林 (红)<br>
        <i style="background:#4488FF;width:10px;height:10px;display:inline-block;margin-right:5px"></i>宜耕开发 (蓝)
        </div>
        '''
        m.get_root().html.add_child(folium.Element(legend_html))
        
        output_path = _generate_output_path("interactive_comparison", "html")
        m.save(output_path)
        
        return f"Interactive comparison map saved to {output_path}"
        
    except Exception as e:
        return f"Error generating interactive map: {str(e)}"

def ffi(data_path: str) -> str:
    """计算破碎化指数。"""
    res_path = _resolve_path(data_path)
    # FFI module internally loads using geopandas, but we pass path.
    # Standardize input to SHP if it was CSV.
    return calculate_ffi(res_path) if os.path.exists(res_path) else f"Error: {res_path} not found"

def visualize_geodataframe(file_path: str) -> str:
    """可视化单份地理数据（静态）。"""
    try:
        _configure_fonts()
        # Use new loader
        gdf = _load_spatial_data(file_path)
        fig, ax = plt.subplots(1, 1, figsize=(10, 10))
        if 'DLMC' not in gdf.columns: gdf['DLMC'] = 'Unknown'
        colors = gdf['DLMC'].apply(lambda x: {'建制镇': '#87CEEB', '村庄': '#87CEEB', '旱地': '#F9FAE8', '水田': '#F9FAE8', '果园': '#FFC0CB', '有林地': '#228B22'}.get(x, '#FFFFFF'))
        gdf.plot(ax=ax, color=colors.tolist(), edgecolor='black', alpha=0.7)
        ax.set_title("土地利用现状图 (Land Use Map)", fontsize=15)
        ax.set_axis_off()
        out = _generate_output_path("visualization")
        plt.savefig(out, dpi=300)
        plt.close()
        return f"Visualization saved to {out}"
    except Exception as e: return f"Error: {str(e)}"

def describe_geodataframe(file_path: str) -> dict[str, any]:
    """数据探查画像。"""
    try:
        # Use new loader
        gdf = _load_spatial_data(file_path)
        recs, warns = [], []
        if not gdf.crs: warns.append("No CRS"); recs.append("Assign CRS")
        elif gdf.crs.is_geographic: warns.append("Geographic CRS"); recs.append("Reproject")
        
        summary = {
            "num_features": len(gdf), 
            "crs": str(gdf.crs), 
            "file_type": os.path.splitext(file_path)[1],
            "data_health": {"warnings": warns, "recommendations": recs, "ready_for_analysis": not warns}, 
            "file_path": _resolve_path(file_path)
        }
        return {"status": "success", "summary": summary}
    except Exception as e: return {"status": "error", "error_message": str(e)}

def reproject_spatial_data(file_path: str, target_crs: str = "EPSG:3857") -> str:
    """重投影。"""
    try:
        # Use new loader
        gdf = _load_spatial_data(file_path).to_crs(target_crs)
        out = _generate_output_path("reprojected", "shp")
        gdf.to_file(out); return out
    except Exception as e: return f"Error: {str(e)}"

def engineer_spatial_features(file_path: str) -> dict[str, any]:
    """特征工程。"""
    try:
        # Use new loader - this is where CSV gets converted to Geometry!
        gdf = _load_spatial_data(file_path)
        
        # Re-project for area/length calc
        gdf_calc = gdf.to_crs(epsg=3857) if gdf.crs and gdf.crs.is_geographic else gdf
        area = gdf_calc.geometry.area
        gdf['S_Idx'] = gdf_calc.geometry.length / (2 * np.sqrt(np.pi * area))
        gdf['CX'] = gdf_calc.geometry.centroid.x
        gdf['CY'] = gdf_calc.geometry.centroid.y
        
        # Output as SHP (Standardization Step)
        # This ensures downstream DRL model gets a Shapefile regardless of input CSV
        out = _generate_output_path("enhanced", "shp")
        gdf.to_file(out)
        
        return {"status": "success", "output_path": out, "message": "Standardized to SHP with features"}
    except Exception as e: return {"status": "error", "error_message": str(e)}

DATASTORE_ID = os.environ.get("DATASTORE_ID", "projects/gen-lang-client-0977577668/locations/global/collections/default_collection/dataStores/adktest20260101_1767273453936")

knowledge_agent = Agent(name="vertex_search_agent", model="gemini-2.5-flash", instruction=prompts['knowledge_agent_instruction'], description="Vertex AI Search 企业文档搜索助手", output_key="domain_knowledge", tools=[VertexAiSearchTool(data_store_id=DATASTORE_ID)])
data_exploration_agent=LlmAgent(name="DataExploration", instruction=prompts['data_exploration_agent_instruction'], description="数据探查专家", model="gemini-2.5-flash", output_key="data_profile", tools=[describe_geodataframe])
data_processing_agent=LlmAgent(name="DataProcessing", instruction=prompts['data_processing_agent_instruction'], description="特征工程与预处理专家", model="gemini-2.5-flash", output_key="processed_data", tools=[reproject_spatial_data, engineer_spatial_features])
data_engineering_agent=SequentialAgent(name="DataEngineering", sub_agents=[data_exploration_agent, data_processing_agent])
data_analysis_agent=LlmAgent(name="DataAnalysis", instruction=prompts['data_analysis_agent_instruction'], description="空间分析与优化专家", model="gemini-2.5-flash", output_key="analysis_report", tools=[ffi, drl_model])
data_visualization_agent=LlmAgent(name="DataVisualization", instruction=prompts['data_visualization_agent_instruction'], description="制图与可视化专家", model="gemini-2.5-flash", output_key="visualizations", tools=[visualize_geodataframe, visualize_optimization_comparison, visualize_interactive_map])
data_summary_agent=LlmAgent(name="DataSummary", instruction=prompts['data_summary_agent_instruction'], global_instruction=f"今天的时间是： {date.today()}", description="决策总结专家", model="gemini-2.5-flash", output_key="final_summary")
data_pipeline = SequentialAgent(name="DataPipeline", sub_agents=[knowledge_agent, data_engineering_agent, data_analysis_agent, data_visualization_agent, data_summary_agent])
root_agent = data_pipeline
