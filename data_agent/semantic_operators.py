"""
Semantic Operator Layer — high-level data operations for L3 Planner.

Operators encapsulate domain knowledge: given a DataProfile, they auto-select
strategies and compose tool calls.  The Planner works with operators instead
of calling 200+ low-level tools directly.

Four operators: Clean, Integrate, Analyze, Visualize.
"""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from .agent_composer import DataProfile, extract_profile
from .observability import get_logger

logger = get_logger("semantic_operators")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    """A planned tool invocation."""
    tool_name: str
    kwargs: dict = field(default_factory=dict)
    description: str = ""


@dataclass
class OperatorPlan:
    """Plan produced by an operator's plan() method."""
    operator_name: str
    strategy: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    estimated_steps: int = 0
    precondition_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "operator": self.operator_name,
            "strategy": self.strategy,
            "steps": [{"tool": tc.tool_name, "kwargs": tc.kwargs, "desc": tc.description}
                      for tc in self.tool_calls],
            "estimated_steps": self.estimated_steps,
            "warnings": self.precondition_warnings,
        }


@dataclass
class OperatorResult:
    """Result returned after operator execution."""
    status: str  # "success" | "partial" | "error"
    output_files: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    summary: str = ""
    next_steps: list[str] = field(default_factory=list)
    details: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "output_files": self.output_files,
            "metrics": self.metrics,
            "summary": self.summary,
            "next_steps": self.next_steps,
            "details": self.details,
        }


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class SemanticOperator(ABC):
    """Base class for all semantic operators."""

    name: str = ""
    description: str = ""

    @abstractmethod
    def plan(self, data_profile: DataProfile, task_description: str = "") -> OperatorPlan:
        """Produce an execution plan based on data characteristics."""

    @abstractmethod
    def execute(self, plan: OperatorPlan, context: dict | None = None) -> OperatorResult:
        """Execute a plan, calling underlying tool functions."""

    def validate_preconditions(self, data_profile: DataProfile) -> list[str]:
        """Return warnings for unmet preconditions (empty = all good)."""
        return []


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class OperatorRegistry:
    """Singleton registry of semantic operators."""
    _operators: dict[str, SemanticOperator] = {}

    @classmethod
    def register(cls, operator: SemanticOperator) -> None:
        cls._operators[operator.name] = operator

    @classmethod
    def get(cls, name: str) -> SemanticOperator | None:
        return cls._operators.get(name)

    @classmethod
    def list_all(cls) -> list[dict]:
        return [{"name": op.name, "description": op.description}
                for op in cls._operators.values()]

    @classmethod
    def reset(cls) -> None:
        cls._operators.clear()


# ---------------------------------------------------------------------------
# Helper: safe tool call execution
# ---------------------------------------------------------------------------

def _safe_call(func, **kwargs) -> dict:
    """Call a tool function, return parsed JSON or error dict."""
    try:
        result = func(**kwargs)
        if isinstance(result, str):
            try:
                return json.loads(result)
            except (json.JSONDecodeError, TypeError):
                return {"status": "success", "raw": result}
        if isinstance(result, dict):
            return result
        return {"status": "success", "raw": str(result)}
    except Exception as e:
        logger.warning("Tool %s failed: %s", func.__name__, e)
        return {"status": "error", "message": str(e)}


def _profile_data(file_path: str) -> tuple[DataProfile, Any]:
    """Extract profile + load GeoDataFrame (best-effort)."""
    profile = extract_profile(file_path)
    gdf = None
    try:
        import geopandas as gpd
        ext = os.path.splitext(file_path)[1].lower()
        if ext in (".shp", ".geojson", ".gpkg", ".kml"):
            gdf = gpd.read_file(file_path, rows=500)
    except Exception:
        pass
    return profile, gdf


# ============================================================================
# CleanOperator
# ============================================================================

class CleanOperator(SemanticOperator):
    """Data cleaning operator — auto-selects cleaning strategy from data profile."""

    name = "clean"
    description = "自动数据清洗: 根据数据特征选择 CRS 标准化/空值填充/字段规范化/PII 脱敏/拓扑修复/异常值处理等策略"

    # Strategy detection thresholds
    NULL_THRESHOLD = 0.05  # >5% nulls trigger null_handling
    PII_PATTERNS = {"phone", "mobile", "idcard", "id_card", "身份证", "电话", "手机", "email", "邮箱"}

    def plan(self, data_profile: DataProfile, task_description: str = "") -> OperatorPlan:
        warnings = self.validate_preconditions(data_profile)
        calls: list[ToolCall] = []
        strategies: list[str] = []

        fp = data_profile.file_path

        # 1. CRS standardization (if CRS present but not standard)
        if data_profile.crs and "4326" not in data_profile.crs and "4490" not in data_profile.crs:
            calls.append(ToolCall("standardize_crs", {"file_path": fp, "target_crs": "EPSG:4490"},
                                  "CRS 转换至 EPSG:4490"))
            strategies.append("crs_standardize")

        # 2. Null handling (detected from profile columns)
        if data_profile.row_count > 0:
            calls.append(ToolCall("auto_fix_defects", {"file_path": fp},
                                  "自动修复缺陷 (空值/拓扑/重复)"))
            strategies.append("auto_fix")

        # 3. PII masking
        cols_lower = {c.lower() for c in data_profile.columns}
        pii_cols = cols_lower & self.PII_PATTERNS
        if pii_cols:
            calls.append(ToolCall("mask_sensitive_fields_tool",
                                  {"file_path": fp, "field_rules": json.dumps({c: "mask" for c in pii_cols})},
                                  "PII 字段脱敏"))
            strategies.append("masking")

        # 4. Standard validation (if task mentions standard)
        if any(kw in task_description for kw in ("标准", "standard", "GB", "DLTB", "规范")):
            std_id = "dltb_2023" if "DLTB" in task_description.upper() else "gb_t_21010_2017"
            calls.append(ToolCall("validate_against_standard",
                                  {"file_path": fp, "standard_id": std_id},
                                  f"按 {std_id} 标准校验"))
            calls.append(ToolCall("add_missing_fields",
                                  {"file_path": fp, "standard_id": std_id},
                                  "补齐标准缺失字段"))
            strategies.append("standard_validate")

        # 5. Defect classification
        if data_profile.geometry_types:
            calls.append(ToolCall("classify_defects", {"file_path": fp},
                                  "缺陷分类 (GB/T 24356)"))
            strategies.append("defect_classify")

        strategy = "+".join(strategies) if strategies else "basic_audit"
        if not calls:
            calls.append(ToolCall("auto_fix_defects", {"file_path": fp},
                                  "基础自动修复"))

        return OperatorPlan(
            operator_name=self.name,
            strategy=strategy,
            tool_calls=calls,
            estimated_steps=len(calls),
            precondition_warnings=warnings,
        )

    def execute(self, plan: OperatorPlan, context: dict | None = None) -> OperatorResult:
        from .toolsets.data_cleaning_tools import (
            fill_null_values, standardize_crs, auto_fix_defects,
            mask_sensitive_fields_tool, add_missing_fields,
        )
        from .toolsets.governance_tools import (
            validate_against_standard, classify_defects,
        )

        tool_map = {
            "standardize_crs": standardize_crs,
            "fill_null_values": fill_null_values,
            "auto_fix_defects": auto_fix_defects,
            "mask_sensitive_fields_tool": mask_sensitive_fields_tool,
            "add_missing_fields": add_missing_fields,
            "validate_against_standard": validate_against_standard,
            "classify_defects": classify_defects,
        }

        details = []
        output_files = []
        errors = 0

        for tc in plan.tool_calls:
            func = tool_map.get(tc.tool_name)
            if not func:
                details.append({"tool": tc.tool_name, "status": "skipped", "reason": "unknown tool"})
                continue
            result = _safe_call(func, **tc.kwargs)
            details.append({"tool": tc.tool_name, "desc": tc.description, **result})
            if result.get("status") == "error":
                errors += 1
            if "output_path" in result:
                output_files.append(result["output_path"])

        status = "error" if errors == len(plan.tool_calls) else ("partial" if errors else "success")
        return OperatorResult(
            status=status,
            output_files=output_files,
            metrics={"total_steps": len(plan.tool_calls), "errors": errors,
                     "strategy": plan.strategy},
            summary=f"清洗完成 (策略: {plan.strategy}, {len(plan.tool_calls)} 步, {errors} 错误)",
            next_steps=["可执行 governance_score 评估数据质量"] if status != "error" else [],
            details=details,
        )

    def validate_preconditions(self, data_profile: DataProfile) -> list[str]:
        warnings = []
        if not data_profile.file_path:
            warnings.append("未指定文件路径")
        if data_profile.row_count == 0:
            warnings.append("数据为空或未能读取行数")
        return warnings


# ============================================================================
# IntegrateOperator
# ============================================================================

class IntegrateOperator(SemanticOperator):
    """Data integration operator — joins, fuses, and aligns multiple sources."""

    name = "integrate"
    description = "数据集成: 多源空间连接、Schema 对齐、CRS 统一、远程数据拉取与融合"

    def plan(self, data_profile: DataProfile, task_description: str = "") -> OperatorPlan:
        warnings = self.validate_preconditions(data_profile)
        calls: list[ToolCall] = []
        strategies: list[str] = []

        # Determine source files from context
        # For planning, we use the profile as the primary; secondary source is from task_description
        fp = data_profile.file_path

        # 1. Profile sources
        calls.append(ToolCall("profile_fusion_sources", {"file_paths": fp},
                              "探查融合源数据特征"))
        strategies.append("profile")

        # 2. Assess compatibility
        calls.append(ToolCall("assess_fusion_compatibility", {"file_paths": fp},
                              "评估融合兼容性"))
        strategies.append("assess")

        # 3. Fuse
        strategy = "auto"
        if any(kw in task_description for kw in ("join", "连接", "合并", "spatial")):
            strategy = "spatial_join"
        elif any(kw in task_description for kw in ("属性", "attribute", "字段")):
            strategy = "attribute_join"
        elif any(kw in task_description for kw in ("overlay", "叠加")):
            strategy = "overlay"

        calls.append(ToolCall("fuse_datasets",
                              {"file_paths": fp, "strategy": strategy},
                              f"执行数据融合 (策略: {strategy})"))
        strategies.append(f"fuse_{strategy}")

        # 4. Validate
        calls.append(ToolCall("validate_fusion_quality", {"file_path": "{{fuse_output}}"},
                              "验证融合质量"))

        return OperatorPlan(
            operator_name=self.name,
            strategy="+".join(strategies),
            tool_calls=calls,
            estimated_steps=len(calls),
            precondition_warnings=warnings,
        )

    def execute(self, plan: OperatorPlan, context: dict | None = None) -> OperatorResult:
        import asyncio
        from .fusion.execution import fuse as _fuse_impl
        from .fusion.profiling import profile_sources as _profile_impl

        details = []
        output_files = []
        errors = 0

        # Execute fusion tool calls (async functions need event loop)
        for tc in plan.tool_calls:
            try:
                if tc.tool_name == "profile_fusion_sources":
                    from .toolsets.fusion_tools import profile_fusion_sources
                    result = asyncio.get_event_loop().run_until_complete(
                        profile_fusion_sources(**tc.kwargs))
                elif tc.tool_name == "assess_fusion_compatibility":
                    from .toolsets.fusion_tools import assess_fusion_compatibility
                    result = asyncio.get_event_loop().run_until_complete(
                        assess_fusion_compatibility(**tc.kwargs))
                elif tc.tool_name == "fuse_datasets":
                    from .toolsets.fusion_tools import fuse_datasets
                    result = asyncio.get_event_loop().run_until_complete(
                        fuse_datasets(**tc.kwargs))
                elif tc.tool_name == "validate_fusion_quality":
                    from .toolsets.fusion_tools import validate_fusion_quality
                    # substitute output path from previous step
                    kwargs = dict(tc.kwargs)
                    if output_files:
                        kwargs["file_path"] = output_files[-1]
                    result = asyncio.get_event_loop().run_until_complete(
                        validate_fusion_quality(**kwargs))
                else:
                    result = json.dumps({"status": "skipped", "reason": "unknown tool"})

                parsed = json.loads(result) if isinstance(result, str) else result
                details.append({"tool": tc.tool_name, "desc": tc.description, **parsed})
                if parsed.get("output_path"):
                    output_files.append(parsed["output_path"])
                if parsed.get("status") == "error":
                    errors += 1
            except Exception as e:
                logger.warning("Integrate tool %s failed: %s", tc.tool_name, e)
                details.append({"tool": tc.tool_name, "status": "error", "message": str(e)})
                errors += 1

        status = "error" if errors == len(plan.tool_calls) else ("partial" if errors else "success")
        return OperatorResult(
            status=status,
            output_files=output_files,
            metrics={"total_steps": len(plan.tool_calls), "errors": errors},
            summary=f"集成完成 ({len(plan.tool_calls)} 步, {errors} 错误)",
            next_steps=["可执行 analyze 算子进行空间分析"] if status != "error" else [],
            details=details,
        )

    def validate_preconditions(self, data_profile: DataProfile) -> list[str]:
        warnings = []
        if not data_profile.file_path:
            warnings.append("未指定数据源路径")
        return warnings


# ============================================================================
# AnalyzeOperator
# ============================================================================

class AnalyzeOperator(SemanticOperator):
    """Spatial analysis operator — auto-selects analysis strategy."""

    name = "analyze"
    description = "空间分析: 空间统计/DRL 优化/因果推断/地形分析/缓冲叠加/时空预测/综合质量评估"

    # Keywords → strategy mapping
    _STRATEGY_KEYWORDS = {
        "spatial_stats": ["分布", "聚类", "热点", "自相关", "moran", "hotspot", "cluster", "distribution"],
        "drl_optimize": ["优化", "布局", "DRL", "optimize", "layout"],
        "causal": ["因果", "causal", "PSM", "DiD", "granger"],
        "terrain": ["地形", "DEM", "流域", "watershed", "terrain", "slope", "elevation"],
        "geoprocessing": ["缓冲", "叠加", "裁剪", "buffer", "overlay", "clip", "intersect"],
        "world_model": ["预测", "趋势", "未来", "predict", "forecast", "LULC"],
        "governance": ["质量", "治理", "评分", "quality", "governance", "audit"],
    }

    def _detect_strategy(self, task_description: str, data_profile: DataProfile) -> str:
        task_lower = task_description.lower()
        for strategy, keywords in self._STRATEGY_KEYWORDS.items():
            if any(kw.lower() in task_lower for kw in keywords):
                return strategy
        # Fallback based on data characteristics
        if data_profile.domain == "landuse":
            return "spatial_stats"
        return "spatial_stats"

    def plan(self, data_profile: DataProfile, task_description: str = "") -> OperatorPlan:
        warnings = self.validate_preconditions(data_profile)
        strategy = self._detect_strategy(task_description, data_profile)
        fp = data_profile.file_path
        calls: list[ToolCall] = []

        if strategy == "spatial_stats":
            col = data_profile.numeric_columns[0] if data_profile.numeric_columns else "value"
            calls.append(ToolCall("spatial_autocorrelation",
                                  {"file_path": fp, "column": col},
                                  "全局空间自相关 (Moran's I)"))
            calls.append(ToolCall("hotspot_analysis",
                                  {"file_path": fp, "column": col},
                                  "热点分析 (Getis-Ord Gi*)"))

        elif strategy == "drl_optimize":
            calls.append(ToolCall("drl_model",
                                  {"data_path": fp},
                                  "DRL 深度强化学习布局优化"))

        elif strategy == "causal":
            col = data_profile.numeric_columns[0] if data_profile.numeric_columns else "outcome"
            calls.append(ToolCall("spatial_autocorrelation",
                                  {"file_path": fp, "column": col},
                                  "空间自相关预检"))
            # Causal tools require treatment/outcome columns — plan them generically
            calls.append(ToolCall("causal_psm",
                                  {"file_path": fp},
                                  "倾向得分匹配 (PSM)"))

        elif strategy == "terrain":
            calls.append(ToolCall("download_dem",
                                  {"file_path": fp},
                                  "下载 DEM 数据"))
            calls.append(ToolCall("extract_watershed",
                                  {"file_path": fp},
                                  "流域提取"))

        elif strategy == "geoprocessing":
            calls.append(ToolCall("create_buffer",
                                  {"file_path": fp, "distance": "1000"},
                                  "创建缓冲区"))

        elif strategy == "world_model":
            calls.append(ToolCall("world_model_predict",
                                  {"file_path": fp},
                                  "LULC 时空预测"))

        elif strategy == "governance":
            calls.append(ToolCall("governance_score_eval",
                                  {"file_path": fp},
                                  "综合质量评分"))

        return OperatorPlan(
            operator_name=self.name,
            strategy=strategy,
            tool_calls=calls,
            estimated_steps=len(calls),
            precondition_warnings=warnings,
        )

    def execute(self, plan: OperatorPlan, context: dict | None = None) -> OperatorResult:
        tool_map = {}
        try:
            from .spatial_statistics import spatial_autocorrelation, hotspot_analysis
            tool_map["spatial_autocorrelation"] = spatial_autocorrelation
            tool_map["hotspot_analysis"] = hotspot_analysis
        except ImportError:
            pass
        try:
            from .toolsets.analysis_tools import drl_model
            tool_map["drl_model"] = drl_model
        except ImportError:
            pass
        try:
            from .toolsets.governance_tools import governance_score
            tool_map["governance_score_eval"] = governance_score
        except ImportError:
            pass

        details = []
        output_files = []
        errors = 0

        for tc in plan.tool_calls:
            func = tool_map.get(tc.tool_name)
            if not func:
                details.append({"tool": tc.tool_name, "status": "skipped", "reason": "tool not available"})
                continue
            result = _safe_call(func, **tc.kwargs)
            details.append({"tool": tc.tool_name, "desc": tc.description, **result})
            if result.get("status") == "error":
                errors += 1
            if result.get("output_path"):
                output_files.append(result["output_path"])

        status = "error" if errors == len(plan.tool_calls) else ("partial" if errors else "success")
        return OperatorResult(
            status=status,
            output_files=output_files,
            metrics={"strategy": plan.strategy, "total_steps": len(plan.tool_calls), "errors": errors},
            summary=f"分析完成 (策略: {plan.strategy}, {len(plan.tool_calls)} 步)",
            next_steps=["可执行 visualize 算子生成可视化"] if status != "error" else [],
            details=details,
        )

    def validate_preconditions(self, data_profile: DataProfile) -> list[str]:
        warnings = []
        if not data_profile.file_path:
            warnings.append("未指定文件路径")
        if not data_profile.geometry_types and not data_profile.has_coordinates:
            warnings.append("数据无几何列，部分空间分析不可用")
        return warnings


# ============================================================================
# VisualizeOperator
# ============================================================================

class VisualizeOperator(SemanticOperator):
    """Visualization operator — maps, charts, and reports."""

    name = "visualize"
    description = "可视化: 交互地图/分类着色/热力图/统计图表/雷达图/报告导出"

    _STRATEGY_KEYWORDS = {
        "choropleth": ["着色", "分级", "choropleth", "graduated"],
        "heatmap": ["热力", "密度", "heatmap", "density"],
        "charts": ["图表", "统计", "chart", "bar", "line", "pie", "histogram"],
        "radar": ["雷达", "多维", "radar"],
        "report": ["报告", "report", "导出", "export"],
    }

    def _detect_strategy(self, task_description: str, data_profile: DataProfile) -> str:
        task_lower = task_description.lower()
        for strategy, keywords in self._STRATEGY_KEYWORDS.items():
            if any(kw.lower() in task_lower for kw in keywords):
                return strategy
        if data_profile.geometry_types:
            return "interactive_map"
        if data_profile.numeric_columns:
            return "charts"
        return "interactive_map"

    def plan(self, data_profile: DataProfile, task_description: str = "") -> OperatorPlan:
        warnings = self.validate_preconditions(data_profile)
        strategy = self._detect_strategy(task_description, data_profile)
        fp = data_profile.file_path
        calls: list[ToolCall] = []

        if strategy == "interactive_map":
            calls.append(ToolCall("visualize_interactive_map",
                                  {"original_data_path": fp},
                                  "生成交互式地图"))

        elif strategy == "choropleth":
            col = data_profile.numeric_columns[0] if data_profile.numeric_columns else "value"
            calls.append(ToolCall("generate_choropleth",
                                  {"file_path": fp, "value_column": col},
                                  f"分类着色图 (列: {col})"))

        elif strategy == "heatmap":
            calls.append(ToolCall("generate_heatmap",
                                  {"file_path": fp},
                                  "热力图"))

        elif strategy == "charts":
            if data_profile.numeric_columns and len(data_profile.columns) > 1:
                x_col = data_profile.columns[0]
                y_col = data_profile.numeric_columns[0]
                calls.append(ToolCall("create_bar_chart",
                                      {"file_path": fp, "x_column": x_col, "y_column": y_col},
                                      f"柱状图 ({x_col} × {y_col})"))

        elif strategy == "radar":
            if data_profile.numeric_columns:
                dims = ",".join(data_profile.numeric_columns[:6])
                calls.append(ToolCall("create_radar_chart",
                                      {"file_path": fp, "dimensions": dims, "value_columns": dims},
                                      "雷达图"))

        elif strategy == "report":
            calls.append(ToolCall("visualize_interactive_map",
                                  {"original_data_path": fp},
                                  "生成地图"))
            calls.append(ToolCall("export_map_png",
                                  {"file_path": fp},
                                  "导出 PNG"))

        if not calls:
            calls.append(ToolCall("visualize_interactive_map",
                                  {"original_data_path": fp},
                                  "默认交互地图"))

        return OperatorPlan(
            operator_name=self.name,
            strategy=strategy,
            tool_calls=calls,
            estimated_steps=len(calls),
            precondition_warnings=warnings,
        )

    def execute(self, plan: OperatorPlan, context: dict | None = None) -> OperatorResult:
        tool_map = {}
        try:
            from .toolsets.visualization_tools import (
                visualize_interactive_map, generate_choropleth, export_map_png,
            )
            tool_map["visualize_interactive_map"] = visualize_interactive_map
            tool_map["generate_choropleth"] = generate_choropleth
            tool_map["export_map_png"] = export_map_png
        except ImportError:
            pass
        try:
            from .toolsets.chart_tools import create_bar_chart, create_radar_chart
            tool_map["create_bar_chart"] = create_bar_chart
            tool_map["create_radar_chart"] = create_radar_chart
        except ImportError:
            pass

        details = []
        output_files = []
        errors = 0

        for tc in plan.tool_calls:
            func = tool_map.get(tc.tool_name)
            if not func:
                details.append({"tool": tc.tool_name, "status": "skipped", "reason": "tool not available"})
                continue
            result = _safe_call(func, **tc.kwargs)
            details.append({"tool": tc.tool_name, "desc": tc.description, **result})
            if result.get("status") == "error":
                errors += 1
            # Capture output paths from various result keys
            for key in ("output_path", "map_path", "html_path"):
                if result.get(key):
                    output_files.append(result[key])

        status = "error" if errors == len(plan.tool_calls) else ("partial" if errors else "success")
        return OperatorResult(
            status=status,
            output_files=output_files,
            metrics={"strategy": plan.strategy, "total_steps": len(plan.tool_calls), "errors": errors},
            summary=f"可视化完成 (策略: {plan.strategy}, {len(plan.tool_calls)} 步)",
            details=details,
        )

    def validate_preconditions(self, data_profile: DataProfile) -> list[str]:
        warnings = []
        if not data_profile.file_path:
            warnings.append("未指定文件路径")
        return warnings


# ---------------------------------------------------------------------------
# Auto-register all built-in operators
# ---------------------------------------------------------------------------

_clean_op = CleanOperator()
_integrate_op = IntegrateOperator()
_analyze_op = AnalyzeOperator()
_visualize_op = VisualizeOperator()

OperatorRegistry.register(_clean_op)
OperatorRegistry.register(_integrate_op)
OperatorRegistry.register(_analyze_op)
OperatorRegistry.register(_visualize_op)
