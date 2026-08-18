"""Deterministic Chainlit conversation flow for UWM multi-stage planning."""

from __future__ import annotations

from typing import Any

from data_agent.i18n import t


ACTION_LABELS = {
    "increase_green_infrastructure": "uwm_chat.action.increase_green_infrastructure",
    "traffic_emission_control": "uwm_chat.action.traffic_emission_control",
    "add_community_service": "uwm_chat.action.add_community_service",
}


def _action_label(action_type: Any) -> str:
    key = ACTION_LABELS.get(str(action_type))
    return t(key) if key else str(action_type or t("uwm_chat.action.unknown"))


def is_multistage_uwm_chat_message(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    explicit_mentions = (
        "@uwm规划",
        "@uwm多阶段",
        "@多阶段uwm",
        "@城市干预",
        "@uwm plan",
        "@uwm multistage",
        "@city intervention",
        "@تخطيط uwm",
        "@تدخل حضري",
    )
    if any(marker in normalized for marker in explicit_mentions):
        return True
    return "uwm" in normalized and any(
        marker in normalized
        for marker in (
            "多阶段", "城市干预", "状态数据", "未来规划",
            "multistage", "city intervention", "state data", "future planning",
            "تدخل", "بيانات الحالة", "التخطيط المستقبلي",
        )
    )


def format_state_inspection(inspection: dict[str, Any]) -> str:
    snapshot = inspection.get("state_snapshot") or {}
    candidate = inspection.get("candidate_action_summary") or {}
    foundation = inspection.get("data_foundation") or {}
    simulator = inspection.get("simulator_specification") or {}
    rows = snapshot.get("units") or []
    action_counts = candidate.get("action_type_counts") or {}
    state_lines = "\n".join(
        t(
            "uwm_chat.state.row",
            display_name=row.get("display_name"),
            heat_risk=row.get("heat_risk"),
            air_pollution_exposure=row.get("air_pollution_exposure"),
            service_accessibility=row.get("service_accessibility"),
            equity=row.get("equity"),
            livability=row.get("livability"),
            candidate_action_count=row.get("candidate_action_count"),
        )
        for row in rows
    )
    action_lines = "\n".join(
        t(
            "uwm_chat.state.action_count",
            action=_action_label(action_type),
            count=count,
        )
        for action_type, count in action_counts.items()
    ) or t("uwm_chat.state.no_actions")
    return (
        f"{t('uwm_chat.state.title')}\n\n"
        f"{t('uwm_chat.state.scenario', display_name=(inspection.get('scenario') or {}).get('display_name'))}\n\n"
        f"{t('uwm_chat.state.section_input')}\n\n"
        f"{t('uwm_chat.state.planning_scope', count=snapshot.get('unit_count'))}\n"
        f"{t('uwm_chat.state.dimensions', count=snapshot.get('state_dimension_count'), dimensions=t('uwm_chat.list_separator').join(snapshot.get('state_dimensions') or []))}\n"
        f"{t('uwm_chat.state.foundation', nodes=foundation.get('graph_node_count'), edges=foundation.get('graph_edge_count'))}\n\n"
        f"{state_lines}\n\n"
        f"{t('uwm_chat.state.section_actions')}\n\n"
        f"{t('uwm_chat.state.candidate_count', count=candidate.get('candidate_action_count'))}\n"
        f"{action_lines}\n"
        f"{t('uwm_chat.state.instance_definition')}\n\n"
        f"{t('uwm_chat.state.section_capability')}\n\n"
        f"{t('uwm_chat.state.simulator', inputs=simulator.get('input_dimension'), outputs=simulator.get('output_dimension'), coefficients=simulator.get('coefficient_count'))}\n"
        f"{t('uwm_chat.state.kernel')}\n"
        f"{t('uwm_chat.state.planner')}\n"
        f"{t('uwm_chat.state.baseline')}\n\n"
        f"{t('uwm_chat.state.section_status')}\n\n"
        f"> {t('uwm_chat.state.status_not_run')}\n\n"
        f"{t('uwm_chat.state.map_sent')}"
    )


def format_scenario_parse(parse_result: dict[str, Any]) -> str:
    interpretation = parse_result.get("interpretation") or {}
    resolution = parse_result.get("resolution") or {}
    request = parse_result.get("planning_request") or {}
    action_types = request.get("action_types") or []
    action_labels = [_action_label(value) for value in action_types]
    objectives = interpretation.get("objectives") or []
    constraints = interpretation.get("explicit_constraints") or []
    warning = str(resolution.get("warning") or "")
    parsed_horizon = interpretation.get("horizon")
    return (
        f"{t('uwm_chat.parse.title')}\n\n"
        f"{t('uwm_chat.parse.model', model=parse_result.get('model'))}\n"
        f"{t('uwm_chat.parse.latency', latency=parse_result.get('latency_ms'))}\n"
        f"{t('uwm_chat.parse.area', area=resolution.get('display_name'))}\n"
        f"{t('uwm_chat.parse.neighborhood', hops=request.get('neighborhood_hops'))}\n"
        f"{t('uwm_chat.parse.horizon', horizon=parsed_horizon or t('uwm_chat.parse.horizon_pending'))}\n"
        f"{t('uwm_chat.parse.actions', actions=t('uwm_chat.list_separator').join(action_labels))}\n"
        f"{t('uwm_chat.parse.objectives', objectives=t('uwm_chat.list_separator').join(objectives) if objectives else t('uwm_chat.parse.objectives_default'))}\n"
        f"{t('uwm_chat.parse.constraints', constraints=t('uwm_chat.constraint_separator').join(constraints) if constraints else t('uwm_chat.parse.none'))}\n"
        f"{t('uwm_chat.parse.uncertainty', preference=interpretation.get('uncertainty_preference'))}\n"
        f"{t('uwm_chat.parse.summary', summary=interpretation.get('summary') or t('uwm_chat.parse.not_provided'))}\n"
        + (f"{t('uwm_chat.parse.warning', warning=warning)}\n" if warning else "")
        + f"\n> {t('uwm_chat.parse.boundary')}"
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
            t(
                "uwm_chat.plan.step",
                index=index + 1,
                action=_action_label(action.get("action_type")),
                display=display,
            )
        )
    return (
        f"{t('uwm_chat.plan.title')}\n\n"
        f"{t('uwm_chat.plan.section_sequence')}\n\n"
        + "\n".join(steps)
        + f"\n\n{t('uwm_chat.plan.section_evidence')}\n\n"
        + t("uwm_chat.plan.evidence", horizon=search.get("horizon"), candidates=search.get("candidate_action_count"), imagined=search.get("evaluated_imagined_action_count"), completed=search.get("completed_sequence_count"), retained=search.get("retained_sequence_count"), switched=t("uwm_chat.yes") if dependency.get("state_update_changes_top_second_action") else t("uwm_chat.no"), changed=dependency.get("changed_action_rank_count"))
        + f"\n\n{t('uwm_chat.plan.section_execution')}\n\n"
        + t("uwm_chat.plan.execution", training=training.get("training_row_count"), holdout=training.get("holdout_row_count"), inputs=training.get("feature_count"), outputs=training.get("target_count"), coefficients=training.get("coefficient_count"), elapsed=runtime.get("total_ms"), run_id=run.get("run_id"))
        + f"\n\n{t('uwm_chat.plan.section_boundary')}\n\n"
        + t("uwm_chat.plan.boundary")
        + f"\n\n{t('uwm_chat.plan.map_sent')}"
    )
