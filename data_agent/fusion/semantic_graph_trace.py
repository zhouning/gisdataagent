"""Semantic graph trace helpers for MMFE products.

The semantic graph is the machine-readable contract. Trace cards are compact,
agent-readable explanations for important nodes such as fields, value domains,
standard sources, rules and objectives.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from typing import Any


SEMANTIC_GRAPH_TRACE_SCHEMA = "mmfe.semantic_graph_trace.v1"


def build_semantic_graph_index(graph: dict) -> dict:
    """Build lookup indexes for an MMFE semantic graph."""
    if not isinstance(graph, dict):
        raise ValueError("semantic graph must be a JSON object")
    nodes = [node for node in graph.get("nodes") or [] if isinstance(node, dict)]
    edges = [edge for edge in graph.get("edges") or [] if isinstance(edge, dict)]
    nodes_by_id = {node.get("id"): node for node in nodes if node.get("id")}
    outgoing: dict[str, list[dict]] = defaultdict(list)
    incoming: dict[str, list[dict]] = defaultdict(list)
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if not source or not target:
            continue
        outgoing[source].append(edge)
        incoming[target].append(edge)
    return {
        "nodes_by_id": nodes_by_id,
        "outgoing": dict(outgoing),
        "incoming": dict(incoming),
        "node_type_distribution": dict(Counter(node.get("type") for node in nodes if node.get("type"))),
        "relationship_distribution": dict(
            Counter(edge.get("relationship") for edge in edges if edge.get("relationship"))
        ),
    }


def trace_semantic_graph_node(
    graph: dict,
    node_id: str,
    *,
    max_depth: int = 4,
    max_paths: int = 12,
) -> dict:
    """Trace a single semantic graph node to standards, rules, objectives and evidence."""
    index = build_semantic_graph_index(graph)
    nodes_by_id = index["nodes_by_id"]
    node = nodes_by_id.get(node_id)
    if not node:
        raise KeyError(f"semantic graph node not found: {node_id}")

    outgoing = _direct_edges(index, node_id, "out")
    incoming = _direct_edges(index, node_id, "in")
    path_targets = {
        "standard_source_paths": {"standard_source"},
        "value_domain_paths": {"value_domain"},
        "rule_paths": {"rule"},
        "objective_paths": {"optimization_objective"},
        "evidence_paths": {"evidence_index"},
    }
    paths = {
        key: _find_paths_to_types(
            index,
            node_id,
            target_types,
            max_depth=max_depth,
            max_paths=max_paths,
        )
        for key, target_types in path_targets.items()
    }
    return {
        "node": _node_ref(node),
        "summary_zh": _node_summary(node, outgoing, incoming, paths),
        "direct_relationships": outgoing + incoming,
        **paths,
    }


def build_semantic_trace_card_bundle(
    graph: dict,
    focus_node_ids: list[str] | None = None,
    *,
    max_depth: int = 4,
    max_paths_per_target: int = 8,
    timestamp: str | None = None,
) -> dict:
    """Build trace cards for selected nodes in an MMFE semantic graph."""
    index = build_semantic_graph_index(graph)
    nodes_by_id = index["nodes_by_id"]
    focus = _normalise_focus_nodes(nodes_by_id, focus_node_ids)
    cards = []
    missing = []
    for node_id in focus:
        if node_id not in nodes_by_id:
            missing.append(node_id)
            continue
        cards.append(
            trace_semantic_graph_node(
                graph,
                node_id,
                max_depth=max_depth,
                max_paths=max_paths_per_target,
            )
        )
    card_type_counts = Counter(card["node"]["type"] for card in cards)
    standard_source_path_count = sum(len(card.get("standard_source_paths") or []) for card in cards)
    return {
        "schema": SEMANTIC_GRAPH_TRACE_SCHEMA,
        "created_at": timestamp or datetime.now(timezone.utc).isoformat(),
        "source_graph_schema": graph.get("schema"),
        "source_graph_node_count": graph.get("node_count", len(nodes_by_id)),
        "source_graph_edge_count": graph.get("edge_count", 0),
        "trace_card_count": len(cards),
        "missing_focus_node_ids": missing,
        "focus_type_distribution": dict(card_type_counts),
        "standard_source_path_count": standard_source_path_count,
        "relationship_distribution": index["relationship_distribution"],
        "cards": cards,
    }


def _normalise_focus_nodes(nodes_by_id: dict[str, dict], focus_node_ids: list[str] | None) -> list[str]:
    if focus_node_ids:
        seen = set()
        ordered = []
        for node_id in focus_node_ids:
            if node_id and node_id not in seen:
                ordered.append(node_id)
                seen.add(node_id)
        return ordered
    priority_types = {"field", "value_domain", "standard_source", "rule", "optimization_objective"}
    return [
        node_id
        for node_id, node in sorted(nodes_by_id.items())
        if node.get("type") in priority_types
    ]


def _direct_edges(index: dict, node_id: str, direction: str) -> list[dict]:
    nodes = index["nodes_by_id"]
    if direction == "out":
        edges = index["outgoing"].get(node_id, [])
    else:
        edges = index["incoming"].get(node_id, [])
    rows = []
    for edge in edges:
        other_id = edge.get("target") if direction == "out" else edge.get("source")
        other = nodes.get(other_id, {"id": other_id, "type": "", "label": other_id})
        rows.append({
            "direction": direction,
            "relationship": edge.get("relationship"),
            "node": _node_ref(other),
            "properties": edge.get("properties") or {},
        })
    return rows


def _find_paths_to_types(
    index: dict,
    start_id: str,
    target_types: set[str],
    *,
    max_depth: int,
    max_paths: int,
) -> list[dict]:
    nodes = index["nodes_by_id"]
    queue = deque([(start_id, [], {start_id})])
    paths = []
    while queue and len(paths) < max_paths:
        current, path_edges, visited = queue.popleft()
        if len(path_edges) >= max_depth:
            continue
        for edge in index["outgoing"].get(current, []):
            target = edge.get("target")
            if not target or target in visited:
                continue
            next_edges = path_edges + [edge]
            target_node = nodes.get(target)
            if target_node and target_node.get("type") in target_types and target != start_id:
                paths.append(_format_path(nodes, start_id, next_edges))
                if len(paths) >= max_paths:
                    break
            queue.append((target, next_edges, visited | {target}))
    return paths


def _format_path(nodes_by_id: dict[str, dict], start_id: str, edges: list[dict]) -> dict:
    node_ids = [start_id]
    relationships = []
    for edge in edges:
        relationships.append(edge.get("relationship"))
        node_ids.append(edge.get("target"))
    node_refs = [_node_ref(nodes_by_id.get(node_id, {"id": node_id, "label": node_id, "type": ""})) for node_id in node_ids]
    parts = []
    for index, node in enumerate(node_refs):
        if index:
            parts.append(f"-[{relationships[index - 1]}]->")
        parts.append(node.get("label") or node.get("id"))
    return {
        "nodes": node_refs,
        "relationships": relationships,
        "path_text": " ".join(parts),
    }


def _node_ref(node: dict) -> dict:
    props = node.get("properties") or {}
    return {
        "id": node.get("id"),
        "type": node.get("type"),
        "label": node.get("label") or node.get("id"),
        "key_properties": _key_properties(props),
    }


def _key_properties(props: dict[str, Any]) -> dict:
    keep = [
        "field_name",
        "twm_semantic_key",
        "domain_code",
        "standard_identifier",
        "retrieval_status",
        "access_mode",
        "severity",
        "direction",
        "hard_constraint",
        "relation_type",
        "twm_usage",
    ]
    return {key: props[key] for key in keep if key in props and props[key] not in (None, "")}


def _node_summary(
    node: dict,
    outgoing: list[dict],
    incoming: list[dict],
    paths: dict[str, list[dict]],
) -> str:
    label = node.get("label") or node.get("id")
    node_type = node.get("type") or "node"
    standard_count = len(paths.get("standard_source_paths") or [])
    value_domain_count = len(paths.get("value_domain_paths") or [])
    rule_count = len(paths.get("rule_paths") or [])
    objective_count = len(paths.get("objective_paths") or [])
    parts = [f"{label} 是 MMFE 语义图中的 {node_type} 节点。"]
    parts.append(f"直接出边 {len(outgoing)} 条，直接入边 {len(incoming)} 条。")
    if value_domain_count:
        parts.append(f"可追溯到 {value_domain_count} 条值域路径。")
    if standard_count:
        parts.append(f"可追溯到 {standard_count} 条标准来源路径。")
    if rule_count:
        parts.append(f"关联 {rule_count} 条规则路径。")
    if objective_count:
        parts.append(f"关联 {objective_count} 条优化目标路径。")
    return "".join(parts)
