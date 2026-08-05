"""Deterministic chat presentation for governed ontology tool results."""

from __future__ import annotations

import json
from typing import Any


def parse_ontology_tool_response(value: Any) -> dict[str, Any] | None:
    """Unwrap common ADK response envelopes and return an ontology result."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return parse_ontology_tool_response(json.loads(value))
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(value, dict):
        return None
    if "ontology_evidence" in value and "result" in value:
        return value
    for key in ("result", "output", "response", "content"):
        if key in value:
            nested = parse_ontology_tool_response(value[key])
            if nested is not None:
                return nested
    return None


def format_ontology_result_for_chat(payload: dict[str, Any]) -> str:
    """Render ontology facts from structured evidence, without LLM rewriting."""
    plan = payload.get("query_plan") or {}
    result = payload.get("result") or {}
    query_type = plan.get("query_type")
    if payload.get("status") not in {None, "ok"}:
        body = str(result.get("message") or "本体查询未返回可用结果。")
    elif query_type == "hierarchy":
        body = _format_hierarchy(result)
    elif query_type == "transition_rules":
        body = _format_transitions(result)
    elif query_type == "relation_path":
        body = _format_relation_path(result)
    elif query_type == "concept_explanation":
        body = _format_concept(result)
    elif query_type == "schema_mapping":
        body = _format_mapping(result)
    elif query_type == "demo_scenario_analysis":
        body = _format_scenario(result)
    else:
        facts = [str(item) for item in result.get("answer_facts") or [] if item]
        body = "\n".join(f"- {item}" for item in facts) or "本体查询已完成。"
    return f"{body}\n\n{_evidence_footer(payload)}"


def _format_hierarchy(result: dict[str, Any]) -> str:
    root = result.get("root") or {}
    graph = result.get("hierarchy") or {}
    nodes = {
        item.get("id"): item.get("data") or {}
        for item in graph.get("nodes") or []
        if item.get("id")
    }
    root_id = root.get("concept_id")
    edges = [
        edge
        for edge in graph.get("edges") or []
        if (edge.get("data") or {}).get("relationType") == "subClassOf"
    ]
    children_by_parent: dict[str, list[str]] = {}
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if source and target:
            children_by_parent.setdefault(target, []).append(source)

    def label(concept_id: str) -> str:
        node = nodes.get(concept_id) or {}
        text = node.get("label") or concept_id
        code = node.get("code")
        return f"{text} (`{code}`)" if code else str(text)

    direct = children_by_parent.get(root_id, [])
    preferred_codes = ["AgriculturalLand", "ConstructionLand", "UnusedLand"]
    direct.sort(
        key=lambda concept_id: (
            preferred_codes.index((nodes.get(concept_id) or {}).get("code"))
            if (nodes.get(concept_id) or {}).get("code") in preferred_codes
            else len(preferred_codes),
            str((nodes.get(concept_id) or {}).get("label") or concept_id),
        )
    )
    lines = [f"**{root.get('pref_label') or '本体'}的领域类层级**", ""]
    lines.append(f"{root.get('pref_label') or label(root_id)} (`{root.get('code') or ''}`)")
    for child_id in direct:
        lines.append(f"├─ {label(child_id)}")
        grandchildren = sorted(
            children_by_parent.get(child_id, []),
            key=lambda item: str((nodes.get(item) or {}).get("label") or item),
        )
        for index, grandchild_id in enumerate(grandchildren[:12]):
            branch = "└─" if index == len(grandchildren[:12]) - 1 else "├─"
            lines.append(f"│  {branch} {label(grandchild_id)}")
        if len(grandchildren) > 12:
            lines.append(f"│  └─ 其余 {len(grandchildren) - 12} 个下位类")
    lines.extend(
        [
            "",
            "关系方向：每条 `rdfs:subClassOf` 边都由子类指向父类。",
            (
                f"本次受限查询返回 {graph.get('node_count', 0)} 个节点、"
                f"{graph.get('edge_count', 0)} 条层级边；上面优先展示土地分类主线。"
            ),
        ]
    )
    return "\n".join(lines)


def _format_transitions(result: dict[str, Any]) -> str:
    subject = result.get("subject") or result.get("process") or {}
    target = result.get("target") or {}
    title = subject.get("pref_label") or "土地利用转换"
    if target.get("pref_label"):
        title += f" → {target['pref_label']}"
    lines = [f"**{title}的受治理转换规则**", ""]
    interpreted = result.get("interpreted_state") or {}
    interpreted_target = result.get("interpreted_target_state") or {}
    if interpreted:
        state_line = f"语义解释：{subject.get('pref_label')} → {interpreted.get('pref_label')}"
        if interpreted_target:
            state_line += f"；{target.get('pref_label')} → {interpreted_target.get('pref_label')}"
        lines.append(state_line)
    processes = result.get("processes")
    if processes is None and result.get("process"):
        processes = [result]
    processes = processes or []
    if not processes:
        lines.append("当前发布本体中没有命中该源/目标方向的受治理转换过程。")
    for item in processes:
        process = item.get("process") or {}
        sources = (
            "、".join(
                state.get("pref_label", "") for state in item.get("allowed_source_states") or []
            )
            or "未注册"
        )
        targets = (
            "、".join(
                state.get("pref_label", "") for state in item.get("allowed_target_states") or []
            )
            or "未注册"
        )
        lines.append(
            f"- **{process.get('pref_label') or process.get('code')}**：{sources} → {targets}"
        )
        requirements = {
            requirement.get("property") for requirement in item.get("semantic_requirements") or []
        }
        evidence = []
        if "authorizedBy" in requirements:
            evidence.append("审批文件")
        if "supportedBy" in requirements:
            evidence.append("法律政策依据")
        if evidence:
            lines.append(f"  证据要求：{'、'.join(evidence)}")
    return "\n".join(lines)


def _format_relation_path(result: dict[str, Any]) -> str:
    source = result.get("source") or {}
    target = result.get("target") or {}
    lines = [
        (
            f"**{source.get('pref_label', '源概念')}到"
            f"{target.get('pref_label', '目标概念')}的语义路径**"
        ),
        "",
    ]
    path = result.get("path") or []
    current = source.get("pref_label") or source.get("code") or "源概念"
    if not path:
        lines.append("在当前跳数和节点预算内未找到关系路径。")
    for step in path:
        direction = "→" if step.get("direction") == "out" else "←"
        relation = step.get("relation_type") or step.get("label") or "关联"
        next_label = step.get("target_label") or step.get("target")
        lines.append(f"- {current} {direction} `{relation}` {direction} {next_label}")
        current = next_label
    return "\n".join(lines)


def _format_concept(result: dict[str, Any]) -> str:
    concept = result.get("concept") or {}
    lines = [f"**{concept.get('pref_label') or concept.get('code')}**", ""]
    if concept.get("definition"):
        lines.append(str(concept["definition"]))
    lines.append(f"建模角色：`{concept.get('kind', '未标注')}`")
    parents = result.get("parents") or []
    children = result.get("children") or []
    if parents:
        lines.append("直接上位类：" + "、".join(item.get("pref_label", "") for item in parents))
    if children:
        lines.append("直接下位类：" + "、".join(item.get("pref_label", "") for item in children))
    return "\n".join(lines)


def _format_mapping(result: dict[str, Any]) -> str:
    alignment = result.get("field_alignment") or {}
    curated = result.get("curated_application_mappings") or []
    return (
        "**字段到本体的语义映射**\n\n"
        f"确定性匹配结果：{len(alignment.get('items') or [])} 条；"
        f"已版本化应用映射：{len(curated)} 条。候选映射不会自动晋升为正式映射。"
    )


def _format_scenario(result: dict[str, Any]) -> str:
    scenario = result.get("scenario_result") or {}
    lines = ["**本体应用场景结果**", "", str(scenario.get("headline") or "场景执行完成。")]
    if scenario.get("decision_scope"):
        lines.append(f"\n结论边界：{scenario['decision_scope']}")
    layers = (result.get("map_update") or {}).get("layers") or []
    map_summary = result.get("map_update_summary") or {}
    layer_count = len(layers) or int(map_summary.get("layer_count") or 0)
    if layer_count:
        lines.append(f"地图已加载 {layer_count} 个结果图层。")
    attestation = scenario.get("attestation") or {}
    receipt = scenario.get("execution_receipt") or {}
    if attestation.get("passed") is True:
        receipt_id = str(receipt.get("receipt_id") or "").removeprefix("sha256:")
        lines.append(
            "执行证明：OKF 0.2 计算契约验证通过"
            + (f"，receipt `{receipt_id[:12]}`。" if receipt_id else "。")
        )
    return "\n".join(lines)


def _evidence_footer(payload: dict[str, Any]) -> str:
    evidence = payload.get("ontology_evidence") or {}
    okf = payload.get("okf_reference") or {}
    digest = str(evidence.get("content_sha256") or "")
    warnings = evidence.get("warnings") or []
    parts = [
        f"本体 `V{evidence.get('semantic_version', '-')}`",
        f"SHA-256 `{digest[:12]}`" if digest else "SHA-256 `-`",
        f"RDF `{evidence.get('rdf_store', '-')}`",
        f"权威源 `{evidence.get('authority_backend', '-')}`",
        (
            f"OKF `{okf.get('okf_version', '-')}:{okf.get('concept_id', '-')}`"
            if okf
            else "OKF `-`"
        ),
    ]
    footer = "证据：" + " | ".join(parts)
    if warnings:
        footer += "\n告警：" + "；".join(str(item) for item in warnings)
    return footer
