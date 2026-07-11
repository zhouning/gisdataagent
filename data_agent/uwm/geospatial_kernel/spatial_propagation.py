"""Evidence-bounded, relation-aware spatial propagation."""

from __future__ import annotations

from typing import Any

from .spatial_message import build_spatial_message, spatial_message_digest


MAX_LOCAL_DISTANCE_M = 300.0


def propagate_spatial_messages(
    *,
    graph: dict[str, Any],
    target_parcel_id: str,
    from_land_use_class: str,
    to_land_use_class: str,
    kernel_version: str,
) -> dict[str, Any]:
    """Propagate a parcel action through bounded local and cross-scale relations."""

    nodes = {str(node.get("node_id")): node for node in graph.get("nodes") or []}
    if target_parcel_id not in nodes or nodes[target_parcel_id].get("node_type") != "parcel":
        raise ValueError("target_parcel_missing")
    edges = sorted(graph.get("edges") or [], key=lambda row: str(row.get("edge_id")))
    messages = [
        build_spatial_message(
            source_node_id=target_parcel_id,
            target_node_id=target_parcel_id,
            relation_type="action_direct_transition",
            effect_type="land_use_state_change",
            direction="self",
            raw_evidence={
                "from_land_use_class": from_land_use_class,
                "to_land_use_class": to_land_use_class,
                "land_use_changed": from_land_use_class != to_land_use_class,
            },
            normalization_basis={"basis": "action_contract"},
            propagation_stage=0,
            support_level="authoritative_rule",
            uncertainty="none",
            review_priority="direct_action",
            kernel_version=kernel_version,
        )
    ]
    seen_keys = {_message_key(messages[0])}
    cycle_paths_skipped = 0

    for edge in edges:
        relation = edge.get("relation_type")
        source_matches = edge.get("source_node_id") == target_parcel_id
        reverse_parcel_relation = (
            edge.get("target_node_id") == target_parcel_id
            and relation in {"parcel_adjacent_parcel", "parcel_near_parcel"}
        )
        if not source_matches and not reverse_parcel_relation:
            continue
        target_id = str(
            edge.get("source_node_id") if reverse_parcel_relation else edge.get("target_node_id")
        )
        if target_id == target_parcel_id:
            cycle_paths_skipped += 1
            continue
        message = _local_message(
            edge=edge,
            target_node=nodes.get(target_id) or {},
            target_node_id=target_id,
            target_parcel_id=target_parcel_id,
            kernel_version=kernel_version,
            from_land_use_class=from_land_use_class,
            to_land_use_class=to_land_use_class,
            reverse_relation=reverse_parcel_relation,
        )
        if message is None:
            continue
        key = _message_key(message)
        if key in seen_keys:
            cycle_paths_skipped += 1
            continue
        seen_keys.add(key)
        messages.append(message)

    village_ids = sorted(
        {
            str(edge.get("target_node_id"))
            for edge in edges
            if edge.get("source_node_id") == target_parcel_id
            and edge.get("relation_type") == "parcel_within_village"
        }
    )
    for village_id in village_ids:
        village_message = _aggregate_message(
            source_id=target_parcel_id,
            target_id=village_id,
            relation_type="parcel_within_village",
            effect_type="village_land_use_structure_signal",
            stage=2,
            raw_evidence={
                "affected_parcel_count": 1,
                "from_land_use_class": from_land_use_class,
                "to_land_use_class": to_land_use_class,
                **_action_evidence(from_land_use_class, to_land_use_class),
            },
            support_level="bounded_proxy",
            kernel_version=kernel_version,
        )
        _append_unique(messages, seen_keys, village_message)
        for edge in edges:
            if edge.get("source_node_id") != village_id:
                continue
            target_id = str(edge.get("target_node_id"))
            target_type = (nodes.get(target_id) or {}).get("node_type")
            relation = edge.get("relation_type")
            if relation == "cross_scale_context" and target_type == "village_context":
                _append_unique(
                    messages,
                    seen_keys,
                    _aggregate_message(
                        source_id=village_id,
                        target_id=target_id,
                        relation_type=relation,
                        effect_type="direct_neighbor_village_context_signal",
                        stage=2,
                        raw_evidence={
                            "context_relation": edge.get("context_relation")
                            or "direct_village_neighbor",
                            **_action_evidence(from_land_use_class, to_land_use_class),
                        },
                        support_level=_bounded_support(edge.get("support_level")),
                        kernel_version=kernel_version,
                    ),
                )
            elif relation == "village_within_admin" and target_type == "admin_context":
                _append_unique(
                    messages,
                    seen_keys,
                    _aggregate_message(
                        source_id=village_id,
                        target_id=target_id,
                        relation_type=relation,
                        effect_type="admin_context_summary",
                        stage=3,
                        raw_evidence={
                            "affected_village_count": 1,
                            **_action_evidence(from_land_use_class, to_land_use_class),
                        },
                        support_level=_bounded_support(edge.get("support_level")),
                        kernel_version=kernel_version,
                    ),
                )

    messages.sort(key=lambda row: (row["propagation_stage"], row["message_id"]))
    return {
        "schema": "uwm.geospatial_kernel.spatial_propagation.v1",
        "target_parcel_id": target_parcel_id,
        "messages": messages,
        "message_digest": spatial_message_digest(messages),
        "summary": {
            "message_count": len(messages),
            "max_local_distance_m": MAX_LOCAL_DISTANCE_M,
            "cycle_paths_skipped": cycle_paths_skipped,
            "admin_propagation_stopped": True,
            "learned_effect_enabled": False,
            "policy_score_emitted": False,
        },
        "claim_boundary": {
            "max_claim_level": "bounded_action_conditioned_spatial_scenario"
        },
        "empirical_policy_effect_claim": False,
    }


def _local_message(
    *,
    edge: dict[str, Any],
    target_node: dict[str, Any],
    target_node_id: str,
    target_parcel_id: str,
    kernel_version: str,
    from_land_use_class: str,
    to_land_use_class: str,
    reverse_relation: bool,
) -> dict[str, Any] | None:
    relation = str(edge.get("relation_type"))
    target_id = target_node_id
    support = _bounded_support(edge.get("support_level"))
    if relation == "parcel_adjacent_parcel":
        shared = _float(edge.get("shared_boundary_length_m"))
        source_perimeter = _float(
            edge.get("target_perimeter_m") if reverse_relation else edge.get("source_perimeter_m")
        )
        target_perimeter = _float(
            edge.get("source_perimeter_m") if reverse_relation else edge.get("target_perimeter_m")
        )
        compatibility = str(edge.get("compatibility_status") or "unresolved")
        return build_spatial_message(
            source_node_id=target_parcel_id,
            target_node_id=target_id,
            relation_type=relation,
            effect_type="adjacent_land_use_compatibility_signal",
            direction="outbound",
            raw_evidence={
                "compatibility_status": compatibility,
                "shared_boundary_length_m": shared,
                "source_shared_boundary_ratio": _ratio(shared, source_perimeter),
                "target_shared_boundary_ratio": _ratio(shared, target_perimeter),
                **_action_evidence(from_land_use_class, to_land_use_class),
            },
            normalization_basis={
                "source": "source_perimeter_m",
                "target": "target_perimeter_m",
            },
            propagation_stage=1,
            support_level=support,
            uncertainty="bounded" if compatibility != "unresolved" else "unresolved",
            review_priority=_compatibility_priority(compatibility),
            kernel_version=kernel_version,
        )
    if relation == "parcel_near_parcel":
        distance = _float(edge.get("distance_m"))
        band = _distance_band(distance)
        if band is None:
            return None
        return build_spatial_message(
            source_node_id=target_parcel_id,
            target_node_id=target_id,
            relation_type=relation,
            effect_type="distance_bounded_land_use_context_signal",
            direction="outbound",
            raw_evidence={
                "distance_m": distance,
                "proxy_distance_band": band,
                **_action_evidence(from_land_use_class, to_land_use_class),
            },
            normalization_basis={"basis": "projected_distance_m", "max_distance_m": 300.0},
            propagation_stage=1,
            support_level=support,
            uncertainty="bounded",
            review_priority="distance_exposure",
            kernel_version=kernel_version,
        )
    if relation == "parcel_contains_resource":
        compatibility = str(edge.get("active_compatibility_status") or "unresolved")
        unmapped = target_node.get("mapping_status") == "unmapped" or compatibility == "unmapped"
        return build_spatial_message(
            source_node_id=target_parcel_id,
            target_node_id=target_id,
            relation_type=relation,
            effect_type="contained_planning_resource_signal",
            direction="outbound",
            raw_evidence={
                "intersection_ratio": round(_float(edge.get("intersection_ratio")), 9),
                "compatibility_status": compatibility,
                "mapping_status": target_node.get("mapping_status") or "unresolved",
                **_action_evidence(from_land_use_class, to_land_use_class),
            },
            normalization_basis={"basis": "target_parcel_intersection_ratio"},
            propagation_stage=1,
            support_level=support,
            uncertainty="unresolved" if unmapped or compatibility == "unresolved" else "bounded",
            review_priority="unmapped_object" if unmapped else _compatibility_priority(compatibility),
            kernel_version=kernel_version,
        )
    if relation == "parcel_near_facility":
        distance = _float(edge.get("distance_m"))
        band = _distance_band(distance)
        if band is None:
            return None
        compatibility = str(edge.get("active_compatibility_status") or "unresolved")
        return build_spatial_message(
            source_node_id=target_parcel_id,
            target_node_id=target_id,
            relation_type=relation,
            effect_type="nearby_facility_compatibility_signal",
            direction="outbound",
            raw_evidence={
                "distance_m": distance,
                "proxy_distance_band": band,
                "compatibility_status": compatibility,
                "mapping_status": target_node.get("mapping_status") or "unresolved",
                **_action_evidence(from_land_use_class, to_land_use_class),
            },
            normalization_basis={"basis": "projected_distance_m", "max_distance_m": 300.0},
            propagation_stage=1,
            support_level=support,
            uncertainty="unresolved" if compatibility == "unresolved" else "bounded",
            review_priority=_compatibility_priority(compatibility),
            kernel_version=kernel_version,
        )
    return None


def _aggregate_message(
    *,
    source_id: str,
    target_id: str,
    relation_type: str,
    effect_type: str,
    stage: int,
    raw_evidence: dict[str, Any],
    support_level: str,
    kernel_version: str,
) -> dict[str, Any]:
    return build_spatial_message(
        source_node_id=source_id,
        target_node_id=target_id,
        relation_type=relation_type,
        effect_type=effect_type,
        direction="upscale" if stage == 3 else "outbound",
        raw_evidence=raw_evidence,
        normalization_basis={"basis": "bounded_cross_scale_aggregation"},
        propagation_stage=stage,
        support_level=support_level,
        uncertainty="bounded",
        review_priority="cross_scale_context",
        kernel_version=kernel_version,
    )


def _append_unique(
    messages: list[dict[str, Any]], seen_keys: set[tuple[str, ...]], message: dict[str, Any]
) -> None:
    key = _message_key(message)
    if key not in seen_keys:
        seen_keys.add(key)
        messages.append(message)


def _message_key(message: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(message.get("source_node_id")),
        str(message.get("target_node_id")),
        str(message.get("relation_type")),
        str(message.get("effect_type")),
    )


def _distance_band(distance: float) -> str | None:
    if distance < 0.0 or distance > MAX_LOCAL_DISTANCE_M:
        return None
    if distance <= 50.0:
        return "0_50m"
    if distance <= 150.0:
        return "50_150m"
    return "150_300m"


def _compatibility_priority(status: str) -> str:
    if status in {"conflict", "prohibited", "potential_conflict"}:
        return "rule_or_potential_conflict"
    if status in {"unmapped", "unresolved"}:
        return "unmapped_or_unresolved"
    if status in {"potential_synergy", "compatible"}:
        return "opportunity_signal"
    return "manual_review"


def _bounded_support(value: Any) -> str:
    if value in {"deterministic_geometry", "authoritative_rule", "bounded_proxy"}:
        return str(value)
    return "bounded_proxy"


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0.0:
        return 0.0
    return round(numerator / denominator, 9)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _action_evidence(from_land_use_class: str, to_land_use_class: str) -> dict[str, Any]:
    return {
        "action_from_land_use_class": from_land_use_class,
        "action_to_land_use_class": to_land_use_class,
        "action_land_use_changed": from_land_use_class != to_land_use_class,
    }
