"""Knowledge Graph toolset: build and query geographic entity-relationship graphs."""
import json
import os
import traceback
from typing import Optional

from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from .. import knowledge_graph as kg_engine
from ..gis_processors import _resolve_path


# ---------------------------------------------------------------------------
# Module-level graph instance (persisted across tool calls in a session)
# ---------------------------------------------------------------------------

_current_graph: Optional[kg_engine.GeoKnowledgeGraph] = None


def _get_or_create_graph() -> kg_engine.GeoKnowledgeGraph:
    """Return the current session graph, creating one if needed."""
    global _current_graph
    if _current_graph is None:
        _current_graph = kg_engine.GeoKnowledgeGraph()
    return _current_graph


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

def build_knowledge_graph(
    file_paths: str,
    entity_type: str = "auto",
    detect_adjacency: str = "true",
    detect_containment: str = "true",
) -> str:
    """从空间数据构建地理知识图谱，自动识别实体类型和空间关系。

    Args:
        file_paths: 逗号分隔的空间数据文件路径。
        entity_type: 实体类型（auto自动检测, parcel, building, road等）。
        detect_adjacency: 是否检测邻接关系（true/false）。
        detect_containment: 是否检测包含关系（true/false）。

    Returns:
        JSON格式的知识图谱统计信息。
    """
    try:
        import geopandas as gpd

        paths = [p.strip() for p in file_paths.split(",") if p.strip()]
        if not paths:
            return "Error: 请提供至少一个文件路径。"

        adj = detect_adjacency.lower() == "true"
        cont = detect_containment.lower() == "true"

        graph = _get_or_create_graph()
        source_names = []

        for i, p in enumerate(paths):
            resolved = _resolve_path(p)
            gdf = gpd.read_file(resolved)
            source_names.append(os.path.basename(resolved))

            if i == 0 and graph.graph.number_of_nodes() == 0:
                stats = graph.build_from_geodataframe(
                    gdf,
                    entity_type=entity_type,
                    detect_adjacency=adj,
                    detect_containment=cont,
                )
            else:
                etype = entity_type if entity_type != "auto" else "feature"
                stats = graph.merge_layer(gdf, entity_type=etype)

        # Persist to DB (best effort)
        try:
            kg_engine.save_graph(graph, f"kg_{'_'.join(source_names)}", source_names)
        except Exception:
            pass

        result = {
            "status": "success",
            "node_count": stats.node_count,
            "edge_count": stats.edge_count,
            "entity_types": stats.entity_types,
            "relationship_types": stats.relationship_types,
            "connected_components": stats.connected_components,
            "density": round(stats.density, 4),
            "source_files": source_names,
        }
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        traceback.print_exc()
        return f"Error: {e}"


def query_knowledge_graph(
    query_type: str = "stats",
    node_id: str = "",
    entity_type: str = "",
    depth: str = "1",
    target_node: str = "",
) -> str:
    """查询知识图谱中的实体关系。

    Args:
        query_type: 查询类型（stats/neighbors/path/type）。
        node_id: 目标节点ID（neighbors/path查询需要）。
        entity_type: 实体类型（type查询需要）。
        depth: 邻居查询深度（默认1）。
        target_node: 路径查询的目标节点（path查询需要）。

    Returns:
        JSON格式的查询结果。
    """
    try:
        graph = _get_or_create_graph()

        if query_type == "stats":
            from dataclasses import asdict
            stats = graph.get_stats()
            return json.dumps(asdict(stats), ensure_ascii=False, indent=2, default=str)

        elif query_type == "neighbors":
            if not node_id:
                return "Error: neighbors查询需要提供node_id。"
            result = graph.query_neighbors(
                node_id, depth=int(depth),
            )
            return json.dumps(result, ensure_ascii=False, indent=2, default=str)

        elif query_type == "path":
            if not node_id or not target_node:
                return "Error: path查询需要提供node_id和target_node。"
            result = graph.query_path(node_id, target_node)
            return json.dumps(result, ensure_ascii=False, indent=2, default=str)

        elif query_type == "type":
            if not entity_type:
                return "Error: type查询需要提供entity_type。"
            results = graph.query_by_type(entity_type)
            return json.dumps(
                {"entity_type": entity_type, "count": len(results), "nodes": results},
                ensure_ascii=False, indent=2, default=str,
            )

        else:
            return f"Error: 未知的查询类型 '{query_type}'。支持: stats, neighbors, path, type"
    except Exception as e:
        traceback.print_exc()
        return f"Error: {e}"


def export_knowledge_graph(format: str = "json") -> str:
    """导出当前知识图谱。

    Args:
        format: 导出格式（json）。

    Returns:
        JSON格式的图谱数据或导出文件路径。
    """
    try:
        graph = _get_or_create_graph()

        if graph.graph.number_of_nodes() == 0:
            return json.dumps({"status": "empty", "message": "知识图谱为空，请先构建图谱。"})

        data = graph.export_to_json()
        from dataclasses import asdict
        stats = graph.get_stats()

        result = {
            "status": "success",
            "format": format,
            "stats": asdict(stats),
            "graph": data,
        }
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        traceback.print_exc()
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Toolset class
# ---------------------------------------------------------------------------

_ALL_FUNCS = [
    build_knowledge_graph,
    query_knowledge_graph,
    export_knowledge_graph,
]


class KnowledgeGraphToolset(BaseToolset):
    """Geographic Knowledge Graph toolset -- build and query entity-relationship graphs."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
