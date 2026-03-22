"""DataCleaningToolset — 数据清洗工具集 (v14.5).

提供空值填充、编码映射、字段重命名、类型转换、异常值裁剪、CRS 统一、
缺失字段补齐等数据治理中的清洗操作。输出清洗后的新文件（不修改原文件）。
"""

import json
import logging
import os

import geopandas as gpd
import pandas as pd
import numpy as np

from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..gis_processors import _resolve_path, _generate_output_path
from ..utils import _load_spatial_data

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

def fill_null_values(
    file_path: str,
    field: str,
    strategy: str = "default",
    fill_value: str = "",
) -> str:
    """填充指定字段的空值。

    Args:
        file_path: 数据文件路径。
        field: 要填充的字段名。
        strategy: 填充策略 — "default"(指定值) | "mean"(均值) | "median"(中位数) | "mode"(众数) | "ffill"(前向填充)。
        fill_value: strategy 为 "default" 时使用的填充值。

    Returns:
        清洗后文件路径和填充统计。
    """
    try:
        gdf = _load_spatial_data(file_path)
        if field not in gdf.columns:
            return json.dumps({"status": "error", "message": f"字段 '{field}' 不存在。可用字段: {list(gdf.columns)}"},
                              ensure_ascii=False)

        null_count = int(gdf[field].isna().sum())
        if null_count == 0:
            return json.dumps({"status": "ok", "message": f"字段 '{field}' 无空值，无需填充", "null_count": 0},
                              ensure_ascii=False)

        if strategy == "mean":
            gdf[field] = gdf[field].fillna(gdf[field].mean())
        elif strategy == "median":
            gdf[field] = gdf[field].fillna(gdf[field].median())
        elif strategy == "mode":
            mode_val = gdf[field].mode()
            gdf[field] = gdf[field].fillna(mode_val.iloc[0] if not mode_val.empty else fill_value)
        elif strategy == "ffill":
            gdf[field] = gdf[field].ffill()
        else:  # default
            gdf[field] = gdf[field].fillna(fill_value)

        out = _generate_output_path("cleaned", "gpkg")
        gdf.to_file(out, driver="GPKG")
        return json.dumps({"status": "ok", "output": out, "field": field,
                           "null_filled": null_count, "strategy": strategy},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def map_field_codes(
    file_path: str,
    field: str,
    mapping_table: str,
    unmapped_strategy: str = "keep",
) -> str:
    """编码映射转换：将字段值按映射表转换（如 CLCD 编码 → GB/T 21010 编码）。

    Args:
        file_path: 数据文件路径。
        field: 要映射的字段名。
        mapping_table: 映射ID（如 "clcd_to_gbt21010"，自动从标准库加载）或 JSON映射表（如 '{"1": "0101"}'）。
        unmapped_strategy: 未匹配值处理策略 — "keep"(保留原值) | "null"(设为空) | "error"(报错)。
        field: 要映射的字段名。
        mapping_table: JSON映射表，如 '{"1": "0101", "2": "0201"}'。
        unmapped_strategy: 未匹配值处理策略 — "keep"(保留原值) | "null"(设为空) | "error"(报错)。

    Returns:
        清洗后文件路径和映射统计。
    """
    try:
        gdf = _load_spatial_data(file_path)
        if field not in gdf.columns:
            return json.dumps({"status": "error", "message": f"字段 '{field}' 不存在"},
                              ensure_ascii=False)

        # Resolve mapping: mapping_id or inline JSON
        if isinstance(mapping_table, str) and not mapping_table.strip().startswith("{"):
            from ..standard_registry import StandardRegistry
            mapping_data = StandardRegistry.get_code_mapping(mapping_table.strip())
            if mapping_data and "mapping" in mapping_data:
                mapping = mapping_data["mapping"]
            else:
                return json.dumps({"status": "error", "message": f"未找到映射表: {mapping_table}"},
                                  ensure_ascii=False)
        else:
            mapping = json.loads(mapping_table) if isinstance(mapping_table, str) else mapping_table

        mapped_count = 0
        unmapped_values = []

        str_mapping = {str(k): v for k, v in mapping.items()}
        gdf[field] = gdf[field].astype(str)
        new_values = gdf[field].map(str_mapping)

        if unmapped_strategy == "keep":
            gdf[field] = new_values.fillna(gdf[field])
        elif unmapped_strategy == "null":
            gdf[field] = new_values
        else:  # error
            missing = set(gdf[field].unique()) - set(str_mapping.keys())
            if missing:
                return json.dumps({"status": "error", "message": f"未映射值: {list(missing)[:10]}"},
                                  ensure_ascii=False)
            gdf[field] = new_values

        mapped_count = int(new_values.notna().sum())
        unmapped_values = list(set(gdf[field].unique()) - set(str_mapping.values()))[:10]

        out = _generate_output_path("mapped", "gpkg")
        gdf.to_file(out, driver="GPKG")
        return json.dumps({"status": "ok", "output": out, "field": field,
                           "mapped_count": mapped_count, "unmapped_sample": unmapped_values},
                          ensure_ascii=False)
    except json.JSONDecodeError:
        return json.dumps({"status": "error", "message": "mapping_table 不是合法的JSON"},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def rename_fields(file_path: str, field_mapping: str) -> str:
    """批量重命名数据字段。

    Args:
        file_path: 数据文件路径。
        field_mapping: JSON映射表，如 '{"old_name": "new_name", "DL": "DLBM"}'。

    Returns:
        清洗后文件路径和重命名统计。
    """
    try:
        gdf = _load_spatial_data(file_path)
        mapping = json.loads(field_mapping) if isinstance(field_mapping, str) else field_mapping

        valid = {k: v for k, v in mapping.items() if k in gdf.columns}
        if not valid:
            return json.dumps({"status": "error",
                               "message": f"映射中的字段均不存在。可用字段: {list(gdf.columns)}"},
                              ensure_ascii=False)

        gdf = gdf.rename(columns=valid)
        out = _generate_output_path("renamed", "gpkg")
        gdf.to_file(out, driver="GPKG")
        return json.dumps({"status": "ok", "output": out, "renamed": valid,
                           "skipped": [k for k in mapping if k not in valid]},
                          ensure_ascii=False)
    except json.JSONDecodeError:
        return json.dumps({"status": "error", "message": "field_mapping 不是合法的JSON"},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def cast_field_type(file_path: str, field: str, target_type: str) -> str:
    """安全转换字段数据类型。

    Args:
        file_path: 数据文件路径。
        field: 要转换的字段名。
        target_type: 目标类型 — "string" | "integer" | "float" | "date"。

    Returns:
        清洗后文件路径和转换统计（含失败行数）。
    """
    try:
        gdf = _load_spatial_data(file_path)
        if field not in gdf.columns:
            return json.dumps({"status": "error", "message": f"字段 '{field}' 不存在"},
                              ensure_ascii=False)

        original_type = str(gdf[field].dtype)
        failed_count = 0

        if target_type == "string":
            gdf[field] = gdf[field].astype(str)
        elif target_type == "integer":
            numeric = pd.to_numeric(gdf[field], errors="coerce")
            failed_count = int(numeric.isna().sum() - gdf[field].isna().sum())
            gdf[field] = numeric.astype("Int64")
        elif target_type == "float":
            numeric = pd.to_numeric(gdf[field], errors="coerce")
            failed_count = int(numeric.isna().sum() - gdf[field].isna().sum())
            gdf[field] = numeric
        elif target_type == "date":
            dt = pd.to_datetime(gdf[field], errors="coerce")
            failed_count = int(dt.isna().sum() - gdf[field].isna().sum())
            gdf[field] = dt

        out = _generate_output_path("typed", "gpkg")
        gdf.to_file(out, driver="GPKG")
        return json.dumps({"status": "ok", "output": out, "field": field,
                           "from_type": original_type, "to_type": target_type,
                           "conversion_failures": failed_count},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def clip_outliers(
    file_path: str,
    field: str,
    lower: str = "",
    upper: str = "",
    strategy: str = "clip",
) -> str:
    """裁剪或移除数值字段中的异常值。

    Args:
        file_path: 数据文件路径。
        field: 数值字段名。
        lower: 下限（留空不限制）。
        upper: 上限（留空不限制）。
        strategy: 处理策略 — "clip"(截断到边界) | "null"(设为空) | "remove"(删除行)。

    Returns:
        清洗后文件路径和处理统计。
    """
    try:
        gdf = _load_spatial_data(file_path)
        if field not in gdf.columns:
            return json.dumps({"status": "error", "message": f"字段 '{field}' 不存在"},
                              ensure_ascii=False)

        lo = float(lower) if lower else None
        hi = float(upper) if upper else None
        col = pd.to_numeric(gdf[field], errors="coerce")

        mask = pd.Series(False, index=gdf.index)
        if lo is not None:
            mask = mask | (col < lo)
        if hi is not None:
            mask = mask | (col > hi)
        affected = int(mask.sum())

        if strategy == "clip":
            if lo is not None:
                col = col.clip(lower=lo)
            if hi is not None:
                col = col.clip(upper=hi)
            gdf[field] = col
        elif strategy == "null":
            gdf.loc[mask, field] = np.nan
        elif strategy == "remove":
            gdf = gdf[~mask]

        out = _generate_output_path("clipped", "gpkg")
        gdf.to_file(out, driver="GPKG")
        return json.dumps({"status": "ok", "output": out, "field": field,
                           "outliers_affected": affected, "strategy": strategy,
                           "remaining_rows": len(gdf)},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def standardize_crs(file_path: str, target_crs: str = "EPSG:4326") -> str:
    """统一数据坐标参考系。

    Args:
        file_path: 数据文件路径。
        target_crs: 目标坐标系（如 "EPSG:4326"、"EPSG:4490"、"EPSG:32650"），默认 EPSG:4326。

    Returns:
        清洗后文件路径和 CRS 转换信息。
    """
    try:
        gdf = _load_spatial_data(file_path)
        original_crs = str(gdf.crs) if gdf.crs else "Unknown"
        if not gdf.crs:
            gdf = gdf.set_crs(target_crs)
        elif str(gdf.crs) != target_crs:
            gdf = gdf.to_crs(target_crs)
        else:
            return json.dumps({"status": "ok", "message": f"已是目标坐标系 {target_crs}，无需转换"},
                              ensure_ascii=False)

        out = _generate_output_path("crs_std", "gpkg")
        gdf.to_file(out, driver="GPKG")
        return json.dumps({"status": "ok", "output": out,
                           "from_crs": original_crs, "to_crs": target_crs},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def add_missing_fields(file_path: str, standard_id: str) -> str:
    """根据数据标准自动补齐缺失字段（用默认值填充）。

    Args:
        file_path: 数据文件路径。
        standard_id: 标准ID（如 "dltb_2023"），可通过 list_data_standards 查看。

    Returns:
        清洗后文件路径和新增字段列表。
    """
    try:
        from ..standard_registry import StandardRegistry

        std = StandardRegistry.get(standard_id)
        if not std:
            return json.dumps({"status": "error", "message": f"未找到标准: {standard_id}"},
                              ensure_ascii=False)

        gdf = _load_spatial_data(file_path)
        added = []
        for fspec in std.fields:
            if fspec.name not in gdf.columns:
                if fspec.type in ("numeric", "integer", "float"):
                    gdf[fspec.name] = 0
                elif fspec.type == "date":
                    gdf[fspec.name] = None
                else:
                    gdf[fspec.name] = ""
                added.append(fspec.name)

        if not added:
            return json.dumps({"status": "ok", "message": "所有标准字段已存在，无需补齐", "added": []},
                              ensure_ascii=False)

        out = _generate_output_path("fields_added", "gpkg")
        gdf.to_file(out, driver="GPKG")
        return json.dumps({"status": "ok", "output": out, "standard": standard_id,
                           "added_fields": added, "total_fields": len(gdf.columns)},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Toolset class
# ---------------------------------------------------------------------------

_ALL_FUNCS = [
    fill_null_values,
    map_field_codes,
    rename_fields,
    cast_field_type,
    clip_outliers,
    standardize_crs,
    add_missing_fields,
]


class DataCleaningToolset(BaseToolset):
    """Provides data cleaning and transformation tools for governance workflows."""

    def __init__(self, *, tool_filter=None):
        super().__init__(tool_filter=tool_filter)

    async def get_tools(self, readonly_context=None) -> list:
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
