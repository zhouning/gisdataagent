"""
Spectral Indices Library — 15+ remote sensing indices with auto-recommendation.

Provides:
- SPECTRAL_INDICES registry: formula, bands, description, category
- calculate_spectral_index(): compute any registered index on a raster
- list_spectral_indices(): list all available indices
- recommend_indices(): suggest indices based on task description
- assess_cloud_cover(): estimate cloud coverage from raster brightness
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import numpy as np

from .observability import get_logger

logger = get_logger("spectral_indices")


# ---------------------------------------------------------------------------
# Index Registry
# ---------------------------------------------------------------------------

@dataclass
class SpectralIndex:
    """Definition of a spectral index."""
    name: str
    formula: str  # numpy expression with band variable names
    bands: dict  # {variable_name: band_number (1-based)}
    description: str = ""
    category: str = "vegetation"  # vegetation, water, urban, fire, soil, snow
    value_range: tuple = (-1.0, 1.0)
    sentinel2_bands: dict = field(default_factory=dict)  # S2 band mapping


SPECTRAL_INDICES: dict[str, SpectralIndex] = {
    # --- Vegetation ---
    "ndvi": SpectralIndex(
        name="NDVI", formula="(nir-red)/(nir+red)",
        bands={"red": 3, "nir": 4},
        description="归一化植被指数 — 植被覆盖与健康状况",
        category="vegetation",
        sentinel2_bands={"red": "B04", "nir": "B08"},
    ),
    "evi": SpectralIndex(
        name="EVI", formula="2.5*(nir-red)/(nir+6*red-7.5*blue+1)",
        bands={"blue": 1, "red": 3, "nir": 4},
        description="增强型植被指数 — 减少大气和土壤背景影响",
        category="vegetation",
        sentinel2_bands={"blue": "B02", "red": "B04", "nir": "B08"},
    ),
    "savi": SpectralIndex(
        name="SAVI", formula="1.5*(nir-red)/(nir+red+0.5)",
        bands={"red": 3, "nir": 4},
        description="土壤调节植被指数 — 减少土壤亮度影响",
        category="vegetation",
        sentinel2_bands={"red": "B04", "nir": "B08"},
    ),
    "gndvi": SpectralIndex(
        name="GNDVI", formula="(nir-green)/(nir+green)",
        bands={"green": 2, "nir": 4},
        description="绿色归一化植被指数 — 对叶绿素浓度更敏感",
        category="vegetation",
        sentinel2_bands={"green": "B03", "nir": "B08"},
    ),
    "arvi": SpectralIndex(
        name="ARVI", formula="(nir-(2*red-blue))/(nir+(2*red-blue))",
        bands={"blue": 1, "red": 3, "nir": 4},
        description="大气阻抗植被指数 — 抗大气散射",
        category="vegetation",
        sentinel2_bands={"blue": "B02", "red": "B04", "nir": "B08"},
    ),
    "ndre": SpectralIndex(
        name="NDRE", formula="(nir-rededge)/(nir+rededge)",
        bands={"nir": 4, "rededge": 5},
        description="归一化红边差值指数 — 作物氮素状态监测",
        category="vegetation",
        sentinel2_bands={"nir": "B08", "rededge": "B05"},
    ),
    # --- Water ---
    "ndwi": SpectralIndex(
        name="NDWI", formula="(green-nir)/(green+nir)",
        bands={"green": 2, "nir": 4},
        description="归一化水体指数 — 水体检测与提取",
        category="water",
        sentinel2_bands={"green": "B03", "nir": "B08"},
    ),
    "mndwi": SpectralIndex(
        name="MNDWI", formula="(green-swir1)/(green+swir1)",
        bands={"green": 2, "swir1": 5},
        description="改进型归一化水体指数 — 抑制建筑噪声",
        category="water",
        sentinel2_bands={"green": "B03", "swir1": "B11"},
    ),
    # --- Urban / Built-up ---
    "ndbi": SpectralIndex(
        name="NDBI", formula="(swir1-nir)/(swir1+nir)",
        bands={"nir": 4, "swir1": 5},
        description="归一化建筑指数 — 建成区检测",
        category="urban",
        sentinel2_bands={"nir": "B08", "swir1": "B11"},
    ),
    "bsi": SpectralIndex(
        name="BSI", formula="((swir1+red)-(nir+blue))/((swir1+red)+(nir+blue))",
        bands={"blue": 1, "red": 3, "nir": 4, "swir1": 5},
        description="裸土指数 — 裸地与建筑混合区识别",
        category="urban",
        sentinel2_bands={"blue": "B02", "red": "B04", "nir": "B08", "swir1": "B11"},
    ),
    # --- Fire / Burn ---
    "nbr": SpectralIndex(
        name="NBR", formula="(nir-swir2)/(nir+swir2)",
        bands={"nir": 4, "swir2": 6},
        description="归一化燃烧比 — 火烧迹地检测",
        category="fire",
        sentinel2_bands={"nir": "B08", "swir2": "B12"},
    ),
    # --- Snow ---
    "ndsi": SpectralIndex(
        name="NDSI", formula="(green-swir1)/(green+swir1)",
        bands={"green": 2, "swir1": 5},
        description="归一化积雪指数 — 积雪覆盖检测",
        category="snow",
        sentinel2_bands={"green": "B03", "swir1": "B11"},
    ),
    # --- Soil ---
    "ci": SpectralIndex(
        name="CI", formula="(red-green)/(red+green)",
        bands={"red": 3, "green": 2},
        description="颜色指数 — 土壤颜色/铁含量",
        category="soil",
        sentinel2_bands={"red": "B04", "green": "B03"},
    ),
    # --- Derived ---
    "lai": SpectralIndex(
        name="LAI", formula="3.618*((2.5*(nir-red)/(nir+6*red-7.5*blue+1)))-0.118",
        bands={"blue": 1, "red": 3, "nir": 4},
        description="叶面积指数 — 由 EVI 线性回归估算",
        category="vegetation",
        value_range=(0, 8),
        sentinel2_bands={"blue": "B02", "red": "B04", "nir": "B08"},
    ),
    "ndmi": SpectralIndex(
        name="NDMI", formula="(nir-swir1)/(nir+swir1)",
        bands={"nir": 4, "swir1": 5},
        description="归一化差值水分指数 — 植被水分含量",
        category="vegetation",
        sentinel2_bands={"nir": "B08", "swir1": "B11"},
    ),
}

# Category → keyword mapping for recommendation
_CATEGORY_KEYWORDS = {
    "vegetation": ["植被", "vegetation", "ndvi", "绿化", "农田", "作物", "crop", "forest", "林地", "草地"],
    "water": ["水体", "water", "河流", "湖泊", "river", "lake", "湿地", "wetland", "洪水", "flood"],
    "urban": ["建筑", "城市", "built-up", "urban", "建成区", "不透水面", "impervious"],
    "fire": ["火灾", "fire", "burn", "燃烧", "火烧迹地"],
    "snow": ["积雪", "snow", "冰川", "glacier"],
    "soil": ["土壤", "soil", "裸地", "bare"],
}


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

def calculate_spectral_index(raster_path: str, index_name: str,
                             band_overrides: str = "") -> str:
    """计算遥感光谱指数。

    支持 15+ 指数: NDVI/EVI/SAVI/NDWI/NDBI/NBR/MNDWI/BSI/NDSI/GNDVI/ARVI/NDRE/LAI/CI/NDMI。
    自动从栅格文件读取波段，按公式计算输出单波段 GeoTIFF。

    Args:
        raster_path: 输入栅格文件路径 (GeoTIFF, 多波段)
        index_name: 指数名称 (如 ndvi, evi, ndwi)
        band_overrides: 可选, JSON 格式波段覆盖 (如 {"red": 4, "nir": 8})
    Returns:
        JSON: {status, index, output_path, statistics, description}
    """
    idx_key = index_name.lower().strip()
    if idx_key not in SPECTRAL_INDICES:
        available = ", ".join(sorted(SPECTRAL_INDICES.keys()))
        return json.dumps({"status": "error",
                           "message": f"Unknown index '{index_name}'. Available: {available}"},
                          ensure_ascii=False)

    idx = SPECTRAL_INDICES[idx_key]

    try:
        import rasterio
        from .gis_processors import _generate_output_path

        # Parse band overrides
        band_map = dict(idx.bands)
        if band_overrides:
            try:
                overrides = json.loads(band_overrides)
                band_map.update({k: int(v) for k, v in overrides.items()})
            except (json.JSONDecodeError, ValueError):
                pass

        with rasterio.open(raster_path) as src:
            # Read required bands
            band_data = {}
            for var_name, band_num in band_map.items():
                if band_num > src.count:
                    return json.dumps({"status": "error",
                                       "message": f"Band {band_num} ({var_name}) exceeds raster band count ({src.count})"},
                                      ensure_ascii=False)
                band_data[var_name] = src.read(band_num).astype(np.float32)

            # Evaluate formula
            # Replace variable names with array references
            local_vars = {k: v for k, v in band_data.items()}
            # Suppress division warnings
            with np.errstate(divide="ignore", invalid="ignore"):
                result = eval(idx.formula, {"__builtins__": {}, "np": np}, local_vars)  # noqa: S307

            result = np.where(np.isfinite(result), result, np.nan)

            # Statistics
            valid = result[np.isfinite(result)]
            stats = {
                "mean": float(np.nanmean(valid)) if len(valid) > 0 else None,
                "std": float(np.nanstd(valid)) if len(valid) > 0 else None,
                "min": float(np.nanmin(valid)) if len(valid) > 0 else None,
                "max": float(np.nanmax(valid)) if len(valid) > 0 else None,
                "valid_pixels": int(len(valid)),
                "total_pixels": int(result.size),
            }

            # Write output
            out_path = _generate_output_path(f"{idx_key}_index", ".tif")
            profile = src.profile.copy()
            profile.update(count=1, dtype="float32", nodata=np.nan)
            with rasterio.open(out_path, "w", **profile) as dst:
                dst.write(result, 1)

        return json.dumps({
            "status": "success",
            "index": idx.name,
            "description": idx.description,
            "category": idx.category,
            "output_path": out_path,
            "statistics": stats,
        }, ensure_ascii=False, default=str)

    except ImportError:
        return json.dumps({"status": "error", "message": "rasterio not installed"})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def list_spectral_indices() -> str:
    """列出所有可用的光谱指数及其描述、类别。

    Returns:
        JSON 列表: [{name, description, category, formula, bands}]
    """
    indices = []
    for key, idx in sorted(SPECTRAL_INDICES.items()):
        indices.append({
            "name": idx.name,
            "key": key,
            "description": idx.description,
            "category": idx.category,
            "formula": idx.formula,
            "bands": idx.bands,
        })
    return json.dumps(indices, ensure_ascii=False)


def recommend_indices(task_description: str) -> str:
    """根据任务描述推荐合适的光谱指数。

    Args:
        task_description: 自然语言分析任务描述
    Returns:
        JSON: {recommended: [{name, description, reason}]}
    """
    task_lower = task_description.lower()
    scores: dict[str, float] = {}

    for category, keywords in _CATEGORY_KEYWORDS.items():
        match_count = sum(1 for kw in keywords if kw.lower() in task_lower)
        if match_count > 0:
            for key, idx in SPECTRAL_INDICES.items():
                if idx.category == category:
                    scores[key] = scores.get(key, 0) + match_count

    # Sort by score, take top 5
    recommended = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:5]

    if not recommended:
        # Default: recommend NDVI + EVI (most versatile)
        recommended = [("ndvi", 1), ("evi", 1)]

    results = []
    for key, score in recommended:
        idx = SPECTRAL_INDICES[key]
        results.append({
            "name": idx.name,
            "key": key,
            "description": idx.description,
            "category": idx.category,
            "relevance_score": score,
        })

    return json.dumps({"recommended": results}, ensure_ascii=False)


def assess_cloud_cover(raster_path: str, bright_threshold: float = 0.3) -> str:
    """评估栅格数据的云覆盖率。

    使用亮度阈值法粗略估计云覆盖 (适用于无 SCL 波段的影像)。
    高亮度像素占比作为云覆盖率近似。

    Args:
        raster_path: 栅格文件路径
        bright_threshold: 亮度阈值 (0-1)，高于此值视为云/高亮
    Returns:
        JSON: {cloud_percentage, usable, recommendation}
    """
    try:
        import rasterio

        with rasterio.open(raster_path) as src:
            # Use first band for brightness estimation
            data = src.read(1).astype(np.float32)

            # Normalize to 0-1 if needed
            valid = data[data != src.nodata] if src.nodata is not None else data.ravel()
            if len(valid) == 0:
                return json.dumps({"status": "error", "message": "No valid pixels"})

            dmax = np.nanmax(valid)
            if dmax > 1:
                valid = valid / dmax

            bright_pixels = np.sum(valid > bright_threshold)
            total = len(valid)
            cloud_pct = float(bright_pixels / total * 100) if total > 0 else 0

            usable = cloud_pct < 30
            if cloud_pct < 10:
                rec = "优质影像，可直接分析"
            elif cloud_pct < 30:
                rec = "云覆盖可接受，建议使用云掩膜处理"
            elif cloud_pct < 60:
                rec = "云覆盖较高，建议更换时相或使用 SAR 数据"
            else:
                rec = "云覆盖严重，建议更换影像"

            return json.dumps({
                "status": "success",
                "cloud_percentage": round(cloud_pct, 1),
                "usable": usable,
                "recommendation": rec,
                "total_pixels": int(total),
                "bright_pixels": int(bright_pixels),
            }, ensure_ascii=False)

    except ImportError:
        return json.dumps({"status": "error", "message": "rasterio not installed"})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)
