"""Deterministic Chainlit conversation flow for UWM multi-stage planning."""

from __future__ import annotations

from typing import Any


ACTION_LABELS = {
    "increase_green_infrastructure": "增加绿色/降温基础设施",
    "traffic_emission_control": "实施交通排放治理",
    "add_community_service": "新增或改善社区公共服务",
}


def is_multistage_uwm_chat_message(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    explicit_mentions = (
        "@uwm规划",
        "@uwm多阶段",
        "@多阶段uwm",
        "@城市干预",
    )
    if any(marker in normalized for marker in explicit_mentions):
        return True
    return "uwm" in normalized and any(
        marker in normalized
        for marker in ("多阶段", "城市干预", "状态数据", "未来规划")
    )


def format_state_inspection(inspection: dict[str, Any]) -> str:
    snapshot = inspection.get("state_snapshot") or {}
    candidate = inspection.get("candidate_action_summary") or {}
    foundation = inspection.get("data_foundation") or {}
    simulator = inspection.get("simulator_specification") or {}
    rows = snapshot.get("units") or []
    action_counts = candidate.get("action_type_counts") or {}
    state_lines = "\n".join(
        (
            f"- **{row.get('display_name')}**：热风险 {row.get('heat_risk')}，"
            f"污染暴露 {row.get('air_pollution_exposure')}，服务可达性 {row.get('service_accessibility')}，"
            f"公平性 {row.get('equity')}，宜居性 {row.get('livability')}，"
            f"候选动作 {row.get('candidate_action_count')} 个"
        )
        for row in rows
    )
    action_lines = "\n".join(
        f"- {ACTION_LABELS.get(action_type, action_type)}：{count}个候选实例"
        for action_type, count in action_counts.items()
    ) or "- 当前范围没有候选动作。"
    return (
        "## UWM推演前状态体检\n\n"
        f"**场景**：{(inspection.get('scenario') or {}).get('display_name')}\n\n"
        "### 1. 当前输入UWM的状态\n\n"
        f"- 当前规划域：{snapshot.get('unit_count')}个空间单元\n"
        f"- 业务状态维度：{snapshot.get('state_dimension_count')}维，分别为"
        f"{'、'.join(snapshot.get('state_dimensions') or [])}\n"
        f"- 全域底座：{foundation.get('graph_node_count')}个状态节点、"
        f"{foundation.get('graph_edge_count')}条空间关系\n\n"
        f"{state_lines}\n\n"
        "### 2. 当前状态生成的候选动作\n\n"
        f"- 本场景候选动作实例：{candidate.get('candidate_action_count')}个\n"
        f"{action_lines}\n"
        "- 一个候选实例表示“一类动作模板 × 一个满足阈值的空间单元”，不是一种新政策。\n\n"
        "### 3. 如果确认推演，UWM会做什么\n\n"
        f"- Simulator：{simulator.get('input_dimension')}维输入 → "
        f"{simulator.get('output_dimension')}维下一状态变化，"
        f"{simulator.get('coefficient_count')}个系数；\n"
        "- Kernel：把目标单元变化传播到真实空间邻域；\n"
        "- Planner：生成第一步未来`t1`，写回世界后再选择第二步，而不是沿用初始排行榜；\n"
        "- 对照：同时比较传统静态排序、单步模型和多步但不写回状态的结果。\n\n"
        "### 4. 当前执行状态\n\n"
        "> 当前只读取并展示状态快照，**尚未训练Simulator、尚未执行未来推演、尚未形成规划结论**。\n\n"
        "当前输入状态已经发送到中间地图。请先检查地图和上述数据，再选择是否正式推演。"
    )


def format_scenario_parse(parse_result: dict[str, Any]) -> str:
    interpretation = parse_result.get("interpretation") or {}
    resolution = parse_result.get("resolution") or {}
    request = parse_result.get("planning_request") or {}
    action_types = request.get("action_types") or []
    action_labels = [ACTION_LABELS.get(str(value), str(value)) for value in action_types]
    objectives = interpretation.get("objectives") or []
    constraints = interpretation.get("explicit_constraints") or []
    warning = str(resolution.get("warning") or "")
    parsed_horizon = interpretation.get("horizon")
    return (
        "## Gemma4场景语义解析\n\n"
        f"- 解析模型：`{parse_result.get('model')}`（已真实调用）\n"
        f"- 解析耗时：{parse_result.get('latency_ms')}毫秒\n"
        f"- 规划区域：{resolution.get('display_name')}\n"
        f"- 邻域范围：{request.get('neighborhood_hops')}阶空间邻域\n"
        f"- 规划时域：{parsed_horizon or '未明确，确认时选择'}\n"
        f"- 允许动作：{'、'.join(action_labels)}\n"
        f"- 用户目标表述：{'、'.join(objectives) if objectives else '未额外指定，采用UWM综合保守回报'}\n"
        f"- 显式约束：{'；'.join(constraints) if constraints else '无'}\n"
        f"- 不确定性偏好：{interpretation.get('uncertainty_preference')}\n"
        f"- 语义复述：{interpretation.get('summary') or '未提供'}\n"
        + (f"- 数据解析提示：{warning}\n" if warning else "")
        + "\n> 区域、邻域、动作类型、时域和不确定性偏好会进入Planner；自由文本目标当前用于确认与解释，不会直接改写Simulator回报函数。Gemma4不生成数值变化或行动排序。"
    )


def format_plan_result(run: dict[str, Any]) -> str:
    selected = run.get("selected_sequence") or {}
    actions = selected.get("action_sequence") or []
    dependency = run.get("state_dependency_diagnostic") or {}
    search = run.get("planner_search_summary") or {}
    training = run.get("training_transparency") or {}
    runtime = run.get("runtime_profile") or {}
    steps = []
    for index, action in enumerate(actions):
        target = str(((action.get("target_units") or [""])[0]))
        parts = target.split("|")
        display = " · ".join(parts[:2]) if len(parts) >= 2 else target
        steps.append(
            f"{index + 1}. **{ACTION_LABELS.get(str(action.get('action_type')), action.get('action_type'))}** — {display}"
        )
    return (
        "## UWM多阶段城市干预规划完成\n\n"
        "### 推荐行动序列\n\n"
        + "\n".join(steps)
        + "\n\n### 世界模型能力证据\n\n"
        f"- 规划时域：{search.get('horizon')}步；\n"
        f"- 候选动作：{search.get('candidate_action_count')}个；\n"
        f"- 主搜索想象动作：{search.get('evaluated_imagined_action_count')}次；\n"
        f"- 完整未来序列：{search.get('completed_sequence_count')}条；\n"
        f"- 保留较优路径：{search.get('retained_sequence_count')}条；\n"
        f"- 第二步首选因状态写回发生切换："
        f"{'是' if dependency.get('state_update_changes_top_second_action') else '否'}；\n"
        f"- 发生名次变化的后续动作：{dependency.get('changed_action_rank_count')}个。\n\n"
        "### Simulator与执行\n\n"
        f"- 本次训练：{training.get('training_row_count')}/{training.get('holdout_row_count')}条训练/留出；\n"
        f"- 模型结构：{training.get('feature_count')}维输入 → {training.get('target_count')}维输出，"
        f"{training.get('coefficient_count')}个系数；\n"
        f"- 本地CPU完整运行：{runtime.get('total_ms')}毫秒；\n"
        f"- 运行ID：`{run.get('run_id')}`。\n\n"
        "### 能力边界\n\n"
        "该结果证明同场景动作条件预测、空间传播、状态写回和多阶段重规划能力；"
        "不证明现实政策因果效果，也不替代正式规划、投资或行政审批。\n\n"
        "第二步未来分叉已发送到中间地图。"
    )
