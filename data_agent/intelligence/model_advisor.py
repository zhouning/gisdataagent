"""
智能交互层 — UC-05 推荐数据模型调整方案

核心流程：
  1. 读取样例数据的字段结构（通过 platform/metadata_api 或直接读文件）
  2. 用 knowledge/semantic_vocab 做字段语义匹配
  3. 用 knowledge/standard_rules 检查合规性
  4. 用 knowledge/model_repo 对比目标模型
  5. 综合生成调整建议（结构化输出，不依赖 LLM 猜测）

核心约束：所有建议必须引用知识库中的具体规则，不允许无依据发挥。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd

from data_agent.knowledge.model_repo import DomainModel, ModelEntity
from data_agent.knowledge.semantic_vocab import SemanticVocab
from data_agent.knowledge.standard_rules import StandardDocument, TableStandard

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class SourceFieldInfo:
    """源数据的字段信息"""

    name: str
    dtype: str  # int32 / float64 / object / ...
    non_null_count: int = 0
    total_count: int = 0
    sample_value: str = ""


@dataclass
class FieldMatchResult:
    """单个字段的匹配结果"""

    source_field: str
    target_field: str | None  # 标准中匹配到的字段代码
    target_field_name: str | None  # 标准中匹配到的字段中文名
    match_type: str  # exact / semantic / unmatched
    group_id: str | None  # 语义等价组 ID


@dataclass
class FieldGap:
    """字段差距项"""

    gap_type: str  # missing_in_source / extra_in_source / type_mismatch / length_mismatch
    field_code: str
    field_name: str
    severity: str  # high(必填缺失) / medium(条件必填缺失) / low(可选缺失) / info(多余字段)
    description: str
    suggestion: str


@dataclass
class ModelAdjustmentAdvice:
    """模型调整建议的完整输出"""

    source_name: str
    target_table: str
    target_table_label: str
    source_field_count: int
    target_field_count: int
    matched_fields: list[FieldMatchResult] = field(default_factory=list)
    gaps: list[FieldGap] = field(default_factory=list)

    @property
    def match_rate(self) -> float:
        """匹配率：匹配到的字段数 / 标准要求的字段数"""
        matched = sum(
            1 for m in self.matched_fields if m.match_type != "unmatched"
        )
        return matched / self.target_field_count if self.target_field_count > 0 else 0

    @property
    def high_gaps(self) -> list[FieldGap]:
        return [g for g in self.gaps if g.severity == "high"]

    @property
    def medium_gaps(self) -> list[FieldGap]:
        return [g for g in self.gaps if g.severity == "medium"]

    def summary(self) -> dict:
        """生成摘要（供 AI 交互层展示）"""
        return {
            "源数据": self.source_name,
            "目标标准表": f"{self.target_table} ({self.target_table_label})",
            "源字段数": self.source_field_count,
            "标准字段数": self.target_field_count,
            "匹配率": f"{self.match_rate:.0%}",
            "高优先级差距": len(self.high_gaps),
            "中优先级差距": len(self.medium_gaps),
            "总差距项": len(self.gaps),
        }

    def to_dict(self) -> dict:
        """完整导出（供报告生成和 LLM 推理使用）"""
        return {
            "源数据": self.source_name,
            "目标标准表": self.target_table,
            "目标标准表中文名": self.target_table_label,
            "源字段数": self.source_field_count,
            "标准字段数": self.target_field_count,
            "匹配率": round(self.match_rate, 4),
            "字段匹配详情": [
                {
                    "源字段": m.source_field,
                    "目标字段": m.target_field,
                    "目标字段名称": m.target_field_name,
                    "匹配类型": m.match_type,
                    "语义组": m.group_id,
                }
                for m in self.matched_fields
            ],
            "差距清单": [
                {
                    "差距类型": g.gap_type,
                    "字段代码": g.field_code,
                    "字段名称": g.field_name,
                    "严重程度": g.severity,
                    "描述": g.description,
                    "建议": g.suggestion,
                }
                for g in self.gaps
            ],
        }


# ---------------------------------------------------------------------------
# 核心逻辑
# ---------------------------------------------------------------------------

def read_source_fields(file_path: str | Path) -> list[SourceFieldInfo]:
    """读取源数据文件的字段信息。支持 Shapefile/GeoJSON/GPKG。"""
    path = Path(file_path)
    gdf = gpd.read_file(path, rows=100)  # 只读前 100 行获取结构
    total = len(gpd.read_file(path, rows=0)) if path.suffix == ".shp" else len(gdf)

    # 重新读全量来获取准确的 non_null count
    gdf_full = gpd.read_file(path)
    total = len(gdf_full)

    fields = []
    for col in gdf_full.columns:
        if col == "geometry":
            continue
        non_null = int(gdf_full[col].notna().sum())
        sample = ""
        if non_null > 0:
            sample = str(gdf_full[col].dropna().iloc[0])[:100]

        fields.append(
            SourceFieldInfo(
                name=col,
                dtype=str(gdf_full[col].dtype),
                non_null_count=non_null,
                total_count=total,
                sample_value=sample,
            )
        )
    return fields


def analyze_model_gap(
    source_fields: list[SourceFieldInfo],
    standard_table: TableStandard,
    vocab: SemanticVocab,
    source_name: str = "",
) -> ModelAdjustmentAdvice:
    """
    分析源数据字段与标准字段的差距，生成模型调整建议。

    Args:
        source_fields: 源数据字段列表
        standard_table: 标准中的目标属性表定义
        vocab: 语义等价库
        source_name: 源数据名称（用于报告展示）

    Returns:
        ModelAdjustmentAdvice 包含匹配详情和差距清单
    """
    source_names = [f.name for f in source_fields]
    target_codes = [r.field_code for r in standard_table.fields if r.field_code]

    # Step 1: 语义匹配
    match_results_raw = vocab.match_fields(source_names, target_codes)

    matched_fields = []
    matched_target_codes: set[str] = set()

    for mr in match_results_raw:
        target_field = mr["target"]
        target_name = ""
        if target_field:
            rule = standard_table.get_field(target_field)
            if rule:
                target_name = rule.field_name
            matched_target_codes.add(target_field)

        matched_fields.append(
            FieldMatchResult(
                source_field=mr["source"],
                target_field=target_field,
                target_field_name=target_name,
                match_type=mr["match_type"],
                group_id=mr["group_id"],
            )
        )

    # Step 2: 识别差距
    gaps: list[FieldGap] = []

    # 2a: 标准要求但源数据缺失的字段
    for rule in standard_table.fields:
        if not rule.field_code:
            continue
        if rule.field_code in matched_target_codes:
            continue

        if rule.constraint == "M":
            severity = "high"
            desc = f"必填字段 {rule.field_code}({rule.field_name}) 在源数据中缺失"
            suggestion = f"需要补充字段 {rule.field_code}，类型 {rule.field_type}({rule.field_length})"
        elif rule.constraint == "C":
            severity = "medium"
            desc = f"条件必填字段 {rule.field_code}({rule.field_name}) 在源数据中缺失"
            suggestion = f"根据业务场景评估是否需要补充 {rule.field_code}"
        else:
            severity = "low"
            desc = f"可选字段 {rule.field_code}({rule.field_name}) 在源数据中缺失"
            suggestion = f"可选补充 {rule.field_code}"

        if rule.value_domain:
            suggestion += f"，值域要求: {rule.value_domain}"

        gaps.append(
            FieldGap(
                gap_type="missing_in_source",
                field_code=rule.field_code,
                field_name=rule.field_name,
                severity=severity,
                description=desc,
                suggestion=suggestion,
            )
        )

    # 2b: 源数据有但标准不要求的字段
    for mr in matched_fields:
        if mr.match_type == "unmatched":
            gaps.append(
                FieldGap(
                    gap_type="extra_in_source",
                    field_code=mr.source_field,
                    field_name=mr.source_field,
                    severity="info",
                    description=f"源数据字段 {mr.source_field} 不在标准 {standard_table.table_name} 中",
                    suggestion="评估是否为旧版标准字段或自定义扩展字段，可保留或映射到标准字段",
                )
            )

    # 按严重程度排序
    severity_order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    gaps.sort(key=lambda g: severity_order.get(g.severity, 9))

    return ModelAdjustmentAdvice(
        source_name=source_name,
        target_table=standard_table.table_name,
        target_table_label=standard_table.table_label,
        source_field_count=len(source_fields),
        target_field_count=len([r for r in standard_table.fields if r.field_code]),
        matched_fields=matched_fields,
        gaps=gaps,
    )


def advise(
    source_file: str | Path,
    standard: StandardDocument,
    target_table_name: str,
    vocab: SemanticVocab | None = None,
) -> ModelAdjustmentAdvice:
    """
    端到端的模型调整建议：从文件读取 → 字段匹配 → 差距分析 → 输出建议。

    Args:
        source_file: 源数据文件路径（Shapefile/GeoJSON/GPKG）
        standard: 已解析的标准文档
        target_table_name: 目标标准属性表名（如 "DLTB"）
        vocab: 语义等价库（None 则使用默认配置）

    Returns:
        ModelAdjustmentAdvice
    """
    if vocab is None:
        vocab = SemanticVocab()

    # 1. 读取源数据字段
    source_path = Path(source_file)
    logger.info("读取源数据: %s", source_path.name)
    source_fields = read_source_fields(source_path)
    logger.info("源数据字段数: %d", len(source_fields))

    # 2. 查找标准表
    std_table = standard.get_table(target_table_name)
    if std_table is None:
        available = [t.table_name for t in standard.tables[:20]]
        raise ValueError(
            f"标准中未找到 {target_table_name}，可用表: {available}"
        )
    logger.info(
        "目标标准表: %s (%s), %d 字段",
        std_table.table_name,
        std_table.table_label,
        len(std_table.fields),
    )

    # 3. 分析差距
    advice = analyze_model_gap(
        source_fields=source_fields,
        standard_table=std_table,
        vocab=vocab,
        source_name=source_path.name,
    )

    logger.info(
        "分析完成: 匹配率=%.0f%%, 高优先级差距=%d, 总差距=%d",
        advice.match_rate * 100,
        len(advice.high_gaps),
        len(advice.gaps),
    )

    return advice
