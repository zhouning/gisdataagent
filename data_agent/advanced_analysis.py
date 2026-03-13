"""Advanced analysis tools: spatiotemporal forecast, scenario simulation, network analysis.

Uses statsmodels (ARIMA/ETS), networkx (centrality/community), scipy/sklearn (accessibility).
All dependencies are already in requirements.txt — zero new packages.
"""
import json
import logging
import os
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .gis_processors import _generate_output_path, _resolve_path
from .utils import _load_spatial_data, _configure_fonts

logger = logging.getLogger(__name__)


def _load_data(path):
    """Load data as GeoDataFrame if spatial, else as plain DataFrame.

    Falls back to pd.read_csv / pd.read_excel when _load_spatial_data
    fails (e.g. CSV without coordinate columns).
    """
    try:
        return _load_spatial_data(path)
    except Exception:
        ext = os.path.splitext(path)[1].lower()
        if ext == ".csv":
            return pd.read_csv(path, encoding="utf-8-sig")
        elif ext in (".xls", ".xlsx"):
            return pd.read_excel(path)
        raise


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_spatial_graph(gdf, weight_col=None):
    """Build networkx Graph from GeoDataFrame.

    For polygon geometries: queen contiguity (shared boundary).
    For line geometries: endpoint connectivity.
    For point geometries: Delaunay triangulation.
    """
    import networkx as nx

    G = nx.Graph()
    if len(gdf) == 0:
        return G

    geom_type = gdf.geometry.iloc[0].geom_type

    if geom_type in ("Polygon", "MultiPolygon"):
        # Queen contiguity — polygons sharing boundary
        from libpysal.weights import Queen
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            gdf_work = gdf.copy()
            if gdf_work.crs and gdf_work.crs.is_geographic:
                gdf_work = gdf_work.to_crs(epsg=3857)
            w = Queen.from_dataframe(gdf_work, use_index=False)
        for i in range(len(gdf)):
            G.add_node(i)
        for i, neighbors in w.neighbors.items():
            for j in neighbors:
                wt = 1.0
                if weight_col and weight_col in gdf.columns:
                    wt = float(gdf.iloc[i][weight_col] + gdf.iloc[j][weight_col]) / 2
                G.add_edge(i, j, weight=wt)

    elif geom_type in ("LineString", "MultiLineString"):
        # Endpoint connectivity
        from shapely.ops import nearest_points
        coords_map = {}
        for i, geom in enumerate(gdf.geometry):
            G.add_node(i)
            if geom.geom_type == "MultiLineString":
                for line in geom.geoms:
                    for pt in [line.coords[0], line.coords[-1]]:
                        key = (round(pt[0], 6), round(pt[1], 6))
                        coords_map.setdefault(key, []).append(i)
            else:
                for pt in [geom.coords[0], geom.coords[-1]]:
                    key = (round(pt[0], 6), round(pt[1], 6))
                    coords_map.setdefault(key, []).append(i)
        for key, indices in coords_map.items():
            for a in indices:
                for b in indices:
                    if a < b:
                        wt = 1.0
                        if weight_col and weight_col in gdf.columns:
                            wt = float(gdf.iloc[a][weight_col] + gdf.iloc[b][weight_col]) / 2
                        G.add_edge(a, b, weight=wt)

    else:
        # Point — Delaunay triangulation
        from scipy.spatial import Delaunay
        coords = np.array([(g.x, g.y) for g in gdf.geometry])
        for i in range(len(gdf)):
            G.add_node(i)
        if len(coords) >= 3:
            tri = Delaunay(coords)
            for simplex in tri.simplices:
                for a_idx in range(3):
                    for b_idx in range(a_idx + 1, 3):
                        a, b = int(simplex[a_idx]), int(simplex[b_idx])
                        wt = 1.0
                        if weight_col and weight_col in gdf.columns:
                            wt = float(gdf.iloc[a][weight_col] + gdf.iloc[b][weight_col]) / 2
                        G.add_edge(a, b, weight=wt)

    return G


def _auto_select_arima(series):
    """Auto-select ARIMA order (p,d,q) via AIC grid search.

    Searches a small grid: p in [0..2], d in [0..1], q in [0..2].
    Returns the (p,d,q) with the lowest AIC.
    """
    from statsmodels.tsa.arima.model import ARIMA

    best_aic = float("inf")
    best_order = (1, 0, 0)

    for p in range(3):
        for d in range(2):
            for q in range(3):
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        model = ARIMA(series, order=(p, d, q))
                        result = model.fit()
                        if result.aic < best_aic:
                            best_aic = result.aic
                            best_order = (p, d, q)
                except Exception:
                    continue

    return best_order


def _plot_forecast(series, forecast_values, conf_int, title, output_path):
    """Plot time series with forecast and confidence interval band."""
    _configure_fonts()
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(range(len(series)), series.values, label="历史数据", color="#2196F3")
    fc_x = range(len(series), len(series) + len(forecast_values))
    ax.plot(fc_x, forecast_values, label="预测", color="#FF5722", linestyle="--")
    if conf_int is not None and len(conf_int) == 2:
        ax.fill_between(fc_x, conf_int[0], conf_int[1], alpha=0.2, color="#FF5722", label="置信区间")
    ax.set_title(title, fontsize=13)
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close()


# ---------------------------------------------------------------------------
# Category 1: Spatiotemporal
# ---------------------------------------------------------------------------

def time_series_forecast(
    data_path: str,
    time_col: str,
    value_col: str,
    periods: int = 12,
    method: str = "auto",
) -> str:
    """时间序列预测（ARIMA/ETS），输出预测值、置信区间和趋势图。

    对时序数据进行建模，预测未来若干期的数值变化趋势。
    支持自动模型选择、ARIMA 和指数平滑（ETS）三种方法。

    Args:
        data_path: 数据文件路径（CSV/Excel/GeoJSON 等）。
        time_col: 时间列名（将被解析为日期时间索引）。
        value_col: 数值列名（待预测的目标变量）。
        periods: 预测期数（默认 12）。
        method: 预测方法。"auto"（自动选择最优 ARIMA）、"arima"（默认 ARIMA(1,1,1)）、"ets"（指数平滑）。

    Returns:
        包含预测结果 CSV 路径、趋势图 PNG 路径和摘要统计的字典。
    """
    try:
        res_path = _resolve_path(data_path)
        df = _load_data(res_path)

        if time_col not in df.columns:
            return f"Error: time column '{time_col}' not found. Available: {list(df.columns)}"
        if value_col not in df.columns:
            return f"Error: value column '{value_col}' not found. Available: {list(df.columns)}"

        df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
        df = df.dropna(subset=[time_col, value_col]).sort_values(time_col)
        series = df.set_index(time_col)[value_col].astype(float)

        if len(series) < 5:
            return "Error: need at least 5 data points for time series forecast."

        method = method.lower()
        forecast_values = None
        conf_lower = None
        conf_upper = None
        model_desc = ""

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")

            if method == "ets":
                from statsmodels.tsa.holtwinters import ExponentialSmoothing
                model = ExponentialSmoothing(
                    series, trend="add", seasonal=None,
                    initialization_method="estimated",
                )
                result = model.fit(optimized=True)
                fc = result.forecast(periods)
                forecast_values = fc.values
                model_desc = "Exponential Smoothing (ETS, additive trend)"

            elif method == "arima":
                from statsmodels.tsa.arima.model import ARIMA
                model = ARIMA(series, order=(1, 1, 1))
                result = model.fit()
                fc = result.get_forecast(periods)
                forecast_values = fc.predicted_mean.values
                ci = fc.conf_int()
                conf_lower = ci.iloc[:, 0].values
                conf_upper = ci.iloc[:, 1].values
                model_desc = "ARIMA(1,1,1)"

            else:  # auto
                from statsmodels.tsa.arima.model import ARIMA
                order = _auto_select_arima(series)
                model = ARIMA(series, order=order)
                result = model.fit()
                fc = result.get_forecast(periods)
                forecast_values = fc.predicted_mean.values
                ci = fc.conf_int()
                conf_lower = ci.iloc[:, 0].values
                conf_upper = ci.iloc[:, 1].values
                model_desc = f"Auto-ARIMA{order}"

        # Build output CSV
        fc_df = pd.DataFrame({
            "period": list(range(1, periods + 1)),
            "forecast": np.round(forecast_values, 4),
        })
        if conf_lower is not None:
            fc_df["ci_lower"] = np.round(conf_lower, 4)
            fc_df["ci_upper"] = np.round(conf_upper, 4)

        csv_path = _generate_output_path("forecast", "csv")
        fc_df.to_csv(csv_path, index=False, encoding="utf-8-sig")

        # Plot
        plot_path = _generate_output_path("forecast_plot", "png")
        ci_for_plot = (conf_lower, conf_upper) if conf_lower is not None else None
        _plot_forecast(series, forecast_values, ci_for_plot, f"时间序列预测 ({model_desc})", plot_path)

        summary = {
            "model": model_desc,
            "history_points": len(series),
            "forecast_periods": periods,
            "last_value": round(float(series.iloc[-1]), 4),
            "mean_forecast": round(float(np.mean(forecast_values)), 4),
        }

        return {
            "forecast_path": csv_path,
            "plot_path": plot_path,
            "summary": summary,
        }

    except Exception as e:
        return f"Error in time_series_forecast: {str(e)}"


def spatial_trend_analysis(
    data_path: str,
    value_col: str,
    method: str = "ols",
) -> str:
    """空间趋势分析（OLS 回归 + Moran's I 检验）。

    分析空间数据中数值属性的空间分布趋势，
    通过坐标回归检测空间梯度，并用 Moran's I 量化空间聚集程度。

    Args:
        data_path: 空间数据文件路径（SHP/GeoJSON/GPKG）。
        value_col: 待分析的数值列名。
        method: 趋势方法。"ols"（普通最小二乘）、"spatial_lag"（空间滞后模型概要）。

    Returns:
        包含趋势结果 GeoJSON 路径、分析图 PNG 路径、Moran's I 及 p 值的字典。
    """
    try:
        res_path = _resolve_path(data_path)
        gdf = _load_spatial_data(res_path)

        if not hasattr(gdf, "geometry") or gdf.geometry is None:
            return "Error: input file has no geometry — spatial trend requires spatial data."

        if value_col not in gdf.columns:
            return f"Error: column '{value_col}' not found. Available: {list(gdf.columns)}"

        y = gdf[value_col].astype(float)
        if y.isna().all():
            return f"Error: column '{value_col}' is entirely NaN."
        y = y.fillna(y.mean())

        # Get centroids for coordinate regression
        gdf_work = gdf.copy()
        if gdf_work.crs and gdf_work.crs.is_geographic:
            gdf_work = gdf_work.to_crs(epsg=3857)
        centroids = gdf_work.geometry.centroid
        X = np.column_stack([centroids.x.values, centroids.y.values])

        # OLS regression: value ~ x + y
        from numpy.linalg import lstsq
        X_aug = np.column_stack([np.ones(len(X)), X])
        coeffs, residuals, _, _ = lstsq(X_aug, y.values, rcond=None)

        gdf_out = gdf.copy()
        predicted = X_aug @ coeffs
        gdf_out["trend_predicted"] = np.round(predicted, 4)
        gdf_out["trend_residual"] = np.round(y.values - predicted, 4)

        # Moran's I on residuals
        moran_i = None
        p_value = None
        try:
            from libpysal.weights import Queen
            from esda.moran import Moran
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                w = Queen.from_dataframe(gdf_work, use_index=False)
                w.transform = "R"
                mi = Moran(gdf_out["trend_residual"].values, w, permutations=999)
                moran_i = round(float(mi.I), 6)
                p_value = round(float(mi.p_sim), 6)
        except Exception as e:
            logger.warning("Moran's I computation failed: %s", e)

        # Save output
        out_path = _generate_output_path("spatial_trend", "geojson")
        gdf_out.to_file(out_path, driver="GeoJSON")

        # Plot
        _configure_fonts()
        fig, axes = plt.subplots(1, 2, figsize=(16, 6))
        gdf_out.plot(column=value_col, ax=axes[0], legend=True, cmap="RdYlGn")
        axes[0].set_title(f"原始值: {value_col}", fontsize=12)
        axes[0].set_axis_off()
        gdf_out.plot(column="trend_residual", ax=axes[1], legend=True, cmap="RdBu_r")
        axes[1].set_title("趋势残差", fontsize=12)
        axes[1].set_axis_off()
        plt.suptitle("空间趋势分析", fontsize=14)
        plt.tight_layout()
        plot_path = _generate_output_path("spatial_trend_plot", "png")
        plt.savefig(plot_path, dpi=200, bbox_inches="tight")
        plt.close()

        result = {
            "trend_path": out_path,
            "plot_path": plot_path,
            "coefficients": {
                "intercept": round(float(coeffs[0]), 6),
                "x_gradient": round(float(coeffs[1]), 10),
                "y_gradient": round(float(coeffs[2]), 10),
            },
            "feature_count": len(gdf),
        }
        if moran_i is not None:
            result["moran_i"] = moran_i
            result["p_value"] = p_value

        return result

    except Exception as e:
        return f"Error in spatial_trend_analysis: {str(e)}"


# ---------------------------------------------------------------------------
# Category 2: Scenario Simulation
# ---------------------------------------------------------------------------

def what_if_analysis(
    data_path: str,
    scenario: str,
    target_col: str,
) -> str:
    """假设分析（What-If）：对目标列应用场景变化因子，计算影响增量。

    通过指定各列的变化倍率（multiplier），模拟场景变化后的
    目标列期望值，并输出前后对比和变化百分比。

    Args:
        data_path: 数据文件路径。
        scenario: JSON 格式的场景定义，如 '{"population": 1.2, "area": 0.9}' 表示人口增长 20%、面积缩减 10%。
        target_col: 目标列名（计算变化的列）。

    Returns:
        包含结果文件路径和变化摘要（前值、后值、变化百分比）的字典。
    """
    try:
        res_path = _resolve_path(data_path)
        df = _load_data(res_path)

        if target_col not in df.columns:
            return f"Error: target column '{target_col}' not found. Available: {list(df.columns)}"

        # Parse scenario
        if isinstance(scenario, str):
            scenario = json.loads(scenario)
        if not isinstance(scenario, dict) or len(scenario) == 0:
            return "Error: scenario must be a non-empty dict of column→multiplier."

        # Validate columns
        for col in scenario:
            if col not in df.columns:
                return f"Error: scenario column '{col}' not found. Available: {list(df.columns)}"

        df_result = df.copy()
        before_mean = float(df[target_col].astype(float).mean())

        # Apply multipliers
        for col, multiplier in scenario.items():
            multiplier = float(multiplier)
            df_result[col] = df_result[col].astype(float) * multiplier

        after_mean = float(df_result[target_col].astype(float).mean())
        delta_pct = round((after_mean - before_mean) / before_mean * 100, 2) if before_mean != 0 else 0.0

        # Save
        has_geom = hasattr(df_result, "geometry") and df_result.geometry is not None
        if has_geom:
            out_path = _generate_output_path("whatif_result", "geojson")
            try:
                df_result.to_file(out_path, driver="GeoJSON")
            except Exception:
                out_path = _generate_output_path("whatif_result", "csv")
                df_result.drop(columns=["geometry"], errors="ignore").to_csv(out_path, index=False, encoding="utf-8-sig")
        else:
            out_path = _generate_output_path("whatif_result", "csv")
            df_result.to_csv(out_path, index=False, encoding="utf-8-sig")

        return {
            "result_path": out_path,
            "summary": {
                "target_col": target_col,
                "before_mean": round(before_mean, 4),
                "after_mean": round(after_mean, 4),
                "delta_pct": delta_pct,
                "scenario": {k: float(v) for k, v in scenario.items()},
                "records": len(df),
            },
        }

    except json.JSONDecodeError:
        return "Error: scenario must be valid JSON, e.g. '{\"col\": 1.2}'."
    except Exception as e:
        return f"Error in what_if_analysis: {str(e)}"


def scenario_compare(
    data_path: str,
    scenarios: str,
    target_col: str,
) -> str:
    """多场景对比分析：并排比较多个 What-If 场景的影响。

    对同一数据集应用多个不同的变化场景，计算各场景下目标列的
    变化量，输出对比表格和排名柱状图。

    Args:
        data_path: 数据文件路径。
        scenarios: JSON 数组格式的多场景定义，如 '[{"name":"增长","population":1.3},{"name":"缩减","population":0.7}]'。每个场景需包含 "name" 键。
        target_col: 目标列名。

    Returns:
        包含对比 CSV 路径、柱状图 PNG 路径和排名列表的字典。
    """
    try:
        res_path = _resolve_path(data_path)
        df = _load_data(res_path)

        if target_col not in df.columns:
            return f"Error: target column '{target_col}' not found. Available: {list(df.columns)}"

        if isinstance(scenarios, str):
            scenarios = json.loads(scenarios)
        if not isinstance(scenarios, list) or len(scenarios) < 2:
            return "Error: scenarios must be a JSON array with at least 2 scenario objects."

        baseline = float(df[target_col].astype(float).mean())
        results = []

        for i, sc in enumerate(scenarios):
            name = sc.pop("name", f"Scenario_{i+1}")
            df_temp = df.copy()
            for col, multiplier in sc.items():
                if col in df_temp.columns:
                    df_temp[col] = df_temp[col].astype(float) * float(multiplier)
            after = float(df_temp[target_col].astype(float).mean())
            delta_pct = round((after - baseline) / baseline * 100, 2) if baseline != 0 else 0.0
            results.append({
                "scenario": name,
                "baseline": round(baseline, 4),
                "result": round(after, 4),
                "delta_pct": delta_pct,
            })

        # Sort by delta_pct descending
        results.sort(key=lambda x: x["delta_pct"], reverse=True)

        comp_df = pd.DataFrame(results)
        csv_path = _generate_output_path("scenario_compare", "csv")
        comp_df.to_csv(csv_path, index=False, encoding="utf-8-sig")

        # Chart
        _configure_fonts()
        fig, ax = plt.subplots(figsize=(10, max(4, len(results) * 0.8)))
        colors = ["#4CAF50" if r["delta_pct"] >= 0 else "#F44336" for r in results]
        ax.barh([r["scenario"] for r in results], [r["delta_pct"] for r in results], color=colors)
        ax.set_xlabel("变化百分比 (%)")
        ax.set_title(f"多场景对比: {target_col}", fontsize=13)
        ax.axvline(x=0, color="black", linewidth=0.8)
        ax.grid(axis="x", alpha=0.3)
        plt.tight_layout()
        chart_path = _generate_output_path("scenario_chart", "png")
        plt.savefig(chart_path, dpi=200, bbox_inches="tight")
        plt.close()

        return {
            "comparison_path": csv_path,
            "chart_path": chart_path,
            "rankings": results,
        }

    except json.JSONDecodeError:
        return "Error: scenarios must be valid JSON array."
    except Exception as e:
        return f"Error in scenario_compare: {str(e)}"


# ---------------------------------------------------------------------------
# Category 3: Network Analysis
# ---------------------------------------------------------------------------

def network_centrality(
    data_path: str,
    weight_col: str = None,
    method: str = "betweenness",
) -> str:
    """网络中心性分析：计算空间要素的图中心性指标。

    从空间数据构建拓扑图（多边形邻接/线段连通/点 Delaunay），
    计算各节点的中心性得分，识别网络中的关键节点。

    Args:
        data_path: 空间数据文件路径（SHP/GeoJSON/GPKG）。
        weight_col: 可选权重列名（用于加权中心性）。
        method: 中心性算法。"degree"（度中心性）、"betweenness"（介数中心性）、
                "closeness"（接近中心性）、"eigenvector"（特征向量中心性）。

    Returns:
        包含结果 GeoJSON 路径、Top-10 节点和统计摘要的字典。
    """
    try:
        import networkx as nx

        res_path = _resolve_path(data_path)
        gdf = _load_spatial_data(res_path)

        if not hasattr(gdf, "geometry") or gdf.geometry is None:
            return "Error: input file has no geometry — network analysis requires spatial data."

        G = _build_spatial_graph(gdf, weight_col)

        if G.number_of_nodes() == 0:
            return "Error: empty graph — no features to analyze."

        method = method.lower()
        if method == "degree":
            centrality = nx.degree_centrality(G)
        elif method == "betweenness":
            centrality = nx.betweenness_centrality(G, weight="weight")
        elif method == "closeness":
            centrality = nx.closeness_centrality(G, distance="weight")
        elif method == "eigenvector":
            try:
                centrality = nx.eigenvector_centrality(G, weight="weight", max_iter=1000)
            except nx.PowerIterationFailedConvergence:
                centrality = nx.eigenvector_centrality_numpy(G, weight="weight")
        else:
            return f"Error: unknown method '{method}'. Use degree/betweenness/closeness/eigenvector."

        # Attach to GeoDataFrame
        gdf_out = gdf.copy()
        scores = [centrality.get(i, 0.0) for i in range(len(gdf))]
        gdf_out["centrality"] = np.round(scores, 6)

        out_path = _generate_output_path("network_centrality", "geojson")
        gdf_out.to_file(out_path, driver="GeoJSON")

        # Top-10
        sorted_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        top_nodes = [{"index": i, "centrality": round(scores[i], 6)} for i in sorted_indices[:10]]

        stats = {
            "method": method,
            "nodes": G.number_of_nodes(),
            "edges": G.number_of_edges(),
            "mean_centrality": round(float(np.mean(scores)), 6),
            "max_centrality": round(float(np.max(scores)), 6),
        }

        return {
            "result_path": out_path,
            "top_nodes": top_nodes,
            "stats": stats,
        }

    except Exception as e:
        return f"Error in network_centrality: {str(e)}"


def community_detection(
    data_path: str,
    weight_col: str = None,
    method: str = "louvain",
) -> str:
    """空间社区检测：基于图分区识别空间聚类。

    从空间邻接关系构建网络图，使用社区检测算法将要素
    划分为内部联系紧密的子群（社区），并计算模块度指标。

    Args:
        data_path: 空间数据文件路径（SHP/GeoJSON/GPKG）。
        weight_col: 可选权重列名。
        method: 社区检测算法。"louvain"（Louvain 算法）、"label_propagation"（标签传播算法）。

    Returns:
        包含结果 GeoJSON 路径、社区数量和模块度的字典。
    """
    try:
        import networkx as nx
        from networkx.algorithms.community import louvain_communities, label_propagation_communities

        res_path = _resolve_path(data_path)
        gdf = _load_spatial_data(res_path)

        if not hasattr(gdf, "geometry") or gdf.geometry is None:
            return "Error: input file has no geometry — community detection requires spatial data."

        G = _build_spatial_graph(gdf, weight_col)

        if G.number_of_nodes() == 0:
            return "Error: empty graph — no features to analyze."

        method = method.lower()
        if method == "louvain":
            communities = louvain_communities(G, weight="weight", seed=42)
        elif method == "label_propagation":
            communities = list(label_propagation_communities(G))
        else:
            return f"Error: unknown method '{method}'. Use louvain/label_propagation."

        # Assign community labels
        labels = [0] * len(gdf)
        for comm_id, comm_nodes in enumerate(communities):
            for node in comm_nodes:
                if node < len(labels):
                    labels[node] = comm_id

        gdf_out = gdf.copy()
        gdf_out["community"] = labels

        # Modularity
        if G.number_of_edges() > 0:
            modularity = round(nx.community.modularity(G, communities), 6)
        else:
            modularity = 0.0

        out_path = _generate_output_path("communities", "geojson")
        gdf_out.to_file(out_path, driver="GeoJSON")

        # Community sizes
        comm_sizes = {}
        for lbl in labels:
            comm_sizes[lbl] = comm_sizes.get(lbl, 0) + 1

        return {
            "result_path": out_path,
            "n_communities": len(communities),
            "modularity": modularity,
            "method": method,
            "community_sizes": comm_sizes,
            "feature_count": len(gdf),
        }

    except Exception as e:
        return f"Error in community_detection: {str(e)}"


def accessibility_analysis(
    data_path: str,
    facility_path: str,
    cost_col: str = None,
    threshold: float = 5000,
) -> str:
    """可达性分析：计算每个要素到最近设施的距离评分。

    基于欧氏距离或自定义成本列，评估各空间要素到指定设施点的
    可达性，并输出评分结果和覆盖率统计。

    Args:
        data_path: 被评估要素的空间数据文件路径。
        facility_path: 设施点的空间数据文件路径。
        cost_col: 可选成本列名（用于加权距离）。为 None 时使用欧氏距离。
        threshold: 可达性阈值距离（米，默认 5000）。超过此距离视为不可达。

    Returns:
        包含评分结果 GeoJSON 路径和覆盖率统计（均值、中位数、达标率）的字典。
    """
    try:
        from sklearn.neighbors import BallTree

        res_path = _resolve_path(data_path)
        gdf = _load_spatial_data(res_path)
        fac_path = _resolve_path(facility_path)
        gdf_fac = _load_spatial_data(fac_path)

        if not hasattr(gdf, "geometry") or gdf.geometry is None:
            return "Error: data file has no geometry."
        if not hasattr(gdf_fac, "geometry") or gdf_fac.geometry is None:
            return "Error: facility file has no geometry."
        if len(gdf_fac) == 0:
            return "Error: facility file is empty — no facilities to compute accessibility."

        # Reproject to metric CRS for distance calculation
        gdf_work = gdf.copy()
        gdf_fac_work = gdf_fac.copy()
        if gdf_work.crs and gdf_work.crs.is_geographic:
            gdf_work = gdf_work.to_crs(epsg=3857)
        if gdf_fac_work.crs and gdf_fac_work.crs.is_geographic:
            gdf_fac_work = gdf_fac_work.to_crs(epsg=3857)

        # Get centroids
        src_coords = np.array([(g.centroid.x, g.centroid.y) for g in gdf_work.geometry])
        fac_coords = np.array([(g.centroid.x, g.centroid.y) for g in gdf_fac_work.geometry])

        # BallTree for nearest-facility distance
        tree = BallTree(fac_coords, metric="euclidean")
        distances, _ = tree.query(src_coords, k=1)
        distances = distances.flatten()

        # Apply cost weighting if specified
        if cost_col and cost_col in gdf.columns:
            cost = gdf[cost_col].astype(float).fillna(1.0).values
            distances = distances * cost

        gdf_out = gdf.copy()
        gdf_out["nearest_facility_dist"] = np.round(distances, 2)
        gdf_out["accessible"] = (distances <= threshold).astype(int)
        if threshold > 0:
            gdf_out["accessibility_score"] = np.round(
                np.clip(1 - distances / threshold, 0, 1), 4
            )
        else:
            gdf_out["accessibility_score"] = 0.0

        out_path = _generate_output_path("accessibility", "geojson")
        gdf_out.to_file(out_path, driver="GeoJSON")

        pct_within = round(float(np.mean(distances <= threshold) * 100), 2)

        stats = {
            "feature_count": len(gdf),
            "facility_count": len(gdf_fac),
            "threshold": threshold,
            "mean_distance": round(float(np.mean(distances)), 2),
            "median_distance": round(float(np.median(distances)), 2),
            "min_distance": round(float(np.min(distances)), 2),
            "max_distance": round(float(np.max(distances)), 2),
            "pct_within_threshold": pct_within,
        }

        return {
            "result_path": out_path,
            "stats": stats,
        }

    except Exception as e:
        return f"Error in accessibility_analysis: {str(e)}"
