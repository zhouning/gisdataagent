"""
ReportToolset — Agent tools for report generation.

Exposes report generation capabilities to the AI Agent:
- List available report templates
- Generate structured reports (Word/PDF/Markdown)
- Generate reports from analysis results
"""
from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..observability import get_logger

logger = get_logger("report_tools")


def list_report_templates() -> str:
    """
    [Report Tool] List available report templates.

    Shows all report templates that can be used to generate structured reports,
    including quality check reports, governance reports, and analysis reports.

    Returns:
        Formatted list of available templates with descriptions.
    """
    from ..report_generator import list_report_templates as _list
    templates = _list()
    if not templates:
        return "暂无可用报告模板。"
    lines = ["可用报告模板:"]
    for t in templates:
        lines.append(f"  [{t['id']}] {t['name']} — {t['description']}")
    return "\n".join(lines)


def generate_quality_report(
    data_description: str,
    quality_findings: str,
    defect_summary: str = "",
    precision_results: str = "",
    recommendations: str = "",
    conclusion: str = "",
    template_id: str = "surveying_qc",
    output_format: str = "docx",
    report_title: str = "",
) -> str:
    """
    [Report Tool] Generate a quality inspection report.

    Creates a structured quality report from inspection findings. The report
    follows industry-standard templates and is exported as Word/PDF.

    Args:
        data_description: Description of the inspected dataset (name, type, source, size).
        quality_findings: Main quality check findings (completeness, format, consistency).
        defect_summary: Summary of defects found (type, count, severity).
        precision_results: Precision/accuracy check results (coordinate, topology, overlay).
        recommendations: Improvement recommendations.
        conclusion: Overall conclusion and quality judgment.
        template_id: Report template to use (default: surveying_qc).
        output_format: Output format — docx (default), pdf, or md.
        report_title: Custom report title (optional).

    Returns:
        Path to the generated report file.
    """
    from ..report_generator import generate_structured_report

    section_data = {
        "项目概况": data_description,
        "检查依据": "依据 GB/T 24356《测绘成果质量检查与验收》及相关行业标准进行检查。",
        "数据审查结果": quality_findings,
        "精度核验结果": precision_results or "*（未执行精度核验）*",
        "缺陷统计": defect_summary or "*（未发现缺陷）*",
        "质量评分": "",  # Will be filled by LLM if available
        "整改建议": recommendations,
        "结论": conclusion,
        # data_quality template sections
        "数据集概览": data_description,
        "质量评估": quality_findings,
        "问题清单": defect_summary,
        "改进建议": recommendations,
        # governance template sections
        "治理概览": data_description,
        "标准符合性": quality_findings,
        "Gap分析": defect_summary,
        "治理建议": recommendations,
        # general_analysis template sections
        "分析概览": data_description,
        "数据描述": data_description,
        "分析结果": quality_findings,
        "可视化": "",
    }

    try:
        path = generate_structured_report(
            template_id=template_id,
            section_data=section_data,
            title=report_title or None,
            output_format=output_format,
        )
        return f"质检报告已生成:\n  路径: {path}\n  格式: {output_format}\n  模板: {template_id}"
    except Exception as e:
        return f"报告生成失败: {e}"


def export_analysis_report(
    analysis_text: str,
    report_title: str = "",
    output_format: str = "docx",
) -> str:
    """
    [Report Tool] Export analysis results as a formatted report.

    Converts markdown-formatted analysis text into a professionally
    formatted Word or PDF document with proper styling, tables, and layout.

    Args:
        analysis_text: Markdown-formatted analysis text to convert.
        report_title: Report title (optional, auto-detected if empty).
        output_format: Output format — docx (default) or pdf.

    Returns:
        Path to the generated report file.
    """
    import uuid
    from ..report_generator import generate_word_report, generate_pdf_report
    from ..user_context import get_user_upload_dir

    output_dir = get_user_upload_dir()
    uid = uuid.uuid4().hex[:8]

    try:
        if output_format == "pdf":
            path = os.path.join(output_dir, f"report_{uid}.pdf")
            result = generate_pdf_report(analysis_text, path, title=report_title or None)
        else:
            path = os.path.join(output_dir, f"report_{uid}.docx")
            result = generate_word_report(analysis_text, path, title=report_title or None)
        return f"报告已导出:\n  路径: {result}\n  格式: {output_format}"
    except Exception as e:
        return f"报告导出失败: {e}"


import os  # noqa: E402 (needed for export_analysis_report)


class ReportToolset(BaseToolset):
    """Report generation tools for Agent."""

    name = "ReportToolset"
    description = "报告生成工具：质检报告、分析报告的模板化生成与导出"
    category = "reporting"

    def get_tools(self):
        return [
            FunctionTool(list_report_templates),
            FunctionTool(generate_quality_report),
            FunctionTool(export_analysis_report),
        ]
