"""Knowledge Base toolset: create, manage, and search RAG knowledge bases."""
import json
import os
import traceback

from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from .. import knowledge_base as kb_engine
from ..gis_processors import _resolve_path


# ---------------------------------------------------------------------------
# Tool filter constants
# ---------------------------------------------------------------------------

KB_READ = ["search_knowledge_base", "get_kb_context", "list_knowledge_bases"]
KB_WRITE = ["create_knowledge_base", "add_document_to_kb", "delete_knowledge_base"]


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------


def create_knowledge_base(name: str, description: str = "") -> str:
    """创建一个私有知识库，用于存储和检索领域文档。

    Args:
        name: 知识库名称（如"城市规划规范"、"土地利用标准"）。
        description: 知识库描述。

    Returns:
        JSON格式的创建结果。
    """
    try:
        kb_id = kb_engine.create_knowledge_base(name, description)
        if kb_id is None:
            return json.dumps({"status": "error", "message": "创建失败（可能已达上限或名称重复）"})
        return json.dumps({
            "status": "success",
            "kb_id": kb_id,
            "name": name,
            "message": f"知识库 '{name}' 创建成功",
        }, ensure_ascii=False)
    except Exception as e:
        traceback.print_exc()
        return f"Error: {e}"


def add_document_to_kb(kb_name: str, file_path: str) -> str:
    """将文档添加到知识库，自动分段并生成向量索引。

    支持格式：.txt, .md, .pdf, .docx

    Args:
        kb_name: 目标知识库名称。
        file_path: 文档文件路径。

    Returns:
        JSON格式的添加结果，包含分段数量。
    """
    try:
        resolved = _resolve_path(file_path)
        if not os.path.isfile(resolved):
            return json.dumps({"status": "error", "message": f"文件不存在: {file_path}"})

        # Resolve KB by name
        from ..db_engine import get_engine
        from ..user_context import current_user_id
        engine = get_engine()
        if not engine:
            return json.dumps({"status": "error", "message": "数据库未连接"})

        username = current_user_id.get()
        with engine.connect() as conn:
            kb_id = kb_engine._resolve_kb_id(conn, username, kb_name=kb_name)
        if not kb_id:
            return json.dumps({"status": "error", "message": f"知识库 '{kb_name}' 不存在"})

        filename = os.path.basename(resolved)
        doc_id = kb_engine.add_document(kb_id, filename, resolved)
        if doc_id is None:
            return json.dumps({"status": "error", "message": "添加失败（内容为空或已达上限）"})

        return json.dumps({
            "status": "success",
            "doc_id": doc_id,
            "filename": filename,
            "kb_name": kb_name,
            "message": f"文档 '{filename}' 已添加到知识库 '{kb_name}'",
        }, ensure_ascii=False)
    except Exception as e:
        traceback.print_exc()
        return f"Error: {e}"


def search_knowledge_base(query: str, kb_name: str = "", top_k: str = "5") -> str:
    """语义搜索知识库，返回与查询最相关的文档片段。

    Args:
        query: 搜索查询文本。
        kb_name: 知识库名称（留空搜索所有可访问知识库）。
        top_k: 返回结果数量（默认5）。

    Returns:
        JSON格式的搜索结果，按相关度排序。
    """
    try:
        k = int(top_k) if top_k else 5
        results = kb_engine.search_kb(
            query,
            kb_name=kb_name if kb_name else None,
            top_k=k,
        )
        if not results:
            return json.dumps({
                "status": "success",
                "results": [],
                "message": "未找到相关内容",
            }, ensure_ascii=False)

        return json.dumps({
            "status": "success",
            "query": query,
            "result_count": len(results),
            "results": results,
        }, ensure_ascii=False, default=str)
    except Exception as e:
        traceback.print_exc()
        return f"Error: {e}"


def get_kb_context(query: str, kb_name: str = "") -> str:
    """检索知识库并返回格式化的上下文信息，可直接用于增强回答。

    Args:
        query: 查询文本。
        kb_name: 知识库名称（留空搜索所有可访问知识库）。

    Returns:
        格式化的知识库检索上下文。
    """
    try:
        context = kb_engine.get_kb_context(
            query,
            kb_name=kb_name if kb_name else None,
        )
        return context
    except Exception as e:
        traceback.print_exc()
        return f"Error: {e}"


def list_knowledge_bases() -> str:
    """列出当前用户可访问的所有知识库。

    Returns:
        JSON格式的知识库列表。
    """
    try:
        kbs = kb_engine.list_knowledge_bases()
        return json.dumps({
            "status": "success",
            "count": len(kbs),
            "knowledge_bases": kbs,
        }, ensure_ascii=False, default=str)
    except Exception as e:
        traceback.print_exc()
        return f"Error: {e}"


def delete_knowledge_base(kb_name: str) -> str:
    """删除一个知识库及其所有文档和索引。

    Args:
        kb_name: 要删除的知识库名称。

    Returns:
        JSON格式的删除结果。
    """
    try:
        from ..db_engine import get_engine
        from ..user_context import current_user_id
        engine = get_engine()
        if not engine:
            return json.dumps({"status": "error", "message": "数据库未连接"})

        username = current_user_id.get()
        with engine.connect() as conn:
            kb_id = kb_engine._resolve_kb_id(conn, username, kb_name=kb_name)
        if not kb_id:
            return json.dumps({"status": "error", "message": f"知识库 '{kb_name}' 不存在"})

        ok = kb_engine.delete_knowledge_base(kb_id)
        if ok:
            return json.dumps({
                "status": "success",
                "message": f"知识库 '{kb_name}' 已删除",
            }, ensure_ascii=False)
        return json.dumps({"status": "error", "message": "删除失败"})
    except Exception as e:
        traceback.print_exc()
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# GraphRAG tools (v10.0.5)
# ---------------------------------------------------------------------------

def graph_rag_search_tool(query: str, kb_name: str = "", top_k: str = "5",
                          use_graph: str = "true") -> str:
    """图增强语义搜索 — 结合向量检索和知识图谱邻居扩展，获取更全面的搜索结果。

    Args:
        query: 搜索查询
        kb_name: 知识库名称 (可选，留空搜索全部)
        top_k: 返回数量
        use_graph: 是否使用图扩展 (true/false)
    """
    try:
        from ..graph_rag import graph_rag_search
        from .. import knowledge_base as kb_engine

        kb_id = None
        if kb_name:
            username = current_user_id.get("")
            kbs = kb_engine.list_knowledge_bases()
            for kb in kbs:
                if kb.get("name") == kb_name:
                    kb_id = kb["id"]
                    break

        if use_graph.lower() == "true":
            results = graph_rag_search(query, kb_id=kb_id, top_k=int(top_k))
        else:
            results = kb_engine.search_kb(query, kb_id=kb_id, top_k=int(top_k))
            for r in results:
                r["source"] = "vector"

        return json.dumps({"status": "ok", "results": results,
                          "count": len(results)}, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def build_kb_graph_tool(kb_name: str) -> str:
    """为知识库构建实体关系图谱 — 提取实体并建立关联，用于增强搜索。

    Args:
        kb_name: 知识库名称
    """
    try:
        from ..graph_rag import build_kb_graph
        from .. import knowledge_base as kb_engine

        kbs = kb_engine.list_knowledge_bases()
        kb_id = None
        for kb in kbs:
            if kb.get("name") == kb_name:
                kb_id = kb["id"]
                break
        if kb_id is None:
            return json.dumps({"status": "error", "message": f"知识库 '{kb_name}' 不存在"})

        result = build_kb_graph(kb_id, use_llm=False)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def get_kb_entity_graph_tool(kb_name: str) -> str:
    """导出知识库的实体关系图谱数据 — 用于可视化展示。

    Args:
        kb_name: 知识库名称
    """
    try:
        from ..graph_rag import get_entity_graph
        from .. import knowledge_base as kb_engine

        kbs = kb_engine.list_knowledge_bases()
        kb_id = None
        for kb in kbs:
            if kb.get("name") == kb_name:
                kb_id = kb["id"]
                break
        if kb_id is None:
            return json.dumps({"status": "error", "message": f"知识库 '{kb_name}' 不存在"})

        result = get_entity_graph(kb_id)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


# ---------------------------------------------------------------------------
# Toolset class
# ---------------------------------------------------------------------------

_ALL_FUNCS = [
    create_knowledge_base,
    add_document_to_kb,
    search_knowledge_base,
    get_kb_context,
    list_knowledge_bases,
    delete_knowledge_base,
    graph_rag_search_tool,
    build_kb_graph_tool,
    get_kb_entity_graph_tool,
]


class KnowledgeBaseToolset(BaseToolset):
    """RAG Knowledge Base toolset -- create, manage, and search private knowledge bases."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
