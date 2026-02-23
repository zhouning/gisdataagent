import geopandas as gpd
import math
import warnings

# Suppress warnings about CRS mismatch if we create temporary buffers
warnings.filterwarnings("ignore", category=UserWarning)

def calculate_ffi_indicators(farmland_gdf_proj, A, N, LA_list, P_list):
    """
    Calculates the six raw indicators for Farmland Fragmentation Index (FFI).
    Optimized version using spatial index for AI calculation.

    Args:
        farmland_gdf_proj (gpd.GeoDataFrame): GeoDataFrame of farmland polygons (projected).
        A (float): Total farmland area.
        N (int): Total number of farmland patches.
        LA_list (list): List of individual patch areas.
        P_list (list): List of individual patch perimeters.

    Returns:
        dict: A dictionary containing the calculated indicator values.
    """
    indicators = {}

    # 1. NP (Number of Patches)
    indicators['NP'] = N

    if A == 0:
        return {k: 0.0 for k in ['NP', 'LPI', 'PD', 'LSI', 'AWMSI', 'AI']}

    # 2. LPI (Largest Patch Index)
    max_area = max(LA_list) if LA_list else 0.0
    indicators['LPI'] = (max_area / A) * 100

    # 3. PD (Patch Density)
    indicators['PD'] = N / A

    # 4. LSI (Landscape Shape Index)
    sum_P = sum(P_list)
    indicators['LSI'] = 0.25 * sum_P / (A**0.5) if A > 0 else 0.0

    # 5. AWMSI (Area-Weighted Mean Shape Index)
    weighted_si_sum = 0.0
    for i in range(N):
        a_i = LA_list[i]
        p_i = P_list[i]
        if a_i > 0:
            si_i = p_i / (2 * (math.pi * a_i)**0.5)
            weighted_si_sum += a_i * si_i
    indicators['AWMSI'] = weighted_si_sum / A

    # 6. AI (Aggregation Index) - Optimized Calculation
    try:
        # Create a spatial index-based adjacency search
        # Buffer slightly to ensure touching polygons are detected as intersecting
        # We use a very small buffer to catch shared boundaries
        buffered = farmland_gdf_proj.copy()
        # Use a small buffer to robustly detect touching neighbors
        # Note: If data is topologically perfect, 'touches' predicate works, 
        # but 'intersects' with small buffer is safer for real-world SHP data.
        buffered['geometry'] = buffered.geometry.buffer(1e-4) 
        
        # Self-join to find neighbors
        # reset_index is crucial to track original IDs
        buffered = buffered.reset_index(names=['orig_idx']) 
        joined = gpd.sjoin(buffered, buffered, how='inner', predicate='intersects')
        
        # Filter out self-intersections (where orig_idx_left == orig_idx_right)
        neighbors = joined[joined['orig_idx_left'] < joined['orig_idx_right']]
        
        total_shared_boundary_length = 0.0
        
        # Calculate shared boundary for identified pairs
        # We go back to original (unbuffered) geometries for accurate length
        geoms = farmland_gdf_proj.geometry.values
        
        # Iterate over unique neighbor pairs found by index
        for idx_left, idx_right in zip(neighbors['orig_idx_left'], neighbors['orig_idx_right']):
            geom1 = geoms[idx_left]
            geom2 = geoms[idx_right]
            
            if geom1.touches(geom2) or geom1.intersects(geom2):
                intersection = geom1.intersection(geom2)
                if intersection.geom_type in ['LineString', 'MultiLineString']:
                    total_shared_boundary_length += intersection.length
        
        sum_P_total = sum(P_list)
        if sum_P_total == 0:
            indicators['AI'] = 0.0
        else:
            # AI = (g_ii / max_g_ii) * 100, here approximated by shared_boundary / total_perimeter
            # Ideally AI uses a lattice model, for vector data, shared perimeter ratio is standard proxy
            indicators['AI'] = (total_shared_boundary_length / sum_P_total) * 100
            
    except Exception as e:
        print(f"Warning: Optimized AI calculation failed ({str(e)}). Falling back to 0.")
        indicators['AI'] = 0.0

    return indicators

def min_max_normalize(value, min_val, max_val, direction):
    """
    Normalizes an indicator value between 0 and 1.
    """
    if max_val == min_val:
        return 0.0

    normalized_value = (value - min_val) / (max_val - min_val)
    # Clip to [0, 1] range to avoid outliers breaking the index
    normalized_value = max(0.0, min(1.0, normalized_value))

    if direction == 'Negative':
        return 1 - normalized_value
    else:
        return normalized_value

def ffi(data_path: str) -> str:
    """
    计算耕地的破碎化指数（Farmland Fragmentation Index, FFI）。
    FFI是一种衡量耕地分布和连通性的重要指标。FFI值越高，表示耕地越分散和破碎。
    
    Args:
        data_path: 用于计算FFI的GIS数据路径。

    Returns:
        FFI的计算结果及各维度得分。
    """
    try:
        gdf = gpd.read_file(data_path)
        
        # Ensure DLMC exists (Case Insensitive Check)
        columns_lower = {c.lower(): c for c in gdf.columns}
        if 'dlmc' not in columns_lower:
            return f"Error: Input data missing 'DLMC' column. Available: {list(gdf.columns)}"
        
        dlmc_col = columns_lower['dlmc']
            
        gdf['Land_Use_Category'] = gdf[dlmc_col].apply(lambda x: '耕地' if x in ['旱地', '水田'] else x)
        farmland_gdf = gdf[gdf['Land_Use_Category'] == '耕地'].copy() # Use copy to avoid SettingWithCopy

        if farmland_gdf.empty:
            return "Warning: No farmland features found in dataset."

        # Ensure projected CRS
        if farmland_gdf.crs and farmland_gdf.crs.is_geographic:
            farmland_gdf = farmland_gdf.to_crs(epsg=3857)
        elif farmland_gdf.crs is None:
             # Assume projected if unknown, but warn? For now assume input is pre-processed by prev agent
             pass

        farmland_gdf['area'] = farmland_gdf.geometry.area
        farmland_gdf['perimeter'] = farmland_gdf.geometry.length

        A = farmland_gdf['area'].sum()
        N = len(farmland_gdf)
        LA_list = farmland_gdf['area'].tolist()
        P_list = farmland_gdf['perimeter'].tolist()

        # Weights
        W_PS, W_SR, W_SD = 0.21, 0.24, 0.55
        W_NP, W_LPI, W_PD = 0.667, 0.333, 0.167
        W_LSI, W_AWMSI = 0.333, 0.667
        W_AI = 0.833 # AI is main component of SD

        DIRECTIONS = {
            'NP': 'Positive', 'LPI': 'Negative', 'LSI': 'Positive',
            'AWMSI': 'Positive', 'PD': 'Positive', 'AI': 'Negative'
        }

        # Calculate Indicators
        ffi_indicators = calculate_ffi_indicators(farmland_gdf, A, N, LA_list, P_list)

        # Normalization Ranges (Based on empirical data or standards)
        min_max_ranges = {
            'NP': (1, max(25, N/100)), # Dynamic upper bound based on data size
            'LPI': (0, 100),
            'PD': (0, 0.1),
            'LSI': (1, 100),
            'AWMSI': (1, 10),
            'AI': (0, 100)
        }

        normalized_indicators = {}
        output_lines = ["### FFI 计算结果 (FFI Calculation Results)"]
        output_lines.append("| 指标 (Indicator) | 原始值 (Raw) | 归一化值 (Norm) |")
        output_lines.append("| :--- | :--- | :--- |")

        for name, raw_value in ffi_indicators.items():
            min_val, max_val = min_max_ranges[name]
            # Dynamic range adjustment
            if DIRECTIONS[name] == 'Positive':
                max_val = max(max_val, raw_value)
            
            norm_val = min_max_normalize(raw_value, min_val, max_val, DIRECTIONS[name])
            normalized_indicators[name] = norm_val
            output_lines.append(f"| {name} | {raw_value:.4f} | {norm_val:.4f} |")

        # Dimensional Scores
        ffi_ps = (normalized_indicators['LSI'] * W_LSI) + (normalized_indicators['AWMSI'] * W_AWMSI)
        ffi_sr = (normalized_indicators['NP'] * W_NP) + (normalized_indicators['LPI'] * W_LPI) + (normalized_indicators['PD'] * W_PD)
        ffi_sd = (normalized_indicators['AI'] * W_AI)

        # Final FFI
        FFI = (ffi_ps * W_PS) + (ffi_sr * W_SR) + (ffi_sd * W_SD)
        
        output_lines.append(f"\n**维度得分 (Dimensional Scores):**")
        output_lines.append(f"- 景观形状 (PS): {ffi_ps:.4f}")
        output_lines.append(f"- 分离度 (SR): {ffi_sr:.4f}")
        output_lines.append(f"- 空间离散度 (SD): {ffi_sd:.4f}")
        output_lines.append(f"\n### 最终 FFI 指数: **{FFI:.4f}**")

        return "\n".join(output_lines)
    except Exception as e:
        return f"Error calculating FFI: {str(e)}"
