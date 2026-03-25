"""Spatial-temporal causal inference tools.

Six methods covering quasi-experimental designs, dynamical-systems causality,
and causal machine learning — all with optional GeoFM embedding support for
controlling unmeasured spatial confounders (paper Angle A interface).

Dependencies: statsmodels, scikit-learn, libpysal, scipy, numpy, pandas,
geopandas, matplotlib — all already in requirements.txt.
"""

import json
import logging
import os
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

from .gis_processors import _generate_output_path, _resolve_path
from .utils import _load_spatial_data, _configure_fonts

logger = logging.getLogger(__name__)


# ====================================================================
#  Internal helpers
# ====================================================================

def _load_data(path):
    """Load as GeoDataFrame if spatial, else plain DataFrame."""
    try:
        return _load_spatial_data(path)
    except Exception:
        ext = os.path.splitext(path)[1].lower()
        if ext == ".csv":
            return pd.read_csv(path, encoding="utf-8-sig")
        if ext in (".xls", ".xlsx"):
            return pd.read_excel(path)
        raise


def _parse_columns(col_str: str) -> list[str]:
    """Parse comma-separated column names."""
    return [c.strip() for c in col_str.split(",") if c.strip()]


def _estimate_propensity_scores(X: np.ndarray, treatment: np.ndarray,
                                method: str = "gbt") -> np.ndarray:
    """Estimate propensity scores via GBT or logistic regression.

    Returns array of P(treatment=1 | X) for each observation.
    """
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression

    if method == "logistic":
        model = LogisticRegression(max_iter=1000, solver="lbfgs")
    else:
        model = GradientBoostingClassifier(
            n_estimators=100, max_depth=3, learning_rate=0.1, random_state=42,
        )
    model.fit(X, treatment)
    return model.predict_proba(X)[:, 1]


def _estimate_gps(X: np.ndarray, exposure: np.ndarray) -> tuple[np.ndarray, float]:
    """Estimate Generalized Propensity Score for continuous exposure.

    Fits GBT regression of exposure on X, then computes density of residuals.
    Returns (gps_values, residual_std).
    """
    from sklearn.ensemble import GradientBoostingRegressor

    model = GradientBoostingRegressor(
        n_estimators=100, max_depth=3, learning_rate=0.1, random_state=42,
    )
    model.fit(X, exposure)
    residuals = exposure - model.predict(X)
    sigma = max(residuals.std(), 1e-8)
    # GPS = normal density of residual
    gps = np.exp(-0.5 * (residuals / sigma) ** 2) / (sigma * np.sqrt(2 * np.pi))
    return gps, sigma


def _balance_diagnostics(X: pd.DataFrame, treatment: np.ndarray,
                         weights: np.ndarray | None = None) -> pd.DataFrame:
    """Compute standardized mean differences (SMD) for balance checking.

    Returns DataFrame with columns: variable, smd_raw, smd_weighted.
    """
    t_mask = treatment.astype(bool)
    rows = []
    for col in X.columns:
        vals = X[col].values.astype(float)
        mu1_raw = vals[t_mask].mean()
        mu0_raw = vals[~t_mask].mean()
        pooled_std = max(np.sqrt((vals[t_mask].var() + vals[~t_mask].var()) / 2), 1e-8)
        smd_raw = (mu1_raw - mu0_raw) / pooled_std

        smd_w = smd_raw
        if weights is not None:
            w1 = weights[t_mask]
            w0 = weights[~t_mask]
            mu1_w = np.average(vals[t_mask], weights=w1) if w1.sum() > 0 else mu1_raw
            mu0_w = np.average(vals[~t_mask], weights=w0) if w0.sum() > 0 else mu0_raw
            smd_w = (mu1_w - mu0_w) / pooled_std
        rows.append({"variable": col, "smd_raw": round(smd_raw, 4),
                      "smd_weighted": round(smd_w, 4)})
    return pd.DataFrame(rows)


def _extract_geofm_confounders(gdf, year: int = 2023) -> pd.DataFrame | None:
    """Extract AlphaEarth 64-dim embeddings as confounder columns.

    Calls world_model.extract_embeddings() on the GeoDataFrame bbox,
    then performs zonal mean aggregation per geometry.
    Returns DataFrame with columns geofm_0 .. geofm_63, or None if unavailable.
    """
    try:
        from .world_model import extract_embeddings
    except ImportError:
        logger.warning("world_model not available, skipping GeoFM embeddings")
        return None

    if not hasattr(gdf, "geometry") or gdf.geometry is None:
        return None

    # Get bbox in EPSG:4326
    gdf_4326 = gdf.to_crs(epsg=4326) if gdf.crs and not gdf.crs.is_geographic else gdf
    bounds = gdf_4326.total_bounds  # [minx, miny, maxx, maxy]
    bbox = [float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3])]

    embeddings = extract_embeddings(bbox, year, scale=100)
    if embeddings is None:
        logger.warning("GeoFM embedding extraction returned None")
        return None

    # embeddings shape: [H, W, 64]
    # For each geometry, compute zonal mean of the embedding grid
    from shapely.geometry import box as shapely_box

    h, w, z_dim = embeddings.shape
    x_res = (bbox[2] - bbox[0]) / w
    y_res = (bbox[3] - bbox[1]) / h

    result = np.zeros((len(gdf_4326), z_dim))
    for idx, geom in enumerate(gdf_4326.geometry):
        gx0, gy0, gx1, gy1 = geom.bounds
        # Map to grid indices
        c0 = max(0, int((gx0 - bbox[0]) / x_res))
        c1 = min(w, int((gx1 - bbox[0]) / x_res) + 1)
        r0 = max(0, int((bbox[3] - gy1) / y_res))
        r1 = min(h, int((bbox[3] - gy0) / y_res) + 1)
        if r1 > r0 and c1 > c0:
            patch = embeddings[r0:r1, c0:c1, :]
            result[idx] = patch.reshape(-1, z_dim).mean(axis=0)

    cols = {f"geofm_{i}": result[:, i] for i in range(z_dim)}
    return pd.DataFrame(cols, index=gdf.index)


def _ensure_metric_crs(gdf):
    """Return (gdf_projected, is_reprojected) — reproject to EPSG:3857 if geographic."""
    if gdf.crs and gdf.crs.is_geographic:
        return gdf.to_crs(epsg=3857), True
    return gdf, False


# ====================================================================
#  Tool 1: Propensity Score Matching
# ====================================================================

def propensity_score_matching(
    file_path: str,
    treatment_col: str,
    outcome_col: str,
    confounders: str,
    method: str = "nearest",
    spatial_distance_weight: float = 0.0,
    caliper: float = 0.25,
    use_geofm_embedding: bool = False,
) -> str:
    """倾向得分匹配因果推断（Propensity Score Matching）。

    通过匹配处理组和对照组的协变量分布，估计平均处理效应(ATE)和
    处理组平均处理效应(ATT)。支持空间距离加权匹配和GeoFM嵌入增强。

    Args:
        file_path: 空间数据文件路径（GeoJSON/SHP/GPKG/CSV）
        treatment_col: 二元处理变量列名（0/1）
        outcome_col: 结果变量列名
        confounders: 混淆变量列名，逗号分隔
        method: 匹配方法 nearest/caliper/kernel
        spatial_distance_weight: 空间距离权重 0~1（0=不考虑空间距离）
        caliper: 倾向得分卡钳宽度（标准差的倍数）
        use_geofm_embedding: 是否使用AlphaEarth GeoFM嵌入作为额外混淆控制

    Returns:
        JSON string with ate, att, diagnostics, and output file paths.
    """
    _configure_fonts()
    path = _resolve_path(file_path)
    gdf = _load_data(path)

    conf_cols = _parse_columns(confounders)
    required = [treatment_col, outcome_col] + conf_cols
    missing = [c for c in required if c not in gdf.columns]
    if missing:
        return json.dumps({"error": f"缺少列: {missing}"}, ensure_ascii=False)

    treatment = gdf[treatment_col].values.astype(int)
    outcome = gdf[outcome_col].values.astype(float)
    X = gdf[conf_cols].copy()

    # GeoFM embedding augmentation
    if use_geofm_embedding and hasattr(gdf, "geometry") and gdf.geometry is not None:
        geofm_df = _extract_geofm_confounders(gdf)
        if geofm_df is not None:
            X = pd.concat([X, geofm_df], axis=1)

    # Handle missing values
    X = X.fillna(X.median())

    # Estimate propensity scores
    ps = _estimate_propensity_scores(X.values, treatment, method="gbt")

    # Matching
    from scipy.spatial import KDTree

    t_idx = np.where(treatment == 1)[0]
    c_idx = np.where(treatment == 0)[0]

    if len(t_idx) == 0 or len(c_idx) == 0:
        return json.dumps({"error": "处理组或对照组为空"}, ensure_ascii=False)

    ps_std = max(ps.std(), 1e-8)
    caliper_abs = caliper * ps_std

    # Build matching features
    if (spatial_distance_weight > 0 and hasattr(gdf, "geometry")
            and gdf.geometry is not None):
        gdf_m, _ = _ensure_metric_crs(gdf)
        coords = np.array([(g.centroid.x, g.centroid.y) for g in gdf_m.geometry])
        max_d = max(np.ptp(coords[:, 0]), np.ptp(coords[:, 1]), 1e-8)
        w = spatial_distance_weight
        # Combine propensity + spatial distance
        ps_norm = ps.reshape(-1, 1) / ps_std
        coord_norm = coords / max_d
        match_feat_c = np.hstack([(1 - w) * ps_norm[c_idx], w * coord_norm[c_idx]])
        match_feat_t = np.hstack([(1 - w) * ps_norm[t_idx], w * coord_norm[t_idx]])
    else:
        match_feat_c = ps[c_idx].reshape(-1, 1)
        match_feat_t = ps[t_idx].reshape(-1, 1)

    tree = KDTree(match_feat_c)
    dists, indices = tree.query(match_feat_t, k=1)

    # Apply caliper
    if method == "caliper":
        keep = dists.flatten() < caliper_abs
    else:
        keep = np.ones(len(t_idx), dtype=bool)

    matched_t = t_idx[keep]
    matched_c = c_idx[indices.flatten()[keep]]

    if len(matched_t) == 0:
        return json.dumps({"error": "卡钳过严，无匹配对"}, ensure_ascii=False)

    # Estimate effects
    y1 = outcome[matched_t]
    y0 = outcome[matched_c]
    att = float(np.mean(y1 - y0))
    ate = att  # With 1:1 matching, ATE ≈ ATT

    diffs = y1 - y0
    se = float(np.std(diffs, ddof=1) / np.sqrt(len(diffs)))
    ci_lower = att - 1.96 * se
    ci_upper = att + 1.96 * se

    # Balance diagnostics
    balance = _balance_diagnostics(
        gdf[conf_cols], treatment,
        weights=None,
    )
    balance_path = _generate_output_path("psm_balance", "csv")
    balance.to_csv(balance_path, index=False)

    # Diagnostic plot: SMD before/after
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    # Plot 1: Propensity score overlap
    axes[0].hist(ps[t_idx], bins=30, alpha=0.5, label="处理组", density=True)
    axes[0].hist(ps[c_idx], bins=30, alpha=0.5, label="对照组", density=True)
    axes[0].set_xlabel("倾向得分")
    axes[0].set_ylabel("密度")
    axes[0].set_title("倾向得分分布重叠")
    axes[0].legend()

    # Plot 2: SMD comparison
    bal_vars = balance["variable"].values
    y_pos = np.arange(len(bal_vars))
    axes[1].barh(y_pos - 0.15, balance["smd_raw"].abs(), height=0.3,
                 label="匹配前", alpha=0.7)
    # Compute post-match SMD
    post_X_t = gdf[conf_cols].iloc[matched_t]
    post_X_c = gdf[conf_cols].iloc[matched_c]
    smd_post = []
    for col in conf_cols:
        v1 = post_X_t[col].astype(float).values
        v0 = post_X_c[col].astype(float).values
        pooled = max(np.sqrt((v1.var() + v0.var()) / 2), 1e-8)
        smd_post.append(abs((v1.mean() - v0.mean()) / pooled))
    axes[1].barh(y_pos + 0.15, smd_post, height=0.3, label="匹配后", alpha=0.7)
    axes[1].set_yticks(y_pos)
    axes[1].set_yticklabels(bal_vars)
    axes[1].axvline(x=0.1, color="red", linestyle="--", alpha=0.5)
    axes[1].set_xlabel("标准化均值差（|SMD|）")
    axes[1].set_title("协变量平衡诊断")
    axes[1].legend()

    plt.tight_layout()
    plot_path = _generate_output_path("psm_diagnostic", "png")
    fig.savefig(plot_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    # Save matched data
    matched_df = gdf.iloc[np.concatenate([matched_t, matched_c])].copy()
    matched_df["_match_group"] = (["treated"] * len(matched_t)
                                  + ["control"] * len(matched_c))
    matched_path = _generate_output_path("psm_matched", "csv")
    if hasattr(matched_df, "geometry"):
        matched_df.drop(columns=["geometry"], errors="ignore").to_csv(
            matched_path, index=False)
    else:
        matched_df.to_csv(matched_path, index=False)

    return json.dumps({
        "method": "propensity_score_matching",
        "ate": round(ate, 4),
        "att": round(att, 4),
        "se": round(se, 4),
        "ci_lower": round(ci_lower, 4),
        "ci_upper": round(ci_upper, 4),
        "n_treated": int(len(t_idx)),
        "n_control": int(len(c_idx)),
        "n_matched": int(len(matched_t)),
        "caliper_used": caliper,
        "spatial_distance_weight": spatial_distance_weight,
        "use_geofm_embedding": use_geofm_embedding,
        "balance_table_path": balance_path,
        "diagnostic_plot_path": plot_path,
        "matched_data_path": matched_path,
        "summary": (
            f"PSM因果推断: ATT={att:.2f} (95%CI: [{ci_lower:.2f}, {ci_upper:.2f}]), "
            f"匹配{len(matched_t)}对, SE={se:.2f}"
        ),
    }, ensure_ascii=False)


# ====================================================================
#  Tool 2: Exposure-Response Function (ERF)
# ====================================================================

def exposure_response_function(
    file_path: str,
    exposure_col: str,
    outcome_col: str,
    confounders: str,
    method: str = "ipsw",
    bandwidth: str = "auto",
    n_bootstrap: int = 0,
    use_geofm_embedding: bool = False,
) -> str:
    """暴露-响应函数估计（Exposure-Response Function）。

    估计连续暴露变量与结果变量之间的因果剂量-响应关系。
    使用逆倾向得分加权(IPSW)控制混淆偏差，高斯核加权移动平均拟合ERF曲线。

    Args:
        file_path: 数据文件路径
        exposure_col: 连续暴露变量列名
        outcome_col: 结果变量列名
        confounders: 混淆变量列名，逗号分隔
        method: ipsw（逆倾向得分加权）
        bandwidth: 核带宽 auto/cv/数值
        n_bootstrap: Bootstrap重采样次数（0=不计算置信区间）
        use_geofm_embedding: 是否使用GeoFM嵌入

    Returns:
        JSON string with ERF curve data and plot paths.
    """
    _configure_fonts()
    path = _resolve_path(file_path)
    gdf = _load_data(path)

    conf_cols = _parse_columns(confounders)
    required = [exposure_col, outcome_col] + conf_cols
    missing = [c for c in required if c not in gdf.columns]
    if missing:
        return json.dumps({"error": f"缺少列: {missing}"}, ensure_ascii=False)

    exposure = gdf[exposure_col].values.astype(float)
    outcome = gdf[outcome_col].values.astype(float)
    X = gdf[conf_cols].copy()

    if use_geofm_embedding and hasattr(gdf, "geometry") and gdf.geometry is not None:
        geofm_df = _extract_geofm_confounders(gdf)
        if geofm_df is not None:
            X = pd.concat([X, geofm_df], axis=1)

    X = X.fillna(X.median())

    # Trim extreme exposure values (1st and 99th percentile)
    lo, hi = np.percentile(exposure, [1, 99])
    trim_mask = (exposure >= lo) & (exposure <= hi)
    exposure_t = exposure[trim_mask]
    outcome_t = outcome[trim_mask]
    X_t = X.values[trim_mask]
    trimmed_pct = round(100 * (1 - trim_mask.sum() / len(exposure)), 2)

    # Generalized propensity score estimation
    gps, sigma = _estimate_gps(X_t, exposure_t)

    # IPSW weights
    # Marginal density of exposure (kernel density estimate)
    from scipy.stats import gaussian_kde
    try:
        kde = gaussian_kde(exposure_t)
        marginal_density = kde(exposure_t)
    except Exception:
        marginal_density = np.ones_like(exposure_t)

    weights = marginal_density / np.maximum(gps, 1e-10)
    # Stabilize weights
    weights = np.clip(weights, 0, np.percentile(weights, 99))
    weights = weights / weights.mean()

    # Bandwidth selection
    if bandwidth == "auto" or bandwidth == "plugin":
        # Fan (1996) plug-in rule: h = 1.06 * σ * n^(-1/5)
        bw = 1.06 * exposure_t.std() * len(exposure_t) ** (-0.2)
    elif bandwidth == "cv":
        # Leave-one-out cross-validation
        bw_candidates = exposure_t.std() * np.array([0.5, 0.75, 1.0, 1.5, 2.0]) * len(exposure_t) ** (-0.2)
        best_bw, best_score = bw_candidates[0], np.inf
        for bw_c in bw_candidates:
            scores = []
            for i in range(len(exposure_t)):
                kern = np.exp(-0.5 * ((exposure_t - exposure_t[i]) / bw_c) ** 2)
                kern[i] = 0  # leave one out
                kw = kern * weights
                if kw.sum() > 0:
                    pred = np.average(outcome_t, weights=kw)
                    scores.append((outcome_t[i] - pred) ** 2)
            cv_score = np.mean(scores) if scores else np.inf
            if cv_score < best_score:
                best_score, best_bw = cv_score, bw_c
        bw = best_bw
    else:
        bw = float(bandwidth)

    bw = max(bw, 1e-8)

    # Compute ERF: Gaussian kernel-weighted moving average
    grid = np.linspace(exposure_t.min(), exposure_t.max(), 100)
    erf_values = np.zeros(len(grid))
    for i, g in enumerate(grid):
        kern = np.exp(-0.5 * ((exposure_t - g) / bw) ** 2)
        kw = kern * weights
        if kw.sum() > 1e-10:
            erf_values[i] = np.average(outcome_t, weights=kw)
        else:
            erf_values[i] = np.nan

    # Bootstrap CI
    ci_lower_arr = ci_upper_arr = None
    if n_bootstrap > 0:
        boot_erfs = []
        rng = np.random.RandomState(42)
        for _ in range(n_bootstrap):
            idx = rng.choice(len(exposure_t), size=len(exposure_t), replace=True)
            e_b, o_b, w_b = exposure_t[idx], outcome_t[idx], weights[idx]
            erf_b = np.zeros(len(grid))
            for i, g in enumerate(grid):
                kern = np.exp(-0.5 * ((e_b - g) / bw) ** 2)
                kw = kern * w_b
                if kw.sum() > 1e-10:
                    erf_b[i] = np.average(o_b, weights=kw)
                else:
                    erf_b[i] = np.nan
            boot_erfs.append(erf_b)
        boot_arr = np.array(boot_erfs)
        ci_lower_arr = np.nanpercentile(boot_arr, 2.5, axis=0)
        ci_upper_arr = np.nanpercentile(boot_arr, 97.5, axis=0)

    # Balance check
    balance = _balance_diagnostics(gdf[conf_cols].iloc[np.where(trim_mask)[0]],
                                   (exposure_t > np.median(exposure_t)).astype(int),
                                   weights)
    mean_abs_smd = float(balance["smd_weighted"].abs().mean())

    # Save ERF data
    erf_df = pd.DataFrame({"exposure": grid, "response": erf_values})
    if ci_lower_arr is not None:
        erf_df["ci_lower"] = ci_lower_arr
        erf_df["ci_upper"] = ci_upper_arr
    erf_data_path = _generate_output_path("erf_data", "csv")
    erf_df.to_csv(erf_data_path, index=False)

    # Plot
    fig, ax = plt.subplots(figsize=(10, 6))
    # Weighted scatter
    ax.scatter(exposure_t, outcome_t, s=weights * 5, alpha=0.3,
               c="steelblue", label="观测值（大小=权重）")
    ax.plot(grid, erf_values, "r-", linewidth=2, label="ERF曲线")
    if ci_lower_arr is not None:
        ax.fill_between(grid, ci_lower_arr, ci_upper_arr,
                        color="red", alpha=0.1, label="95% CI")
    ax.set_xlabel(exposure_col)
    ax.set_ylabel(outcome_col)
    ax.set_title("暴露-响应函数 (Exposure-Response Function)")
    ax.legend()
    plt.tight_layout()
    plot_path = _generate_output_path("erf_plot", "png")
    fig.savefig(plot_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    return json.dumps({
        "method": "exposure_response_function",
        "bandwidth": round(bw, 4),
        "trimmed_pct": trimmed_pct,
        "n_observations": int(len(exposure_t)),
        "balance_mean_abs_smd": round(mean_abs_smd, 4),
        "n_bootstrap": n_bootstrap,
        "erf_data_path": erf_data_path,
        "erf_plot_path": plot_path,
        "use_geofm_embedding": use_geofm_embedding,
        "summary": (
            f"ERF分析: 带宽={bw:.3f}, 观测{len(exposure_t)}个, "
            f"裁剪{trimmed_pct}%, 平衡|SMD|={mean_abs_smd:.3f}"
        ),
    }, ensure_ascii=False)


# ====================================================================
#  Tool 3: Difference-in-Differences
# ====================================================================

def difference_in_differences(
    file_path: str,
    outcome_col: str,
    treatment_col: str,
    time_col: str,
    post_col: str = "",
    entity_col: str = "",
    time_threshold: str = "",
    use_geofm_embedding: bool = False,
) -> str:
    """双重差分因果推断（Difference-in-Differences）。

    利用处理组和对照组在政策实施前后的变化差异，估计政策/干预的因果效应。
    β3（交互项系数）= DiD估计量。

    Args:
        file_path: 面板数据文件路径
        outcome_col: 结果变量列名
        treatment_col: 处理组标识列名（0/1）
        time_col: 时间列名
        post_col: 政策后时期标识列名（0/1）；若为空则用time_threshold自动划分
        entity_col: 个体/区域标识列名（可选，用于固定效应）
        time_threshold: 时间分割阈值（当post_col为空时使用）
        use_geofm_embedding: 是否使用GeoFM嵌入作为控制变量

    Returns:
        JSON string with DiD estimate, parallel trends plot, regression summary.
    """
    import statsmodels.api as sm
    _configure_fonts()
    path = _resolve_path(file_path)
    df = _load_data(path)

    required = [outcome_col, treatment_col, time_col]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return json.dumps({"error": f"缺少列: {missing}"}, ensure_ascii=False)

    df = df.copy()
    df[treatment_col] = df[treatment_col].astype(int)

    # Determine post period
    if post_col and post_col in df.columns:
        df["_post"] = df[post_col].astype(int)
    elif time_threshold:
        df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
        threshold = pd.to_datetime(time_threshold)
        df["_post"] = (df[time_col] >= threshold).astype(int)
    else:
        # Auto: use median time as threshold
        df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
        threshold = df[time_col].median()
        df["_post"] = (df[time_col] >= threshold).astype(int)

    df["_treat_post"] = df[treatment_col] * df["_post"]

    # Build regression formula
    y = df[outcome_col].values.astype(float)
    X_vars = [treatment_col, "_post", "_treat_post"]

    # Entity fixed effects (dummies)
    if entity_col and entity_col in df.columns:
        entity_dummies = pd.get_dummies(df[entity_col], prefix="entity", drop_first=True)
        X_mat = pd.concat([df[X_vars], entity_dummies], axis=1)
    else:
        X_mat = df[X_vars].copy()

    # GeoFM embedding as controls
    if use_geofm_embedding and hasattr(df, "geometry") and df.geometry is not None:
        geofm_df = _extract_geofm_confounders(df)
        if geofm_df is not None:
            X_mat = pd.concat([X_mat, geofm_df], axis=1)

    X_mat = X_mat.fillna(0).astype(float)
    X_mat = sm.add_constant(X_mat)

    # OLS regression
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = sm.OLS(y, X_mat).fit(cov_type="HC1")

    did_est = float(model.params.get("_treat_post", 0))
    did_se = float(model.bse.get("_treat_post", 0))
    did_p = float(model.pvalues.get("_treat_post", 1))
    ci = model.conf_int().loc["_treat_post"] if "_treat_post" in model.conf_int().index else [did_est, did_est]
    ci_lower, ci_upper = float(ci.iloc[0]), float(ci.iloc[1])

    # Parallel trends visualization
    fig, ax = plt.subplots(figsize=(10, 6))
    df["_time_num"] = pd.to_numeric(df[time_col], errors="coerce")
    if df["_time_num"].isna().all():
        df["_time_num"] = np.arange(len(df))

    for grp, label, color in [(1, "处理组", "steelblue"), (0, "对照组", "darkorange")]:
        sub = df[df[treatment_col] == grp]
        means = sub.groupby("_time_num")[outcome_col].mean()
        ax.plot(means.index, means.values, "o-", label=label, color=color)

    # Mark treatment time
    if post_col and post_col in df.columns:
        pre_times = df[df["_post"] == 0]["_time_num"]
        if len(pre_times) > 0:
            t_line = pre_times.max()
            ax.axvline(x=t_line, color="red", linestyle="--", alpha=0.7,
                       label="政策实施")
    ax.set_xlabel(time_col)
    ax.set_ylabel(outcome_col)
    ax.set_title(f"双重差分: DiD={did_est:.3f} (p={did_p:.4f})")
    ax.legend()
    plt.tight_layout()
    plot_path = _generate_output_path("did_parallel_trends", "png")
    fig.savefig(plot_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    return json.dumps({
        "method": "difference_in_differences",
        "did_estimate": round(did_est, 4),
        "se": round(did_se, 4),
        "p_value": round(did_p, 6),
        "ci_lower": round(ci_lower, 4),
        "ci_upper": round(ci_upper, 4),
        "r_squared": round(float(model.rsquared), 4),
        "n_observations": int(model.nobs),
        "parallel_trends_plot_path": plot_path,
        "use_geofm_embedding": use_geofm_embedding,
        "regression_summary": model.summary().as_text()[:500],
        "summary": (
            f"DiD因果推断: β3={did_est:.3f} (p={did_p:.4f}), "
            f"95%CI=[{ci_lower:.3f}, {ci_upper:.3f}], R²={model.rsquared:.3f}"
        ),
    }, ensure_ascii=False)


# ====================================================================
#  Tool 4: Spatial Granger Causality
# ====================================================================

def spatial_granger_causality(
    file_path: str,
    variables: str,
    time_col: str,
    location_col: str = "",
    max_lag: int = 4,
    significance: float = 0.05,
) -> str:
    """空间Granger因果检验。

    使用VAR模型检验多个变量之间的Granger因果关系。
    可选择引入空间滞后项，考虑相邻区域的溢出效应。

    Args:
        file_path: 时间序列或面板数据文件路径
        variables: 待检验变量列名，逗号分隔
        time_col: 时间列名
        location_col: 位置/区域标识列名（可选，用于空间面板）
        max_lag: 最大滞后阶数
        significance: 显著性水平

    Returns:
        JSON string with causality matrix, significant pairs, and plot path.
    """
    from statsmodels.tsa.api import VAR
    from statsmodels.tsa.stattools import grangercausalitytests

    _configure_fonts()
    path = _resolve_path(file_path)
    df = _load_data(path)

    var_cols = _parse_columns(variables)
    if len(var_cols) < 2:
        return json.dumps({"error": "至少需要2个变量"}, ensure_ascii=False)

    missing = [c for c in var_cols + [time_col] if c not in df.columns]
    if missing:
        return json.dumps({"error": f"缺少列: {missing}"}, ensure_ascii=False)

    df = df.sort_values(time_col).copy()

    # If panel data with location_col, aggregate or pick first location
    if location_col and location_col in df.columns:
        # Aggregate across locations (mean)
        df = df.groupby(time_col)[var_cols].mean().reset_index()

    ts_data = df[var_cols].dropna()
    if len(ts_data) < max_lag + 5:
        return json.dumps({"error": f"时间序列太短 ({len(ts_data)} 行)"}, ensure_ascii=False)

    # Pairwise Granger causality tests
    causality_matrix = {}
    significant_pairs = []

    for cause in var_cols:
        causality_matrix[cause] = {}
        for effect in var_cols:
            if cause == effect:
                causality_matrix[cause][effect] = {"f_stat": 0, "p_value": 1.0,
                                                    "significant": False, "best_lag": 0}
                continue

            pair_data = ts_data[[effect, cause]].values
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    results = grangercausalitytests(pair_data, maxlag=max_lag,
                                                   verbose=False)
                # Find best lag (minimum p-value)
                best_lag, best_p, best_f = 1, 1.0, 0.0
                for lag in range(1, max_lag + 1):
                    if lag in results:
                        test_res = results[lag][0]
                        p_val = test_res["ssr_ftest"][1]
                        f_val = test_res["ssr_ftest"][0]
                        if p_val < best_p:
                            best_p, best_f, best_lag = p_val, f_val, lag

                is_sig = best_p < significance
                causality_matrix[cause][effect] = {
                    "f_stat": round(float(best_f), 4),
                    "p_value": round(float(best_p), 6),
                    "significant": bool(is_sig),
                    "best_lag": int(best_lag),
                }
                if is_sig:
                    significant_pairs.append({
                        "cause": cause, "effect": effect,
                        "f_stat": round(float(best_f), 4),
                        "p_value": round(float(best_p), 6),
                        "lag": int(best_lag),
                    })
            except Exception as e:
                causality_matrix[cause][effect] = {
                    "f_stat": 0, "p_value": 1.0, "significant": False,
                    "error": str(e)[:100],
                }

    # Heatmap visualization
    n = len(var_cols)
    matrix = np.zeros((n, n))
    for i, cause in enumerate(var_cols):
        for j, effect in enumerate(var_cols):
            if cause != effect:
                p = causality_matrix[cause][effect]["p_value"]
                matrix[i, j] = -np.log10(max(p, 1e-10))

    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(matrix, cmap="YlOrRd", aspect="auto")
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(var_cols, rotation=45, ha="right")
    ax.set_yticklabels(var_cols)
    ax.set_xlabel("结果变量 (Effect)")
    ax.set_ylabel("原因变量 (Cause)")
    ax.set_title("Granger因果检验 (-log10 p-value)")
    plt.colorbar(im, ax=ax, label="-log10(p)")

    # Annotate significant cells
    for i in range(n):
        for j in range(n):
            if i != j:
                p = causality_matrix[var_cols[i]][var_cols[j]]["p_value"]
                sig_mark = "★" if p < significance else ""
                ax.text(j, i, f"{p:.3f}\n{sig_mark}", ha="center", va="center",
                        fontsize=8)
    plt.tight_layout()
    plot_path = _generate_output_path("granger_heatmap", "png")
    fig.savefig(plot_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    return json.dumps({
        "method": "spatial_granger_causality",
        "variables": var_cols,
        "max_lag": max_lag,
        "significance": significance,
        "causality_matrix": causality_matrix,
        "significant_pairs": significant_pairs,
        "n_significant": len(significant_pairs),
        "plot_path": plot_path,
        "summary": (
            f"Granger因果检验: {len(var_cols)}个变量, "
            f"发现{len(significant_pairs)}对显著因果关系 (α={significance})"
        ),
    }, ensure_ascii=False)


# ====================================================================
#  Tool 5: Geographic Convergent Cross Mapping (GCCM)
# ====================================================================

def geographic_causal_mapping(
    file_path: str,
    cause_col: str,
    effect_col: str,
    lib_sizes: str = "",
    embedding_dim: int = 0,
    weights_type: str = "knn",
    k: int = 8,
) -> str:
    """地理收敛交叉映射因果检验（GCCM）。

    基于动力系统理论和广义嵌入定理，利用空间截面数据推断两个变量之间的因果关系。
    如果变量X因果驱动Y，则从Y的影子流形可以交叉预测X，且预测能力随样本量收敛。

    Args:
        file_path: 空间数据文件路径（需含几何信息）
        cause_col: 候选原因变量列名
        effect_col: 候选结果变量列名
        lib_sizes: 库大小序列，逗号分隔（默认自动生成）
        embedding_dim: 嵌入维度E（0=自动选择）
        weights_type: 空间权重类型 knn/queen/distance
        k: KNN邻居数

    Returns:
        JSON string with convergence data, causal direction, and plot path.
    """
    from scipy.spatial import KDTree as KDTreeSci
    from .spatial_statistics import _build_spatial_weights

    _configure_fonts()
    path = _resolve_path(file_path)
    gdf = _load_data(path)

    if not hasattr(gdf, "geometry") or gdf.geometry is None:
        return json.dumps({"error": "GCCM需要空间几何数据"}, ensure_ascii=False)

    for col in [cause_col, effect_col]:
        if col not in gdf.columns:
            return json.dumps({"error": f"缺少列: {col}"}, ensure_ascii=False)

    x = gdf[cause_col].values.astype(float)
    y = gdf[effect_col].values.astype(float)
    n = len(gdf)

    if n < 20:
        return json.dumps({"error": f"样本量太小 ({n}), 需至少20个空间单元"},
                          ensure_ascii=False)

    # Build spatial weights to get neighbor indices
    gdf_proj, w = _build_spatial_weights(gdf, weights_type=weights_type, k=k)
    neighbor_dict = w.neighbors  # {i: [j1, j2, ...]}

    # Auto-select embedding dimension E via simplex projection
    def _simplex_predict(values, neighbors, E, idx_lib, idx_pred):
        """Simplex projection: predict values at idx_pred using idx_lib."""
        if len(idx_lib) < E + 2:
            return np.full(len(idx_pred), np.nan)

        # Build E-dimensional embeddings using spatial neighbors
        embeddings = np.zeros((n, E))
        for i in range(n):
            nbrs = list(neighbors.get(i, []))
            for e in range(E):
                if e < len(nbrs):
                    embeddings[i, e] = values[nbrs[e]]
                else:
                    embeddings[i, e] = values[i]  # self-fill

        lib_emb = embeddings[idx_lib]
        pred_emb = embeddings[idx_pred]
        lib_vals = values[idx_lib]

        if len(lib_emb) == 0 or len(pred_emb) == 0:
            return np.full(len(idx_pred), np.nan)

        tree = KDTreeSci(lib_emb)
        nn = min(E + 1, len(lib_emb))
        dists, idxs = tree.query(pred_emb, k=nn)

        predictions = np.zeros(len(idx_pred))
        for i in range(len(idx_pred)):
            d = dists[i] if dists.ndim > 1 else np.array([dists[i]])
            ix = idxs[i] if idxs.ndim > 1 else np.array([idxs[i]])
            d = np.atleast_1d(d)
            ix = np.atleast_1d(ix)
            # Exponential distance weights
            min_d = max(d.min(), 1e-10)
            wts = np.exp(-d / min_d)
            wts = wts / max(wts.sum(), 1e-10)
            predictions[i] = np.dot(wts, lib_vals[ix])
        return predictions

    def _cross_map_rho(x_vals, y_vals, neighbors, E, lib_idx):
        """Cross-mapping: use y's manifold to predict x.

        If x causes y, then y's shadow manifold contains information about x,
        so y cross-map-predicts x with skill.
        """
        all_idx = np.arange(n)
        pred_idx = np.setdiff1d(all_idx, lib_idx)
        if len(pred_idx) < 5:
            pred_idx = lib_idx  # use leave-one-out within lib

        # Predict x from y's embedding
        x_pred = _simplex_predict(y_vals, neighbors, E, lib_idx, pred_idx)
        x_true = x_vals[pred_idx]

        valid = ~np.isnan(x_pred) & ~np.isnan(x_true)
        if valid.sum() < 3:
            return 0.0
        return float(np.corrcoef(x_true[valid], x_pred[valid])[0, 1])

    # Auto-select E
    if embedding_dim <= 0:
        rng = np.random.RandomState(42)
        lib_half = rng.choice(n, size=n // 2, replace=False)
        best_E, best_rho = 2, -1
        for E_try in range(2, min(k, 10) + 1):
            rho = _cross_map_rho(x, y, neighbor_dict, E_try, lib_half)
            if rho > best_rho:
                best_rho, best_E = rho, E_try
        E = best_E
    else:
        E = embedding_dim

    # Library sizes for convergence test
    if lib_sizes:
        L_list = [int(s.strip()) for s in lib_sizes.split(",") if s.strip()]
    else:
        L_list = sorted(set(
            [int(x_) for x_ in np.linspace(max(E + 2, 10), n, min(8, n // 5 + 1))]
        ))
        if L_list[-1] != n:
            L_list.append(n)

    # Convergence test: for each library size, compute cross-map rho
    rng = np.random.RandomState(42)
    rho_x_causes_y = []  # y cross-maps x (tests if x→y)
    rho_y_causes_x = []  # x cross-maps y (tests if y→x)

    n_reps = 20
    for L in L_list:
        rhos_xy, rhos_yx = [], []
        for _ in range(n_reps):
            lib = rng.choice(n, size=min(L, n), replace=False)
            rxy = _cross_map_rho(x, y, neighbor_dict, E, lib)
            ryx = _cross_map_rho(y, x, neighbor_dict, E, lib)
            rhos_xy.append(rxy)
            rhos_yx.append(ryx)
        rho_x_causes_y.append(float(np.mean(rhos_xy)))
        rho_y_causes_x.append(float(np.mean(rhos_yx)))

    # Determine causal direction
    final_rho_xy = rho_x_causes_y[-1] if rho_x_causes_y else 0
    final_rho_yx = rho_y_causes_x[-1] if rho_y_causes_x else 0

    # Convergence: check if rho increases with library size
    def _is_convergent(rhos):
        if len(rhos) < 3:
            return False
        # Spearman correlation with library size index
        from scipy.stats import spearmanr
        corr, p = spearmanr(range(len(rhos)), rhos)
        return corr > 0.3 and p < 0.1

    xy_converges = _is_convergent(rho_x_causes_y)
    yx_converges = _is_convergent(rho_y_causes_x)

    if xy_converges and not yx_converges:
        direction = f"{cause_col} → {effect_col}"
    elif yx_converges and not xy_converges:
        direction = f"{effect_col} → {cause_col}"
    elif xy_converges and yx_converges:
        direction = "双向因果 (bidirectional)"
    else:
        direction = "未检测到显著因果关系"

    # Save convergence data
    conv_df = pd.DataFrame({
        "library_size": L_list,
        f"{cause_col}_causes_{effect_col}_rho": rho_x_causes_y,
        f"{effect_col}_causes_{cause_col}_rho": rho_y_causes_x,
    })
    conv_path = _generate_output_path("gccm_convergence", "csv")
    conv_df.to_csv(conv_path, index=False)

    # Plot
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(L_list, rho_x_causes_y, "o-", color="steelblue",
            label=f"{cause_col} → {effect_col} (ρ={final_rho_xy:.3f})")
    ax.plot(L_list, rho_y_causes_x, "s--", color="darkorange",
            label=f"{effect_col} → {cause_col} (ρ={final_rho_yx:.3f})")
    ax.set_xlabel("库大小 (Library Size)")
    ax.set_ylabel("交叉映射预测相关系数 ρ")
    ax.set_title(f"GCCM收敛检验 — {direction}")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plot_path = _generate_output_path("gccm_convergence", "png")
    fig.savefig(plot_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    return json.dumps({
        "method": "geographic_causal_mapping",
        "embedding_dim": E,
        "x_causes_y_rho": round(final_rho_xy, 4),
        "y_causes_x_rho": round(final_rho_yx, 4),
        "x_causes_y_converges": bool(xy_converges),
        "y_causes_x_converges": bool(yx_converges),
        "causal_direction": direction,
        "library_sizes": L_list,
        "convergence_data_path": conv_path,
        "convergence_plot_path": plot_path,
        "summary": (
            f"GCCM因果检验: {direction}, "
            f"ρ({cause_col}→{effect_col})={final_rho_xy:.3f}, "
            f"ρ({effect_col}→{cause_col})={final_rho_yx:.3f}"
        ),
    }, ensure_ascii=False)


# ====================================================================
#  Tool 6: Causal Forest (T-learner)
# ====================================================================

def causal_forest_analysis(
    file_path: str,
    treatment_col: str,
    outcome_col: str,
    feature_cols: str,
    spatial_col: str = "",
) -> str:
    """因果森林异质处理效应分析（Causal Forest / T-Learner）。

    估计条件平均处理效应(CATE)在不同空间单元/个体间的异质性分布。
    使用T-learner方法：分别训练处理组和对照组的预测模型，差异即CATE。

    Args:
        file_path: 数据文件路径
        treatment_col: 二元处理变量列名（0/1）
        outcome_col: 结果变量列名
        feature_cols: 特征变量列名，逗号分隔
        spatial_col: 空间分组列名（可选，用于空间异质性可视化）

    Returns:
        JSON string with ATE, CATE distribution, feature importance, and map.
    """
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.model_selection import KFold
    from scipy.stats import ttest_ind

    _configure_fonts()
    path = _resolve_path(file_path)
    gdf = _load_data(path)

    feat_cols = _parse_columns(feature_cols)
    required = [treatment_col, outcome_col] + feat_cols
    missing = [c for c in required if c not in gdf.columns]
    if missing:
        return json.dumps({"error": f"缺少列: {missing}"}, ensure_ascii=False)

    treatment = gdf[treatment_col].values.astype(int)
    outcome = gdf[outcome_col].values.astype(float)
    X = gdf[feat_cols].fillna(gdf[feat_cols].median()).values

    t_mask = treatment == 1
    c_mask = treatment == 0

    if t_mask.sum() < 10 or c_mask.sum() < 10:
        return json.dumps({"error": "处理组或对照组样本不足（<10）"}, ensure_ascii=False)

    # T-learner with cross-fitting
    n = len(gdf)
    cate = np.zeros(n)
    kf = KFold(n_splits=5, shuffle=True, random_state=42)

    for train_idx, test_idx in kf.split(X):
        # Train treated model on treated units in train fold
        t_train = np.intersect1d(train_idx, np.where(t_mask)[0])
        c_train = np.intersect1d(train_idx, np.where(c_mask)[0])

        if len(t_train) < 5 or len(c_train) < 5:
            # Fallback: use all train data
            t_train = np.where(t_mask)[0]
            c_train = np.where(c_mask)[0]

        model_t = GradientBoostingRegressor(
            n_estimators=100, max_depth=4, learning_rate=0.1, random_state=42,
        )
        model_c = GradientBoostingRegressor(
            n_estimators=100, max_depth=4, learning_rate=0.1, random_state=42,
        )
        model_t.fit(X[t_train], outcome[t_train])
        model_c.fit(X[c_train], outcome[c_train])

        # Predict CATE for test fold
        mu1 = model_t.predict(X[test_idx])
        mu0 = model_c.predict(X[test_idx])
        cate[test_idx] = mu1 - mu0

    ate = float(cate.mean())
    ate_se = float(cate.std() / np.sqrt(n))
    ci_lower = ate - 1.96 * ate_se
    ci_upper = ate + 1.96 * ate_se

    # Feature importance via permutation
    # Train final models on all data
    model_t_full = GradientBoostingRegressor(
        n_estimators=100, max_depth=4, learning_rate=0.1, random_state=42,
    )
    model_c_full = GradientBoostingRegressor(
        n_estimators=100, max_depth=4, learning_rate=0.1, random_state=42,
    )
    model_t_full.fit(X[t_mask], outcome[t_mask])
    model_c_full.fit(X[c_mask], outcome[c_mask])

    importance = {}
    for fi, col in enumerate(feat_cols):
        imp_t = model_t_full.feature_importances_[fi] if fi < len(model_t_full.feature_importances_) else 0
        imp_c = model_c_full.feature_importances_[fi] if fi < len(model_c_full.feature_importances_) else 0
        importance[col] = round(float((imp_t + imp_c) / 2), 4)

    # Heterogeneity test: split by median CATE
    high_cate = cate > np.median(cate)
    if high_cate.sum() > 2 and (~high_cate).sum() > 2:
        _, het_p = ttest_ind(cate[high_cate], cate[~high_cate])
        het_p = float(het_p)
    else:
        het_p = 1.0

    # Save CATE data
    cate_df = gdf.copy()
    cate_df["cate"] = cate
    cate_data_path = _generate_output_path("causal_forest_cate", "csv")
    if hasattr(cate_df, "geometry"):
        cate_df.drop(columns=["geometry"], errors="ignore").to_csv(
            cate_data_path, index=False)
    else:
        cate_df.to_csv(cate_data_path, index=False)

    # Visualization
    has_geom = hasattr(gdf, "geometry") and gdf.geometry is not None and not gdf.geometry.isna().all()
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # Plot 1: CATE distribution
    axes[0].hist(cate, bins=30, color="steelblue", alpha=0.7, edgecolor="white")
    axes[0].axvline(x=ate, color="red", linestyle="--", linewidth=2,
                    label=f"ATE={ate:.2f}")
    axes[0].set_xlabel("条件平均处理效应 (CATE)")
    axes[0].set_ylabel("频数")
    axes[0].set_title("CATE分布")
    axes[0].legend()

    # Plot 2: CATE spatial map or by spatial group
    cate_map_path = ""
    if has_geom:
        gdf_plot = gdf.copy()
        gdf_plot["cate"] = cate
        gdf_plot.plot(column="cate", cmap="RdYlBu_r", legend=True, ax=axes[1],
                      edgecolor="gray", linewidth=0.3)
        axes[1].set_title("CATE空间分布")
        axes[1].set_axis_off()
    elif spatial_col and spatial_col in gdf.columns:
        cate_df_group = pd.DataFrame({"group": gdf[spatial_col], "cate": cate})
        group_means = cate_df_group.groupby("group")["cate"].mean()
        axes[1].bar(range(len(group_means)), group_means.values,
                    tick_label=group_means.index.astype(str))
        axes[1].set_xlabel(spatial_col)
        axes[1].set_ylabel("平均CATE")
        axes[1].set_title("分组CATE")
    else:
        axes[1].text(0.5, 0.5, "无几何/分组信息", ha="center", va="center",
                     transform=axes[1].transAxes)
        axes[1].set_title("CATE空间分布（不可用）")

    plt.tight_layout()
    plot_path = _generate_output_path("causal_forest_plot", "png")
    fig.savefig(plot_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    if has_geom:
        cate_map_path = plot_path

    return json.dumps({
        "method": "causal_forest_analysis",
        "ate": round(ate, 4),
        "ate_se": round(ate_se, 4),
        "ci_lower": round(ci_lower, 4),
        "ci_upper": round(ci_upper, 4),
        "cate_mean": round(ate, 4),
        "cate_std": round(float(cate.std()), 4),
        "cate_min": round(float(cate.min()), 4),
        "cate_max": round(float(cate.max()), 4),
        "heterogeneity_pvalue": round(het_p, 6),
        "feature_importance": importance,
        "n_treated": int(t_mask.sum()),
        "n_control": int(c_mask.sum()),
        "cate_data_path": cate_data_path,
        "cate_map_path": cate_map_path,
        "diagnostic_plot_path": plot_path,
        "summary": (
            f"因果森林: ATE={ate:.2f}±{ate_se:.2f}, "
            f"CATE范围[{cate.min():.2f}, {cate.max():.2f}], "
            f"异质性检验p={het_p:.4f}"
        ),
    }, ensure_ascii=False)
