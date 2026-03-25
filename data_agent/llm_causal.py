"""LLM-based causal inference module (Angle B).

Uses Google Gemini for knowledge-driven causal reasoning about geographic
phenomena.  Four tool functions provide complementary capabilities:
  1. construct_causal_dag      — build a causal DAG from domain knowledge
  2. counterfactual_reasoning  — reason through "what-if" counterfactuals
  3. explain_causal_mechanism  — interpret Angle A statistical results
  4. generate_what_if_scenarios — structured scenario generation

All functions return JSON strings (ADK FunctionTool convention).
"""

import json
import logging
import os
import re
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import networkx as nx
import numpy as np
import pandas as pd

from google import genai as genai_client
from google.genai import types

from .gis_processors import _generate_output_path, _resolve_path
from .utils import _configure_fonts

logger = logging.getLogger(__name__)

# Dedicated GenAI client for causal reasoning (outside ADK agents)
_client = genai_client.Client()

# Model aliases
_MODEL_PRO = "gemini-2.5-pro"
_MODEL_FLASH = "gemini-2.5-flash"

# Node-type colors for DAG rendering
_NODE_COLORS = {
    "exposure": "#e74c3c",
    "outcome": "#2ecc71",
    "confounder": "#3498db",
    "mediator": "#f39c12",
    "collider": "#9b59b6",
    "instrument": "#1abc9c",
    "unknown": "#95a5a6",
}


# ====================================================================
#  Internal helpers — LLM interaction
# ====================================================================

def _call_gemini(model: str, prompt: str, timeout: int = 90_000) -> tuple[str, dict]:
    """Call Gemini and return (text, usage_dict).

    Logs token usage for observability.
    """
    response = _client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            http_options=types.HttpOptions(timeout=timeout),
        ),
    )
    text = response.text or ""
    usage = {}
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        um = response.usage_metadata
        usage = {
            "input_tokens": getattr(um, "prompt_token_count", 0) or 0,
            "output_tokens": getattr(um, "candidates_token_count", 0) or 0,
        }
        logger.info(
            "Gemini %s tokens — input: %d, output: %d",
            model, usage["input_tokens"], usage["output_tokens"],
        )
    return text, usage


def _parse_llm_json(text: str) -> dict:
    """Extract JSON object from LLM output.

    Tries fenced ```json...```, <json>...</json>, then raw json.loads.
    """
    # Try ```json ... ```
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try <json>...</json>
    m = re.search(r"<json>(.*?)</json>", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try raw — find first { ... last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError("无法从LLM输出中解析JSON")


# ====================================================================
#  Internal helpers — data summarisation
# ====================================================================

def _summarize_data_context(file_path: str, max_rows: int = 200) -> str:
    """Load file and create a concise text summary for LLM context."""
    try:
        path = _resolve_path(file_path)
        ext = os.path.splitext(path)[1].lower()
        if ext == ".csv":
            df = pd.read_csv(path, nrows=max_rows, encoding="utf-8-sig")
        elif ext in (".xls", ".xlsx"):
            df = pd.read_excel(path, nrows=max_rows)
        else:
            from .utils import _load_spatial_data
            df = _load_spatial_data(path)
            if len(df) > max_rows:
                df = df.head(max_rows)
    except Exception as exc:
        return f"[数据加载失败: {exc}]"

    lines = [
        f"数据维度: {df.shape[0]}行 x {df.shape[1]}列",
        f"列名: {', '.join(df.columns.tolist())}",
    ]

    # Numeric summary
    num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    if num_cols:
        desc = df[num_cols].describe().round(3)
        lines.append(f"数值统计:\n{desc.to_string()}")

    # Categorical value counts (first 3 cat columns)
    cat_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()[:3]
    for col in cat_cols:
        vc = df[col].value_counts().head(5)
        lines.append(f"[{col}] 值分布: {vc.to_dict()}")

    # Missing values
    missing = df.isnull().sum()
    missing = missing[missing > 0]
    if len(missing) > 0:
        lines.append(f"缺失值: {missing.to_dict()}")

    return "\n".join(lines)


# ====================================================================
#  Internal helpers — prompt builders
# ====================================================================

def _build_dag_prompt(question: str, domain: str,
                      data_summary: str | None,
                      geofm_available: bool) -> str:
    """Construct a causal DAG generation prompt."""
    domain_hints = {
        "urban_geography": "城市地理学领域,关注城市空间结构、土地利用、交通、人口、经济等因素之间的因果关系。",
        "ecological": "生态学领域,关注生物多样性、植被、气候、土壤、水文等生态系统要素之间的因果机制。",
        "agricultural": "农业地理学领域,关注农作物产量、土地利用、灌溉、施肥、气候等农业因子之间的因果路径。",
        "climate": "气候科学领域,关注气温、降水、NDVI、碳排放、城市热岛等气候-环境要素之间的因果网络。",
        "general": "地理空间分析,根据具体问题自动推断相关领域知识。",
    }
    domain_desc = domain_hints.get(domain, domain_hints["general"])

    data_block = ""
    if data_summary:
        data_block = f"""

## 可用数据上下文
{data_summary}
请结合数据中已有变量构建DAG,变量名尽量与数据列名对齐。"""

    geofm_block = ""
    if geofm_available:
        geofm_block = """

## AlphaEarth GeoFM嵌入
系统已接入AlphaEarth地理基础模型,可以提供64维空间嵌入向量作为空间混淆控制。
你可以在DAG中加入"空间嵌入(GeoFM)"作为一个特殊的混淆变量节点。"""

    return textwrap.dedent(f"""\
你是一位地理因果推断专家。请根据以下研究问题,构建一个因果有向无环图(DAG)。

## 研究问题
{question}

## 领域背景
{domain_desc}
{data_block}{geofm_block}

## 输出要求
请以严格JSON格式输出,不要包含其他文本:
```json
{{
  "nodes": [
    {{"name": "变量名", "type": "exposure/outcome/confounder/mediator/collider"}},
    ...
  ],
  "edges": [
    {{"from": "变量A", "to": "变量B", "mechanism": "简要因果机制描述"}},
    ...
  ],
  "explanation": "整体因果结构的解释(2-3段)",
  "identification_strategy": "推荐的识别策略(如IV、DID、RDD等)"
}}
```

## 注意事项
1. 节点type必须是以下之一: exposure, outcome, confounder, mediator, collider
2. DAG必须是有向无环图(无环路)
3. 至少识别出关键混淆变量和可能的中介路径
4. edges中的mechanism要简洁但准确
5. 变量数量控制在合理范围内""")


def _build_counterfactual_prompt(question: str, data_summary: str | None,
                                 treatment: str, time_range: str,
                                 spatial_ctx: str) -> str:
    """Construct a counterfactual reasoning prompt."""
    data_block = ""
    if data_summary:
        data_block = f"\n## 观测数据摘要\n{data_summary}\n"

    time_block = f"\n## 时间范围\n{time_range}" if time_range else ""
    spatial_block = f"\n## 空间范围\n{spatial_ctx}" if spatial_ctx else ""

    return textwrap.dedent(f"""\
你是一位地理因果推断专家,擅长反事实推理。请分析以下反事实问题。

## 反事实问题
{question}

## 干预/处理描述
{treatment}
{data_block}{time_block}{spatial_block}

## 输出要求
请以严格JSON格式输出:
```json
{{
  "counterfactual_chain": [
    {{
      "step": 1,
      "cause": "初始干预/处理",
      "effect": "第一级效应",
      "mechanism": "传导机制描述",
      "time_lag": "预估时滞(如: 1-2年)"
    }},
    ...
  ],
  "estimated_effect": {{
    "direction": "positive/negative/ambiguous",
    "magnitude": "large/moderate/small/negligible",
    "description": "定量或定性的效应估计"
  }},
  "confidence": "high/medium/low",
  "key_assumptions": ["假设1", "假设2", ...],
  "sensitivity_factors": [
    {{"factor": "因素名", "impact": "该因素变化如何影响结论"}}
  ],
  "analogous_cases": ["参考案例1", "参考案例2"]
}}
```

## 注意事项
1. 反事实链条应当逻辑清晰,每步因果关系都有明确的机制
2. 考虑时间滞后效应和空间溢出效应
3. 明确关键假设和可能的敏感性因素
4. 如有类似历史案例可以参考""")


def _build_mechanism_prompt(stat_result_parsed: dict, method: str,
                            question: str, domain: str) -> str:
    """Construct a mechanism explanation prompt for Angle A output."""
    domain_hints = {
        "urban_geography": "城市地理学",
        "ecological": "生态学",
        "agricultural": "农业地理学",
        "climate": "气候科学",
        "general": "地理空间分析",
    }
    domain_label = domain_hints.get(domain, "地理空间分析")

    # Format key metrics
    metrics_lines = []
    key_fields = [
        ("method", "方法"), ("ate", "ATE"), ("att", "ATT"),
        ("p_value", "p值"), ("coefficient", "系数"),
        ("rho_x_causes_y", "X→Y因果强度"), ("rho_y_causes_x", "Y→X因果强度"),
        ("causal_direction", "因果方向"), ("convergence", "收敛性"),
        ("effect_direction", "效应方向"), ("granger_f_stat", "F统计量"),
        ("feature_importance", "特征重要度"),
    ]
    for field, label in key_fields:
        if field in stat_result_parsed:
            val = stat_result_parsed[field]
            if isinstance(val, float):
                metrics_lines.append(f"- {label}: {val:.4f}")
            else:
                metrics_lines.append(f"- {label}: {val}")
    metrics_block = "\n".join(metrics_lines) if metrics_lines else "无关键指标"

    return textwrap.dedent(f"""\
你是一位地理因果推断专家。以下是使用统计方法得到的因果推断结果,
请从{domain_label}领域知识角度,解释其背后的因果机制。

## 研究问题
{question}

## 统计方法
{method}

## 关键统计结果
{metrics_block}

## 完整统计输出
{json.dumps(stat_result_parsed, ensure_ascii=False, indent=2, default=str)}

## 输出要求
请以严格JSON格式输出:
```json
{{
  "mechanism_explanation": "1-2段因果机制解释,结合领域知识",
  "causal_pathway": [
    {{"from": "变量A", "to": "变量B", "mechanism": "传导机制"}}
  ],
  "alternative_explanations": ["替代解释1", "替代解释2"],
  "limitations": ["局限性1", "局限性2"],
  "suggested_robustness_checks": [
    {{"check": "稳健性检验名称", "reason": "建议原因", "method": "具体方法"}}
  ],
  "confidence_assessment": {{
    "level": "high/medium/low",
    "reasoning": "置信度评估的理由"
  }}
}}
```

## 注意事项
1. 解释要结合{domain_label}领域的具体知识,不能仅重述统计数字
2. 替代解释应该考虑遗漏变量偏误、逆因果、测量误差等
3. 稳健性检验建议应具有可操作性""")


def _build_scenario_prompt(context: str, n: int, target: str,
                           constraint: str) -> str:
    """Construct a scenario generation prompt."""
    constraint_block = f"\n## 约束条件\n{constraint}" if constraint else ""

    return textwrap.dedent(f"""\
你是一位地理空间分析和城市规划专家。请根据以下背景信息,
生成{n}个结构化的"假如"(what-if)情景。

## 背景信息
{context}

## 目标变量
{target}
{constraint_block}

## 输出要求
请以严格JSON格式输出:
```json
{{
  "scenarios": [
    {{
      "name": "情景名称(简短)",
      "description": "情景描述(1-2句话)",
      "parameter_modifications": {{
        "参数名1": "修改描述或具体数值",
        "参数名2": "修改描述或具体数值"
      }},
      "expected_direction": "positive/negative/neutral",
      "expected_magnitude": "large/moderate/small",
      "reasoning": "为什么预期这个方向和幅度",
      "world_model_scenario": "urban_sprawl/ecological_restoration/agricultural_intensification/climate_adaptation/baseline",
      "time_horizon": "短期/中期/长期"
    }},
    ...
  ]
}}
```

## world_model_scenario映射说明
- urban_sprawl: 城市扩张/土地开发情景
- ecological_restoration: 生态修复/植被恢复情景
- agricultural_intensification: 农业集约化/种植调整情景
- climate_adaptation: 气候适应/极端天气情景
- baseline: 维持现状/无干预基准情景

## 注意事项
1. 每个情景应当有明确的因果逻辑
2. parameter_modifications应当具有可操作性
3. 情景之间应当有差异性(覆盖不同方向和幅度)
4. world_model_scenario必须是上述5个之一""")


# ====================================================================
#  Internal helpers — visualization
# ====================================================================

def _render_dag_plot(nodes: list[dict], edges: list[dict]) -> str:
    """Render causal DAG using networkx + matplotlib. Returns saved file path."""
    _configure_fonts()

    G = nx.DiGraph()
    for node in nodes:
        name = node.get("name", "?")
        ntype = node.get("type", "unknown")
        G.add_node(name, type=ntype)

    for edge in edges:
        src = edge.get("from", "")
        dst = edge.get("to", "")
        mech = edge.get("mechanism", "")
        if src and dst:
            G.add_edge(src, dst, mechanism=mech)

    fig, ax = plt.subplots(figsize=(12, 8))
    ax.set_title("因果有向无环图 (Causal DAG)", fontsize=14, fontweight="bold")

    # Layout — use dot-like layout for DAGs
    try:
        pos = nx.nx_agraph.graphviz_layout(G, prog="dot")
    except Exception:
        try:
            pos = nx.planar_layout(G)
        except Exception:
            pos = nx.spring_layout(G, seed=42, k=2.0)

    # Node colors
    node_list = list(G.nodes())
    colors = [_NODE_COLORS.get(G.nodes[n].get("type", "unknown"), "#95a5a6")
              for n in node_list]

    nx.draw_networkx_nodes(G, pos, nodelist=node_list, node_color=colors,
                           node_size=2000, alpha=0.9, ax=ax)
    nx.draw_networkx_labels(G, pos, font_size=9, font_family="sans-serif", ax=ax)
    nx.draw_networkx_edges(G, pos, edge_color="#555555", arrows=True,
                           arrowsize=20, arrowstyle="-|>",
                           connectionstyle="arc3,rad=0.1", ax=ax)

    # Edge labels (mechanisms)
    edge_labels = {}
    for u, v, data in G.edges(data=True):
        mech = data.get("mechanism", "")
        if mech and len(mech) <= 20:
            edge_labels[(u, v)] = mech
        elif mech:
            edge_labels[(u, v)] = mech[:18] + "..."
    if edge_labels:
        nx.draw_networkx_edge_labels(G, pos, edge_labels, font_size=7, ax=ax)

    # Legend
    legend_patches = []
    seen = set()
    for n in node_list:
        ntype = G.nodes[n].get("type", "unknown")
        if ntype not in seen:
            seen.add(ntype)
            label_map = {
                "exposure": "暴露/处理",
                "outcome": "结果",
                "confounder": "混淆变量",
                "mediator": "中介变量",
                "collider": "碰撞变量",
                "instrument": "工具变量",
                "unknown": "其他",
            }
            legend_patches.append(
                mpatches.Patch(color=_NODE_COLORS.get(ntype, "#95a5a6"),
                               label=label_map.get(ntype, ntype))
            )
    if legend_patches:
        ax.legend(handles=legend_patches, loc="upper left", fontsize=8)

    ax.axis("off")
    plt.tight_layout()

    out_path = _generate_output_path("causal_dag", "png")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("DAG plot saved to %s", out_path)
    return out_path


def _render_counterfactual_chain(chain: list[dict]) -> str:
    """Render counterfactual chain as a flowchart using matplotlib.

    Returns saved file path.
    """
    _configure_fonts()

    n_steps = len(chain)
    if n_steps == 0:
        return ""

    fig_height = max(4, n_steps * 1.8 + 1)
    fig, ax = plt.subplots(figsize=(10, fig_height))
    ax.set_title("反事实推理链 (Counterfactual Chain)", fontsize=13,
                 fontweight="bold", pad=15)

    # Draw boxes top-to-bottom
    box_width = 0.7
    box_height = 0.12
    x_center = 0.5
    y_top = 0.92
    y_step = min(0.16, 0.85 / max(n_steps, 1))

    for i, step in enumerate(chain):
        y = y_top - i * y_step
        cause = step.get("cause", "?")
        effect = step.get("effect", "?")
        mechanism = step.get("mechanism", "")
        time_lag = step.get("time_lag", "")

        # Box for cause→effect
        label = f"Step {step.get('step', i+1)}: {cause}"
        if len(label) > 40:
            label = label[:37] + "..."
        effect_label = f"→ {effect}"
        if len(effect_label) > 40:
            effect_label = effect_label[:37] + "..."

        # Draw rounded box
        bg_color = "#3498db" if i == 0 else ("#2ecc71" if i == n_steps - 1 else "#f39c12")
        rect = mpatches.FancyBboxPatch(
            (x_center - box_width / 2, y - box_height / 2),
            box_width, box_height,
            boxstyle="round,pad=0.01",
            facecolor=bg_color, edgecolor="#2c3e50", alpha=0.85,
            transform=ax.transAxes,
        )
        ax.add_patch(rect)

        ax.text(x_center, y + 0.015, label, ha="center", va="center",
                fontsize=8, fontweight="bold", color="white",
                transform=ax.transAxes)
        ax.text(x_center, y - 0.025, effect_label, ha="center", va="center",
                fontsize=7, color="white", transform=ax.transAxes)

        # Mechanism annotation on the right
        if mechanism:
            mech_text = mechanism if len(mechanism) <= 30 else mechanism[:27] + "..."
            side_text = mech_text
            if time_lag:
                side_text += f" [{time_lag}]"
            ax.text(x_center + box_width / 2 + 0.02, y, side_text,
                    ha="left", va="center", fontsize=6, color="#7f8c8d",
                    style="italic", transform=ax.transAxes)

        # Arrow between boxes
        if i < n_steps - 1:
            arrow_y = y - box_height / 2 - 0.005
            arrow_end = y - y_step + box_height / 2 + 0.005
            ax.annotate(
                "", xy=(x_center, arrow_end), xytext=(x_center, arrow_y),
                xycoords="axes fraction", textcoords="axes fraction",
                arrowprops=dict(arrowstyle="-|>", color="#2c3e50", lw=1.5),
            )

    ax.axis("off")
    plt.tight_layout()

    out_path = _generate_output_path("counterfactual_chain", "png")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Counterfactual chain plot saved to %s", out_path)
    return out_path


def _nodes_to_mermaid(nodes: list[dict], edges: list[dict]) -> str:
    """Generate a Mermaid diagram string from DAG nodes/edges."""
    lines = ["graph TD"]
    # Node definitions with style classes
    type_shapes = {
        "exposure": ("([", "])"),
        "outcome": ("[[", "]]"),
        "confounder": ("{{", "}}"),
        "mediator": ("(", ")"),
        "collider": (">", "]"),
    }
    node_ids = {}
    for i, node in enumerate(nodes):
        name = node.get("name", f"V{i}")
        ntype = node.get("type", "unknown")
        nid = f"V{i}"
        node_ids[name] = nid
        left, right = type_shapes.get(ntype, ("(", ")"))
        lines.append(f"    {nid}{left}\"{name}\"{right}")

    for edge in edges:
        src = node_ids.get(edge.get("from", ""), "")
        dst = node_ids.get(edge.get("to", ""), "")
        mech = edge.get("mechanism", "")
        if src and dst:
            if mech:
                short = mech if len(mech) <= 15 else mech[:12] + "..."
                lines.append(f"    {src} -->|{short}| {dst}")
            else:
                lines.append(f"    {src} --> {dst}")

    return "\n".join(lines)


# ====================================================================
#  Tool 1: Construct Causal DAG
# ====================================================================

def construct_causal_dag(
    question: str,
    domain: str = "general",
    context_file: str = "",
    max_variables: int = 12,
    use_geofm_embedding: bool = False,
) -> str:
    """基于LLM领域知识构建因果有向无环图(DAG)。

    利用Gemini大模型的领域知识,为地理因果推断问题构建结构化的因果DAG。
    自动生成DAG可视化图和Mermaid流程图。

    Args:
        question: 研究问题描述（如:"城市绿地面积对PM2.5浓度的因果影响"）
        domain: 领域 urban_geography/ecological/agricultural/climate/general
        context_file: 可选,数据文件路径,用于提取变量名和统计信息作为LLM上下文
        max_variables: DAG中最大变量数（默认12）
        use_geofm_embedding: 是否在DAG中加入AlphaEarth GeoFM嵌入节点

    Returns:
        JSON string with nodes, edges, confounders, mediators, colliders,
        dag_plot_path, mermaid_diagram, explanation, and token_usage.
    """
    try:
        # Data context
        data_summary = None
        if context_file:
            data_summary = _summarize_data_context(context_file)

        # Build prompt and call LLM
        prompt = _build_dag_prompt(question, domain, data_summary, use_geofm_embedding)
        if max_variables:
            prompt += f"\n6. 变量节点数量控制在{max_variables}个以内"

        raw_text, usage = _call_gemini(_MODEL_PRO, prompt)
        parsed = _parse_llm_json(raw_text)

        nodes = parsed.get("nodes", [])
        edges = parsed.get("edges", [])
        explanation = parsed.get("explanation", "")
        id_strategy = parsed.get("identification_strategy", "")

        # Classify node types
        confounders = [n["name"] for n in nodes if n.get("type") == "confounder"]
        mediators = [n["name"] for n in nodes if n.get("type") == "mediator"]
        colliders = [n["name"] for n in nodes if n.get("type") == "collider"]

        # Render DAG plot
        dag_plot_path = ""
        try:
            dag_plot_path = _render_dag_plot(nodes, edges)
        except Exception as exc:
            logger.warning("DAG plot rendering failed: %s", exc)

        # Generate Mermaid diagram
        mermaid = _nodes_to_mermaid(nodes, edges)

        return json.dumps({
            "status": "success",
            "method": "llm_causal_dag",
            "question": question,
            "domain": domain,
            "nodes": nodes,
            "edges": edges,
            "confounders": confounders,
            "mediators": mediators,
            "colliders": colliders,
            "n_nodes": len(nodes),
            "n_edges": len(edges),
            "dag_plot_path": dag_plot_path,
            "mermaid_diagram": mermaid,
            "explanation": explanation,
            "identification_strategy": id_strategy,
            "use_geofm_embedding": use_geofm_embedding,
            "token_usage": usage,
            "summary": (
                f"因果DAG构建完成: {len(nodes)}个变量, {len(edges)}条边, "
                f"混淆变量{len(confounders)}个, 中介变量{len(mediators)}个"
            ),
        }, ensure_ascii=False)

    except Exception as exc:
        logger.exception("construct_causal_dag failed")
        return json.dumps({
            "status": "error",
            "method": "llm_causal_dag",
            "error": str(exc),
        }, ensure_ascii=False)


# ====================================================================
#  Tool 2: Counterfactual Reasoning
# ====================================================================

def counterfactual_reasoning(
    question: str,
    observed_data_file: str = "",
    treatment_description: str = "",
    time_range: str = "",
    spatial_context: str = "",
) -> str:
    """基于LLM的地理反事实推理。

    利用Gemini大模型进行结构化的反事实推理,分析"如果某个干预没有发生/发生了,
    地理现象会如何变化"。自动生成反事实推理链的可视化。

    Args:
        question: 反事实问题（如:"如果2010年没有实施退耕还林政策,黄土高原的植被覆盖会如何变化?"）
        observed_data_file: 可选,观测数据文件路径
        treatment_description: 干预/处理措施描述
        time_range: 时间范围（如:"2010-2023"）
        spatial_context: 空间范围描述（如:"黄土高原地区"）

    Returns:
        JSON string with counterfactual_chain, estimated_effect, confidence,
        key_assumptions, sensitivity_factors, chain_plot_path, and token_usage.
    """
    try:
        # Data context
        data_summary = None
        if observed_data_file:
            data_summary = _summarize_data_context(observed_data_file)

        treatment = treatment_description or question

        prompt = _build_counterfactual_prompt(
            question, data_summary, treatment, time_range, spatial_context,
        )
        raw_text, usage = _call_gemini(_MODEL_PRO, prompt)
        parsed = _parse_llm_json(raw_text)

        chain = parsed.get("counterfactual_chain", [])
        estimated_effect = parsed.get("estimated_effect", {})
        confidence = parsed.get("confidence", "medium")
        assumptions = parsed.get("key_assumptions", [])
        sensitivity = parsed.get("sensitivity_factors", [])
        analogous = parsed.get("analogous_cases", [])

        # Render chain plot
        chain_plot_path = ""
        try:
            if chain:
                chain_plot_path = _render_counterfactual_chain(chain)
        except Exception as exc:
            logger.warning("Counterfactual chain plot rendering failed: %s", exc)

        direction = estimated_effect.get("direction", "unknown")
        magnitude = estimated_effect.get("magnitude", "unknown")

        return json.dumps({
            "status": "success",
            "method": "llm_counterfactual",
            "question": question,
            "counterfactual_chain": chain,
            "n_steps": len(chain),
            "estimated_effect": estimated_effect,
            "confidence": confidence,
            "key_assumptions": assumptions,
            "sensitivity_factors": sensitivity,
            "analogous_cases": analogous,
            "chain_plot_path": chain_plot_path,
            "token_usage": usage,
            "summary": (
                f"反事实推理完成: {len(chain)}步推理链, "
                f"效应方向={direction}, 幅度={magnitude}, "
                f"置信度={confidence}"
            ),
        }, ensure_ascii=False)

    except Exception as exc:
        logger.exception("counterfactual_reasoning failed")
        return json.dumps({
            "status": "error",
            "method": "llm_counterfactual",
            "error": str(exc),
        }, ensure_ascii=False)


# ====================================================================
#  Tool 3: Explain Causal Mechanism
# ====================================================================

def explain_causal_mechanism(
    statistical_result: str,
    method_name: str = "",
    question: str = "",
    domain: str = "general",
) -> str:
    """用LLM解释Angle A统计因果推断结果的因果机制。

    接收Angle A工具（PSM、DiD、ERF、Granger、GCCM、Causal Forest）的
    JSON输出,利用Gemini领域知识解释统计结果背后的因果机制。

    Args:
        statistical_result: Angle A工具的JSON输出字符串
        method_name: 统计方法名称（如:"PSM", "DiD", "Granger"等）
        question: 原始研究问题
        domain: 领域 urban_geography/ecological/agricultural/climate/general

    Returns:
        JSON string with mechanism_explanation, causal_pathway,
        alternative_explanations, limitations, suggested_robustness_checks,
        confidence_assessment, and token_usage.
    """
    try:
        # Parse statistical result
        if isinstance(statistical_result, str):
            try:
                stat_parsed = json.loads(statistical_result)
            except json.JSONDecodeError:
                stat_parsed = {"raw_text": statistical_result}
        else:
            stat_parsed = statistical_result

        # Auto-detect method if not provided
        if not method_name:
            method_name = stat_parsed.get("method", "unknown")

        prompt = _build_mechanism_prompt(stat_parsed, method_name, question, domain)
        raw_text, usage = _call_gemini(_MODEL_FLASH, prompt)
        parsed = _parse_llm_json(raw_text)

        mechanism = parsed.get("mechanism_explanation", "")
        pathway = parsed.get("causal_pathway", [])
        alternatives = parsed.get("alternative_explanations", [])
        limitations = parsed.get("limitations", [])
        robustness = parsed.get("suggested_robustness_checks", [])
        confidence = parsed.get("confidence_assessment", {})

        return json.dumps({
            "status": "success",
            "method": "llm_mechanism_explanation",
            "source_method": method_name,
            "question": question,
            "mechanism_explanation": mechanism,
            "causal_pathway": pathway,
            "alternative_explanations": alternatives,
            "limitations": limitations,
            "suggested_robustness_checks": robustness,
            "confidence_assessment": confidence,
            "token_usage": usage,
            "summary": (
                f"因果机制解释完成({method_name}): "
                f"{len(pathway)}条因果路径, "
                f"{len(alternatives)}个替代解释, "
                f"{len(robustness)}项稳健性检验建议"
            ),
        }, ensure_ascii=False)

    except Exception as exc:
        logger.exception("explain_causal_mechanism failed")
        return json.dumps({
            "status": "error",
            "method": "llm_mechanism_explanation",
            "error": str(exc),
        }, ensure_ascii=False)


# ====================================================================
#  Tool 4: Generate What-If Scenarios
# ====================================================================

def generate_what_if_scenarios(
    base_context: str,
    n_scenarios: int = 4,
    target_variable: str = "",
    constraint: str = "",
) -> str:
    """基于LLM生成结构化的what-if情景。

    利用Gemini生成多个假设情景,每个情景包含参数修改方案、预期效应方向、
    以及对应的World Model场景映射（用于与Angle C世界模型推演联动）。

    Args:
        base_context: 背景描述（研究区域、当前状况、关注的问题等）
        n_scenarios: 生成情景数量（默认4,最大8）
        target_variable: 目标变量名称（如:"PM2.5浓度", "植被覆盖率"）
        constraint: 约束条件描述（如:"不改变城市建设用地面积"）

    Returns:
        JSON string with scenarios list and token_usage.
    """
    try:
        n_scenarios = max(1, min(n_scenarios, 8))

        prompt = _build_scenario_prompt(base_context, n_scenarios,
                                        target_variable, constraint)
        raw_text, usage = _call_gemini(_MODEL_FLASH, prompt)
        parsed = _parse_llm_json(raw_text)

        scenarios = parsed.get("scenarios", [])

        # Validate world_model_scenario values
        valid_wm = {
            "urban_sprawl", "ecological_restoration",
            "agricultural_intensification", "climate_adaptation", "baseline",
        }
        for s in scenarios:
            if s.get("world_model_scenario") not in valid_wm:
                s["world_model_scenario"] = "baseline"

        return json.dumps({
            "status": "success",
            "method": "llm_what_if_scenarios",
            "base_context": base_context[:200],
            "target_variable": target_variable,
            "n_requested": n_scenarios,
            "n_generated": len(scenarios),
            "scenarios": scenarios,
            "token_usage": usage,
            "summary": (
                f"What-If情景生成完成: {len(scenarios)}个情景, "
                f"目标变量={target_variable or '未指定'}"
            ),
        }, ensure_ascii=False)

    except Exception as exc:
        logger.exception("generate_what_if_scenarios failed")
        return json.dumps({
            "status": "error",
            "method": "llm_what_if_scenarios",
            "error": str(exc),
        }, ensure_ascii=False)
