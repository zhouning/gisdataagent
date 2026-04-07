"""
Agent 编排层 — ADK FunctionTool 包装

将知识管理层和底座调用层的能力包装为 ADK FunctionTool，
供 Agent 在对话中按需调用。

设计原则：
  - 每个 Tool 函数的入参和返回值都是 JSON 可序列化的（dict/list/str）
  - Tool 函数的 docstring 是 LLM 看到的工具描述，要写得清晰准确
  - 确定性逻辑在知识管理层，Tool 只做组装和调用
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from google.adk.tools import FunctionTool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 延迟初始化的知识库单例（避免 import 时就加载大文件）
# ---------------------------------------------------------------------------

_vocab = None
_standard = None
_model = None


def _get_vocab():
    global _vocab
    if _vocab is None:
        from data_agent.knowledge.semantic_vocab import SemanticVocab
        _vocab = SemanticVocab()
    return _vocab


def _get_standard():
    global _standard
    if _standard is None:
        from data_agent.knowledge.standard_rules import load_survey_standard
        _standard = load_survey_standard()
    return _standard


def _get_model():
    global _model
    if _model is None:
        from data_agent.knowledge.model_repo import load_survey_model
        _model = load_survey_model()
    return _model


# ---------------------------------------------------------------------------
# Tool 函数定义
# ---------------------------------------------------------------------------

def analyze_fields(file_path: str) -> dict:
    """分析空间数据文件的字段结构，用语义等价库自动识别每个字段的含义。

    Args:
        file_path: 数据文件路径（支持 Shapefile/GeoJSON/GPKG）

    Returns:
        包含字段列表、语义匹配结果、匹配率、推荐的标准表名的字典
    """
    from data_agent.intelligence.model_advisor import read_source_fields

    vocab = _get_vocab()
    standard = _get_standard()

    # 读取字段
    fields = read_source_fields(file_path)
    source_names = [f.name for f in fields]

    # 尝试匹配每个标准表，找最佳匹配
    best_table = None
    best_rate = 0
    best_matches = []

    for std_table in standard.tables:
        target_codes = [
            r.field_code for r in std_table.fields
            if r.field_code and len(r.field_code) < 20
        ]
        if not target_codes:
            continue

        matches = vocab.match_fields(source_names, target_codes)
        matched = sum(1 for m in matches if m["match_type"] != "unmatched")
        rate = matched / len(target_codes) if target_codes else 0

        if matched > (len(best_matches) - sum(1 for m in best_matches if m["match_type"] == "unmatched")) or (
            best_table is None
        ):
            if rate > best_rate:
                best_table = std_table
                best_rate = rate
                best_matches = matches

    return {
        "file": Path(file_path).name,
        "field_count": len(fields),
        "fields": [
            {
                "name": f.name,
                "dtype": f.dtype,
                "non_null": f.non_null_count,
                "total": f.total_count,
                "sample": f.sample_value[:50],
            }
            for f in fields
        ],
        "recommended_standard_table": best_table.table_name if best_table else None,
        "recommended_table_label": best_table.table_label if best_table else None,
        "match_rate": round(best_rate, 4),
        "match_details": best_matches[:20],  # 截断避免过长
    }


def check_compliance(file_path: str, standard_table: str = "DLTB") -> dict:
    """将数据文件与指定的数据标准进行对照分析，生成差距报告。

    Args:
        file_path: 数据文件路径
        standard_table: 标准中的目标属性表名（如 DLTB、LSYD），默认 DLTB

    Returns:
        包含匹配率、差距项列表（按严重程度分级）的字典
    """
    from data_agent.intelligence.model_advisor import advise

    advice = advise(
        source_file=file_path,
        standard=_get_standard(),
        target_table_name=standard_table,
        vocab=_get_vocab(),
    )
    return advice.to_dict()


def advise_model(file_path: str, standard_table: str = "DLTB") -> dict:
    """基于差距分析和目标数据模型，推荐数据模型调整方案。

    Args:
        file_path: 数据文件路径
        standard_table: 标准中的目标属性表名

    Returns:
        包含调整建议清单的字典（必须执行/建议执行/可选执行）
    """
    from data_agent.intelligence.model_advisor import advise

    advice = advise(
        source_file=file_path,
        standard=_get_standard(),
        target_table_name=standard_table,
        vocab=_get_vocab(),
    )

    # 按操作类型分组
    must_do = [g for g in advice.gaps if g.severity == "high"]
    should_do = [g for g in advice.gaps if g.severity == "medium"]
    optional = [g for g in advice.gaps if g.severity in ("low", "info")]

    return {
        "source": advice.source_name,
        "target_table": advice.target_table,
        "match_rate": round(advice.match_rate, 4),
        "must_do": [
            {"field": g.field_code, "name": g.field_name, "action": g.suggestion}
            for g in must_do
        ],
        "should_do": [
            {"field": g.field_code, "name": g.field_name, "action": g.suggestion}
            for g in should_do
        ],
        "optional": [
            {"field": g.field_code, "name": g.field_name, "action": g.suggestion}
            for g in optional
            if len(g.field_code) < 20  # 过滤注释
        ],
    }


def execute_governance(
    dataset_id: str,
    steps: list[str] | None = None,
) -> dict:
    """调用底座 API 执行数据治理流程。

    Args:
        dataset_id: 数据集 ID
        steps: 要执行的步骤列表（默认全部）。
               可选值: field_mapping, aggregation, quality_check, asset_register

    Returns:
        每个步骤的执行状态和结果
    """
    # Phase 1b 对接底座后实现，当前返回 Mock 结果
    if steps is None:
        steps = ["field_mapping", "aggregation", "quality_check", "asset_register"]

    results = {}
    for step in steps:
        results[step] = {
            "status": "mock_success",
            "message": f"[MOCK] {step} 执行成功（底座环境未就绪，使用模拟数据）",
        }

    return {
        "dataset_id": dataset_id,
        "mode": "mock",
        "steps": results,
    }


def generate_report(file_path: str, standard_table: str = "DLTB") -> dict:
    """生成治理成果报告（Word 格式）。

    Args:
        file_path: 源数据文件路径
        standard_table: 标准属性表名

    Returns:
        包含报告文件路径的字典
    """
    import geopandas as gpd
    from data_agent.intelligence.model_advisor import advise
    from data_agent.intelligence.report_generator import generate_report as gen

    advice = advise(
        source_file=file_path,
        standard=_get_standard(),
        target_table_name=standard_table,
        vocab=_get_vocab(),
    )

    gdf = gpd.read_file(file_path)
    source_name = Path(file_path).stem
    output_path = Path(f"治理分析报告_{standard_table}_{source_name}.docx")

    report_path = gen(
        advice=advice,
        output_path=output_path,
        source_record_count=len(gdf),
        source_crs=str(gdf.crs),
    )

    return {
        "report_path": str(report_path),
        "report_size_bytes": report_path.stat().st_size,
        "summary": advice.summary(),
    }


def query_knowledge(question: str) -> dict:
    """查询知识库，回答关于数据标准、语义映射、数据模型的问题。

    Args:
        question: 用户的问题（如"DLBM是什么字段"、"DLTB有哪些必填字段"）

    Returns:
        包含查询结果的字典
    """
    vocab = _get_vocab()
    standard = _get_standard()
    model = _get_model()

    result = {"question": question, "answers": []}

    # 尝试从语义等价库回答
    # 检查问题中是否包含字段名
    words = question.replace("？", "").replace("?", "").split()
    for word in words:
        group = vocab.lookup(word)
        if group:
            fields = vocab.get_group_fields(group)
            result["answers"].append({
                "source": "语义等价库",
                "content": f"字段 {word} 属于等价组 '{group}'，等价字段包括：{', '.join(fields)}",
            })

    # 尝试从标准规则库回答
    for word in words:
        std_table = standard.get_table(word.upper())
        if std_table:
            mandatory = std_table.mandatory_fields()
            result["answers"].append({
                "source": "标准规则库",
                "content": f"标准表 {std_table.table_name}（{std_table.table_label}）"
                           f"共 {len(std_table.fields)} 个字段，其中 {len(mandatory)} 个必填。"
                           f"必填字段：{', '.join(f.field_code for f in mandatory)}",
            })

    # 尝试从数据模型库回答
    for word in words:
        entity = model.get_entity(word)
        if entity:
            result["answers"].append({
                "source": "数据模型库",
                "content": f"实体 {entity.name} 有 {len(entity.fields)} 个字段，"
                           f"继承自：{[g.parent_name for g in entity.generalizations]}",
            })

    if not result["answers"]:
        result["answers"].append({
            "source": "未找到",
            "content": "知识库中未找到相关信息，建议在管理端补充相关知识。",
        })

    return result


# ---------------------------------------------------------------------------
# ADK FunctionTool 实例（供 Agent 注册使用）
# ---------------------------------------------------------------------------

analyze_fields_tool = FunctionTool(analyze_fields)
check_compliance_tool = FunctionTool(check_compliance)
advise_model_tool = FunctionTool(advise_model)
execute_governance_tool = FunctionTool(execute_governance)
generate_report_tool = FunctionTool(generate_report)
query_knowledge_tool = FunctionTool(query_knowledge)
