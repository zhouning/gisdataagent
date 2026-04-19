"""
DomainStandardToolset — 自然资源领域数据模型工具集。

Exposes XMI compiler artifacts to agents:
- compile_xmi_standards: compile EA XMI files into normalized JSON/YAML/KG artifacts
- query_domain_modules: list modules with class counts from compiled index
- query_domain_class: fuzzy-search a class by name and return its details
"""
import os
from pathlib import Path

from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..observability import get_logger

logger = get_logger("domain_standard_tools")

_DEFAULT_COMPILED_DIR = str(Path(__file__).parent.parent / "standards" / "compiled")


def compile_xmi_standards(source_dir: str, output_dir: str = "") -> str:
    """
    [Domain Standard Tool] Compile EA XMI files into normalized artifacts.

    Parses all *.xml files in source_dir and emits:
    - xmi_normalized/*.json  (per-file normalized JSON)
    - indexes/xmi_global_index.yaml  (corpus-level index)
    - kg/domain_model_nodes.json + kg/domain_model_edges.json

    Args:
        source_dir: Directory containing EA XMI/XML export files.
        output_dir: Output directory for compiled artifacts. Defaults to
                    data_agent/standards/compiled/.

    Returns:
        Summary string with file/module/class/association counts.
    """
    from data_agent.standards.xmi_compiler import compile_xmi_corpus

    out = output_dir.strip() if output_dir else _DEFAULT_COMPILED_DIR

    if not os.path.isdir(source_dir):
        return f"源目录不存在: {source_dir}"

    try:
        result = compile_xmi_corpus(source_dir, out)
        return (
            f"XMI编译完成:\n"
            f"  源目录: {result['source_root']}\n"
            f"  输出目录: {result['output_root']}\n"
            f"  文件数: {result['file_count']}\n"
            f"  模块数: {result['module_count']}\n"
            f"  类数: {result['class_count']}\n"
            f"  关联数: {result['association_count']}"
        )
    except Exception as exc:
        logger.exception("compile_xmi_standards failed")
        return f"编译失败: {exc}"


def query_domain_modules(compiled_dir: str = "") -> str:
    """
    [Domain Standard Tool] List domain modules with class counts from compiled index.

    Reads indexes/xmi_global_index.yaml from the compiled artifacts directory
    and returns a formatted list of modules with their class and association counts.

    Args:
        compiled_dir: Directory containing compiled artifacts. Defaults to
                      data_agent/standards/compiled/.

    Returns:
        Formatted module list with class counts, or an error message.
    """
    import yaml

    base = compiled_dir.strip() if compiled_dir else _DEFAULT_COMPILED_DIR
    index_path = Path(base) / "indexes" / "xmi_global_index.yaml"

    if not index_path.is_file():
        return f"未找到全局索引文件: {index_path}\n请先运行 compile_xmi_standards 生成编译产物。"

    try:
        with index_path.open(encoding="utf-8") as f:
            index = yaml.safe_load(f)
    except Exception as exc:
        return f"读取索引失败: {exc}"

    modules = index.get("modules") or []
    if not modules:
        return "索引中无模块记录。"

    lines = [
        f"领域模块列表 (共 {index.get('module_count', len(modules))} 个模块, "
        f"{index.get('class_count', 0)} 个类, "
        f"{index.get('association_count', 0)} 个关联):"
    ]
    for mod in modules:
        name = mod.get("module_name") or mod.get("module_id_raw") or mod.get("module_id", "?")
        cls_cnt = mod.get("class_count", 0)
        assoc_cnt = mod.get("association_count", 0)
        src = mod.get("source_file", "")
        lines.append(f"  [{name}]  类: {cls_cnt}  关联: {assoc_cnt}  来源: {src}")

    return "\n".join(lines)


def query_domain_class(class_name: str, compiled_dir: str = "") -> str:
    """
    [Domain Standard Tool] Search for a domain class by name (fuzzy match).

    Searches the class_index in xmi_global_index.yaml for classes whose name
    contains the given search string (case-insensitive). Returns class details
    including module, package path, and attribute count.

    Args:
        class_name: Class name or partial name to search for.
        compiled_dir: Directory containing compiled artifacts. Defaults to
                      data_agent/standards/compiled/.

    Returns:
        Matching class details, or a message if no matches found.
    """
    import yaml

    if not class_name or not class_name.strip():
        return "请提供类名搜索词。"

    base = compiled_dir.strip() if compiled_dir else _DEFAULT_COMPILED_DIR
    index_path = Path(base) / "indexes" / "xmi_global_index.yaml"

    if not index_path.is_file():
        return f"未找到全局索引文件: {index_path}\n请先运行 compile_xmi_standards 生成编译产物。"

    try:
        with index_path.open(encoding="utf-8") as f:
            index = yaml.safe_load(f)
    except Exception as exc:
        return f"读取索引失败: {exc}"

    class_index: dict = index.get("class_index") or {}
    if not class_index:
        return "索引中无类记录。"

    query = class_name.strip().lower()
    matches = [
        (cid, info)
        for cid, info in class_index.items()
        if query in (info.get("class_name") or "").lower()
    ]

    if not matches:
        return f"未找到包含 '{class_name}' 的类。共索引 {len(class_index)} 个类。"

    lines = [f"搜索 '{class_name}' 找到 {len(matches)} 个匹配类:"]
    for cid, info in matches[:20]:  # cap output at 20 results
        name = info.get("class_name", "?")
        module = info.get("module_name") or info.get("module_id_raw") or info.get("module_id", "?")
        pkg = " > ".join(info.get("package_path") or []) or "(无包路径)"
        src = info.get("source_file", "")
        lines.append(
            f"\n  类名: {name}\n"
            f"    模块: {module}\n"
            f"    包路径: {pkg}\n"
            f"    来源: {src}\n"
            f"    全局ID: {cid}"
        )

    if len(matches) > 20:
        lines.append(f"\n  ... 还有 {len(matches) - 20} 个结果未显示，请缩小搜索范围。")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Toolset Registration
# ---------------------------------------------------------------------------

class DomainStandardToolset(BaseToolset):
    """Domain standard tools: XMI compilation, module listing, class search."""

    name = "DomainStandardToolset"
    description = "自然资源领域数据模型编译、模块查询与类关系检索"
    category = "domain_standards"

    def __init__(self, tool_filter=None):
        self._tool_filter = tool_filter

    async def get_tools(self, readonly_context=None):
        tools = [
            FunctionTool(compile_xmi_standards),
            FunctionTool(query_domain_modules),
            FunctionTool(query_domain_class),
        ]
        if self._tool_filter:
            tools = [t for t in tools if t.name in self._tool_filter]
        return tools
