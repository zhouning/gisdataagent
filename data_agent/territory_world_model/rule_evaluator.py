from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace
from typing import Any, Iterable

from .evidence import build_evidence_chain
from .models import (
    StateBuildResult,
    TerritoryWorldModelAction,
    TwmAuditReport,
    TwmEvidenceItem,
    TwmLayerBinding,
    TwmPolicyRule,
    TwmProject,
    TwmRelationSpec,
    TwmReviewTask,
    TwmRuleEvaluationResult,
    TwmRuleHit,
    TwmRuleSet,
    TwmScenarioMetric,
    TwmStateObject,
    TwmStateRelation,
    jsonable,
    now_utc_iso,
)
from .rule_dsl import normalize_rule_body, validate_rule_body
from .utils import compact_text, safe_float, truthy


DEFAULT_RULE_SEVERITY_ORDER = {
    "blocking": 4,
    "critical": 3,
    "high": 2,
    "medium": 1,
    "low": 0,
    "info": -1,
}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _count_by_role(objects: Iterable[TwmStateObject]) -> dict[str, list[TwmStateObject]]:
    grouped: dict[str, list[TwmStateObject]] = defaultdict(list)
    for obj in objects:
        for key in {
            compact_text(obj.canonical_role),
            compact_text(obj.source_role),
            compact_text(obj.object_type),
        }:
            if key:
                grouped[key].append(obj)
    return grouped


def _resolve_rule_subjects(
    objects: list[TwmStateObject],
    rule_body: dict[str, Any],
) -> list[TwmStateObject]:
    subject = rule_body.get("subject") or {}
    object_type = compact_text(subject.get("object_type"))
    where = subject.get("where") or {}
    selected = [obj for obj in objects if obj.object_type == object_type or obj.canonical_role == object_type or obj.source_role == object_type]
    if not where:
        return selected
    filtered = []
    for obj in selected:
        if _matches_where(obj, where):
            filtered.append(obj)
    return filtered


def _matches_where(obj: TwmStateObject, where: dict[str, Any]) -> bool:
    attrs = obj.attributes or {}
    for field, expected in where.items():
        actual = attrs.get(field)
        if isinstance(expected, dict):
            if not _matches_condition(actual, expected):
                return False
            continue
        values = expected if isinstance(expected, list) else [expected]
        if actual not in values:
            return False
    return True


def _matches_condition(actual: Any, condition: dict[str, Any]) -> bool:
    for op, expected in condition.items():
        if op == "eq":
            if actual != expected:
                return False
        elif op == "in":
            if actual not in (expected or []):
                return False
        elif op == "gt":
            if _float(actual, float("-inf")) <= _float(expected, float("-inf")):
                return False
        elif op == "gte":
            if _float(actual, float("-inf")) < _float(expected, float("-inf")):
                return False
        elif op == "lt":
            if _float(actual, float("inf")) >= _float(expected, float("inf")):
                return False
        elif op == "lte":
            if _float(actual, float("inf")) > _float(expected, float("inf")):
                return False
        elif op == "exists":
            exists = actual not in (None, "", [], {})
            if bool(expected) != exists:
                return False
    return True


def _dominant_planning_zone(subject: TwmStateObject, relations: list[TwmStateRelation], objects: dict[str, TwmStateObject]) -> str:
    best_zone = ""
    best_area = -1.0
    for rel in relations:
        if rel.subject_object_id != subject.id:
            continue
        if rel.relation_type != "project_overlaps_planning_zone":
            continue
        target = objects.get(rel.object_object_id)
        if target is None:
            continue
        area = _float(rel.metrics.get("overlap_area_m2"), 0.0)
        if area > best_area:
            best_area = area
            best_zone = compact_text(
                target.attributes.get("plan_zone_type")
                or target.attributes.get("plan_zone_name")
                or target.attributes.get("zone_type")
                or target.object_code
            )
    return best_zone


def _dominant_relation_target(
    subject: TwmStateObject,
    relation_type: str,
    relations: list[TwmStateRelation],
    objects: dict[str, TwmStateObject],
) -> TwmStateObject | None:
    best_target = None
    best_area = -1.0
    for rel in relations:
        if rel.subject_object_id != subject.id or rel.relation_type != relation_type:
            continue
        target = objects.get(rel.object_object_id)
        if target is None:
            continue
        area = _float(rel.metrics.get("overlap_area_m2"), 0.0)
        if area > best_area:
            best_area = area
            best_target = target
    return best_target


def _approval_status_value(obj: TwmStateObject) -> str:
    return compact_text(
        obj.attributes.get("approval_status")
        or obj.attributes.get("decision_result")
        or obj.attributes.get("DKZT")
        or obj.attributes.get("task_status")
        or obj.attributes.get("review_result")
    )


def _review_status_allows_high_risk(status: str) -> bool:
    normalized = status.lower()
    allowed = {"in_review", "returned", "supplement_required", "conditional_approval", "conditional", "needs_supplement", "requires_supplementary_evidence"}
    return normalized in allowed


def _build_rule_hit(
    *,
    rule: TwmPolicyRule,
    state_version_id: str,
    subject: TwmStateObject,
    target: TwmStateObject | None,
    metrics: dict[str, Any],
    explanation: str,
    severity: str | None = None,
    hit_status: str = "open",
    risk_score: float = 0.0,
    geom: Any | None = None,
) -> TwmRuleHit:
    return TwmRuleHit(
        state_version_id=state_version_id,
        rule_id=rule.rule_code or rule.id,
        subject_object_id=subject.id,
        target_object_id=target.id if target is not None else None,
        hit_status=hit_status,
        severity=severity or rule.severity,
        risk_score=risk_score,
        metrics=metrics,
        explanation=explanation,
        geom=geom,
    )


class RuleEvaluator:
    """Deterministic policy evaluator for TWM state bundles."""

    def __init__(self, repository=None):
        from .repository import get_twm_repository

        self.repository = repository or get_twm_repository()

    def evaluate_state(
        self,
        state_bundle: StateBuildResult,
        rule_set: TwmRuleSet | None = None,
        rules: Iterable[TwmPolicyRule] | None = None,
        *,
        include_default_rules: bool = True,
        model_output: dict[str, Any] | None = None,
        scenario_context: dict[str, Any] | None = None,
    ) -> TwmRuleEvaluationResult:
        bundle = state_bundle
        state_version = bundle.state_version
        objects = list(bundle.objects)
        relations = list(bundle.relations)
        object_map = {obj.id: obj for obj in objects}
        grouped_objects = _count_by_role(objects)
        selected_rules = list(rules or [])
        if not selected_rules and rule_set is not None:
            selected_rules = self.repository.list_policy_rules(rule_set.id, enabled=True)
        if not selected_rules and include_default_rules:
            selected_rules = self._default_rules()

        hits: list[TwmRuleHit] = []
        evidence_items: list[TwmEvidenceItem] = []
        review_tasks: list[TwmReviewTask] = []
        warnings: list[str] = []
        severity_distribution: Counter[str] = Counter()

        # Data quality gate
        dq_hits = self._evaluate_data_quality_rule(bundle)
        if dq_hits:
            hits.extend(dq_hits)
            severity_distribution.update(hit.severity for hit in dq_hits)

        for rule in selected_rules:
            # System gates are evaluated once outside the generic rule loop.
            # They are still registered as policy rules so the rule catalog is
            # auditable, but they should not produce duplicate hits here.
            if rule.rule_code in {"TWM-DQ-001", "TWM-GOV-001"}:
                continue
            validation = validate_rule_body(rule.rule_body)
            if not validation.get("valid"):
                warnings.append(f"rule {rule.rule_code or rule.id} invalid: {'; '.join(validation.get('errors') or [])}")
                continue
            body = validation["normalized"]
            body_subjects = _resolve_rule_subjects(objects, body)
            if not body_subjects:
                continue
            generated = self._evaluate_rule(
                rule,
                state_bundle,
                body,
                body_subjects,
                object_map,
                grouped_objects,
                relations,
            )
            if not generated:
                continue
            hits.extend(generated["hits"])
            evidence_items.extend(generated["evidence_items"])
            review_tasks.extend(generated["review_tasks"])
            severity_distribution.update(hit.severity for hit in generated["hits"])

        if rule_set is not None and not selected_rules:
            warnings.append(f"rule_set {rule_set.id} has no enabled rules")

        # Approval consistency gate tied to high/critical hits.
        approval_hits = self._evaluate_approval_consistency(bundle, hits)
        if approval_hits:
            hits.extend(approval_hits["hits"])
            evidence_items.extend(approval_hits["evidence_items"])
            review_tasks.extend(approval_hits["review_tasks"])
            severity_distribution.update(hit.severity for hit in approval_hits["hits"])

        review_task_by_hit: dict[str, TwmReviewTask] = {}
        for task in review_tasks:
            if task.rule_hit_id:
                review_task_by_hit[task.rule_hit_id] = task

        # Final persistence.
        hits = self.repository.save_rule_hits(hits) if hasattr(self.repository, "save_rule_hits") else hits
        evidence_items = self.repository.save_evidence_items(evidence_items) if hasattr(self.repository, "save_evidence_items") else evidence_items
        review_tasks = self.repository.save_review_tasks(review_tasks) if hasattr(self.repository, "save_review_tasks") else review_tasks

        persisted_review_tasks: list[TwmReviewTask] = list(review_tasks)
        for hit in hits:
            if hit.review_task_id is None and hit.rule_id in {"TWM-DQ-001", "TWM-GOV-001"}:
                continue
            if hit.review_task_id is None and hit.severity in {"blocking", "critical", "high"} and hit.hit_status == "open":
                task = review_task_by_hit.get(hit.id)
                if task is None:
                    task = TwmReviewTask(rule_hit_id=hit.id, status="pending")
                    task = self.repository.save_review_task(task) if hasattr(self.repository, "save_review_task") else task
                    persisted_review_tasks.append(task)
                hit.review_task_id = task.id
                if hasattr(self.repository, "save_rule_hit"):
                    self.repository.save_rule_hit(hit)

        summary = {
            "state_version_id": state_version.id,
            "rule_count": len(selected_rules),
            "hit_count": len(hits),
            "review_task_count": len(persisted_review_tasks),
            "severity_distribution": dict(severity_distribution),
            "data_quality_hit_count": sum(1 for item in hits if item.rule_id == "TWM-DQ-001"),
            "approval_consistency_hit_count": sum(1 for item in hits if item.rule_id == "TWM-GOV-001"),
            "evidence_item_count": len(evidence_items),
            "warnings": warnings,
        }
        return TwmRuleEvaluationResult(
            state_version_id=state_version.id,
            rule_set_id=rule_set.id if rule_set else "",
            hits=hits,
            evidence_items=evidence_items,
            review_tasks=persisted_review_tasks,
            severity_distribution=dict(severity_distribution),
            summary=summary,
            warnings=warnings,
        )

    def _evaluate_rule(
        self,
        rule: TwmPolicyRule,
        state_bundle: StateBuildResult,
        body: dict[str, Any],
        subjects: list[TwmStateObject],
        object_map: dict[str, TwmStateObject],
        grouped_objects: dict[str, list[TwmStateObject]],
        relations: list[TwmStateRelation],
    ) -> dict[str, Any]:
        state_version = state_bundle.state_version
        hits: list[TwmRuleHit] = []
        evidence_items: list[TwmEvidenceItem] = []
        review_tasks: list[TwmReviewTask] = []
        constraint = body.get("constraint") or {}
        target_role = compact_text(constraint.get("target_role"))
        spatial_predicate = compact_text(constraint.get("spatial_predicate") or "intersects")
        review_policy = compact_text((body.get("review") or {}).get("policy")).lower()
        target_objects = grouped_objects.get(target_role) or grouped_objects.get(constraint.get("target_role") or "") or []
        target_objects = target_objects or self._fallback_targets(target_role, object_map.values())

        if rule.rule_code == "TWM-DQ-001":
            return self._evaluate_data_quality_rule(state_bundle)

        if rule.rule_code == "TWM-FARM-001":
            return self._evaluate_overlap_rule(
                state_bundle,
                rule,
                body,
                body_subjects=subjects,
                relation_type="project_overlaps_permanent_basic_farmland",
                relation_label="pbf",
                review_policy=review_policy,
            )
        if rule.rule_code == "TWM-ECO-001":
            return self._evaluate_overlap_rule(
                state_bundle,
                rule,
                body,
                body_subjects=subjects,
                relation_type="project_overlaps_ecological_redline",
                relation_label="eco_redline",
                review_policy=review_policy,
            )
        if rule.rule_code == "TWM-PLAN-001":
            return self._evaluate_planning_rule(state_bundle, rule, subjects, relations, object_map, review_policy)
        if rule.rule_code == "TWM-URBAN-001":
            return self._evaluate_urban_rule(state_bundle, rule, subjects, relations, object_map, review_policy)
        if rule.rule_code == "TWM-EVD-001":
            return self._evaluate_evidence_rule(state_bundle, rule, subjects, relations, object_map, review_policy)
        if rule.rule_code == "TWM-GOV-001":
            return {"hits": [], "evidence_items": [], "review_tasks": []}

        for subject in subjects:
            matches = self._match_targets(subject, target_objects, spatial_predicate, body, relations, object_map)
            if not matches:
                continue
            for match in matches:
                metrics = self._build_metrics(subject, match, spatial_predicate, body, relations)
                risk_score = self._risk_score(rule, metrics, body, subject, match)
                hit_status = "open"
                if rule.review_policy == "auto_pass" and risk_score <= 0.1:
                    hit_status = "auto_pass"
                elif rule.review_policy == "review_required":
                    hit_status = "open"
                elif rule.review_policy == "always_review":
                    hit_status = "open"
                explanation = self._build_explanation(rule, subject, match, metrics, body)
                hit = _build_rule_hit(
                    rule=rule,
                    state_version_id=state_version.id,
                    subject=subject,
                    target=match,
                    metrics=metrics,
                    explanation=explanation,
                    severity=rule.severity,
                    hit_status=hit_status,
                    risk_score=risk_score,
                    geom=match.geom or subject.geom,
                )
                hits.append(hit)
                evidence_items.extend(
                    self._build_evidence_items(hit, rule, subject, match, metrics, body, review_policy)
                )
                if hit.severity in {"blocking", "critical", "high"} or rule.review_policy == "always_review":
                    review_tasks.append(
                        TwmReviewTask(
                            rule_hit_id=hit.id,
                            assignee=None,
                            status="pending",
                            decision="",
                            comment="",
                        )
                    )

        return {
            "hits": hits,
            "evidence_items": evidence_items,
            "review_tasks": review_tasks,
        }

    def _evaluate_overlap_rule(
        self,
        state_bundle: StateBuildResult,
        rule: TwmPolicyRule,
        body: dict[str, Any],
        *,
        body_subjects: list[TwmStateObject],
        relation_type: str,
        relation_label: str,
        review_policy: str,
    ) -> dict[str, Any]:
        state_version = state_bundle.state_version
        relations = [rel for rel in state_bundle.relations if rel.relation_type == relation_type]
        objects = {obj.id: obj for obj in state_bundle.objects}
        grouped: dict[str, list[TwmStateRelation]] = defaultdict(list)
        for rel in relations:
            grouped[rel.subject_object_id].append(rel)

        hits: list[TwmRuleHit] = []
        evidence_items: list[TwmEvidenceItem] = []
        review_tasks: list[TwmReviewTask] = []
        for subject in body_subjects:
            rels = grouped.get(subject.id) or []
            if not rels:
                continue
            total_overlap = sum(_float(rel.metrics.get("overlap_area_m2"), 0.0) for rel in rels)
            if total_overlap <= 1.0:
                continue
            dominant = max(rels, key=lambda rel: _float(rel.metrics.get("overlap_area_m2"), 0.0))
            target = objects.get(dominant.object_object_id)
            if target is None:
                continue
            metrics = {
                "overlap_area_m2": round(total_overlap, 6),
                "dominant_overlap_area_m2": round(_float(dominant.metrics.get("overlap_area_m2"), 0.0), 6),
                "overlap_ratio_left": round(max(_float(rel.metrics.get("overlap_ratio_left"), 0.0) for rel in rels), 6),
                "overlap_ratio_right": round(max(_float(rel.metrics.get("overlap_ratio_right"), 0.0) for rel in rels), 6),
                "relation_count": len(rels),
                "relation_label": relation_label,
            }
            hit = _build_rule_hit(
                rule=rule,
                state_version_id=state_version.id,
                subject=subject,
                target=target,
                metrics=metrics,
                explanation=self._build_explanation(rule, subject, target, metrics, body),
                severity=rule.severity,
                hit_status="open",
                risk_score=self._risk_score(rule, metrics, body, subject, target),
                geom=subject.geom or target.geom,
            )
            hits.append(hit)
            evidence_items.extend(self._build_evidence_items(hit, rule, subject, target, metrics, body, review_policy))
            if rule.review_policy in {"review_required", "always_review"} or hit.severity in {"high", "critical", "blocking"}:
                review_tasks.append(TwmReviewTask(rule_hit_id=hit.id, status="pending"))
        return {"hits": hits, "evidence_items": evidence_items, "review_tasks": review_tasks}

    def _evaluate_planning_rule(
        self,
        state_bundle: StateBuildResult,
        rule: TwmPolicyRule,
        body_subjects: list[TwmStateObject],
        relations: list[TwmStateRelation],
        object_map: dict[str, TwmStateObject],
        review_policy: str,
    ) -> dict[str, Any]:
        state_version = state_bundle.state_version
        hits: list[TwmRuleHit] = []
        evidence_items: list[TwmEvidenceItem] = []
        review_tasks: list[TwmReviewTask] = []
        expected_by_type = {
            "construction_expansion": "urban_space",
            "industrial_site": "urban_space",
            "public_service": "urban_space",
            "rural_infrastructure": "urban_space",
            "rural_road": "urban_space",
            "tourism_facility": "urban_space",
            "mining_remediation": "ecological_space",
            "ecological_restoration": "ecological_space",
        }
        for subject in body_subjects:
            dominant_zone_rel = _dominant_relation_target(subject, "project_overlaps_planning_zone", relations, object_map)
            if dominant_zone_rel is None:
                continue
            dominant_zone = compact_text(
                dominant_zone_rel.attributes.get("plan_zone_type")
                or dominant_zone_rel.attributes.get("plan_zone_name")
                or dominant_zone_rel.attributes.get("zone_type")
                or dominant_zone_rel.object_code
            )
            project_type = compact_text(subject.attributes.get("project_type"))
            expected_zone = expected_by_type.get(project_type)
            if expected_zone and dominant_zone == expected_zone:
                continue
            metrics = {
                "dominant_zone_type": dominant_zone,
                "project_type": project_type,
                "expected_zone_type": expected_zone or "",
                "relation_count": sum(1 for rel in relations if rel.subject_object_id == subject.id and rel.relation_type == "project_overlaps_planning_zone"),
                "overlap_area_m2": round(sum(_float(rel.metrics.get("overlap_area_m2"), 0.0) for rel in relations if rel.subject_object_id == subject.id and rel.relation_type == "project_overlaps_planning_zone"), 6),
            }
            hit = _build_rule_hit(
                rule=rule,
                state_version_id=state_version.id,
                subject=subject,
                target=dominant_zone_rel,
                metrics=metrics,
                explanation=(
                    f"{rule.title}: project_type={project_type} dominant_plan_zone={dominant_zone} "
                    f"expected_zone={expected_zone or 'unknown'}"
                ),
                severity=rule.severity,
                hit_status="open",
                risk_score=self._risk_score(rule, metrics, {"review": {"policy": review_policy}}, subject, dominant_zone_rel),
                geom=subject.geom or dominant_zone_rel.geom,
            )
            hits.append(hit)
            evidence_items.extend(self._build_evidence_items(hit, rule, subject, dominant_zone_rel, metrics, {"constraint": {"target_role": "planning_zone"}}, review_policy))
            review_tasks.append(TwmReviewTask(rule_hit_id=hit.id, status="pending"))
        return {"hits": hits, "evidence_items": evidence_items, "review_tasks": review_tasks}

    def _evaluate_urban_rule(
        self,
        state_bundle: StateBuildResult,
        rule: TwmPolicyRule,
        body_subjects: list[TwmStateObject],
        relations: list[TwmStateRelation],
        object_map: dict[str, TwmStateObject],
        review_policy: str,
    ) -> dict[str, Any]:
        state_version = state_bundle.state_version
        hits: list[TwmRuleHit] = []
        evidence_items: list[TwmEvidenceItem] = []
        review_tasks: list[TwmReviewTask] = []
        construction_types = {"construction_expansion", "industrial_site", "public_service", "rural_infrastructure", "rural_road", "tourism_facility"}
        for subject in body_subjects:
            project_type = compact_text(subject.attributes.get("project_type"))
            if project_type not in construction_types:
                continue
            rels = [rel for rel in relations if rel.subject_object_id == subject.id and rel.relation_type == "project_overlaps_urban_development_boundary"]
            overlap_area = sum(_float(rel.metrics.get("overlap_area_m2"), 0.0) for rel in rels)
            if overlap_area > 0:
                continue
            target = _dominant_relation_target(subject, "project_overlaps_urban_development_boundary", relations, object_map)
            metrics = {
                "project_type": project_type,
                "inside_urban_boundary": False,
                "overlap_area_m2": 0.0,
                "relation_count": len(rels),
            }
            hit = _build_rule_hit(
                rule=rule,
                state_version_id=state_version.id,
                subject=subject,
                target=target or subject,
                metrics=metrics,
                explanation=(
                    f"{rule.title}: construction project {subject.object_code} is outside urban boundary"
                ),
                severity=rule.severity,
                hit_status="open",
                risk_score=self._risk_score(rule, metrics, {"review": {"policy": review_policy}}, subject, target or subject),
                geom=subject.geom,
            )
            hits.append(hit)
            evidence_items.extend(self._build_evidence_items(hit, rule, subject, target or subject, metrics, {"constraint": {"target_role": "urban_boundary"}}, review_policy))
            review_tasks.append(TwmReviewTask(rule_hit_id=hit.id, status="pending"))
        return {"hits": hits, "evidence_items": evidence_items, "review_tasks": review_tasks}

    def _evaluate_evidence_rule(
        self,
        state_bundle: StateBuildResult,
        rule: TwmPolicyRule,
        body_subjects: list[TwmStateObject],
        relations: list[TwmStateRelation],
        object_map: dict[str, TwmStateObject],
        review_policy: str,
    ) -> dict[str, Any]:
        state_version = state_bundle.state_version
        hits: list[TwmRuleHit] = []
        evidence_items: list[TwmEvidenceItem] = []
        review_tasks: list[TwmReviewTask] = []
        text_evidence_objects = [obj for obj in state_bundle.objects if obj.object_type == "multimodal_evidence_index" or obj.source_role == "multimodal_evidence_index"]
        evidence_by_project: dict[str, list[TwmStateObject]] = defaultdict(list)
        for item in text_evidence_objects:
            linked = compact_text(item.attributes.get("linked_object_id") or item.attributes.get("project_id") or item.attributes.get("object_id"))
            if linked:
                evidence_by_project[linked].append(item)
        rs_relations = [rel for rel in relations if rel.relation_type == "project_observed_by_remote_sensing_tile"]
        rs_count_by_project: Counter[str] = Counter()
        dominant_rs_target: dict[str, TwmStateObject] = {}
        for rel in rs_relations:
            rs_count_by_project[rel.subject_object_id] += 1
            prev = dominant_rs_target.get(rel.subject_object_id)
            if prev is None or _float(rel.metrics.get("overlap_area_m2"), 0.0) > _float(getattr(prev, "attributes", {}).get("overlap_area_m2"), 0.0):
                target = object_map.get(rel.object_object_id)
                if target is not None:
                    dominant_rs_target[rel.subject_object_id] = target
        for subject in body_subjects:
            project_keys = [
                compact_text(subject.attributes.get("project_id")),
                compact_text((subject.attributes.get("canonical_fields") or {}).get("project_id")),
                compact_text(subject.object_code),
                compact_text(subject.source_feature_id),
            ]
            project_keys = [key for key in project_keys if key]
            text_evidence = []
            for key in project_keys:
                text_evidence.extend(evidence_by_project.get(key, []))
            deduped_text_evidence = {item.id: item for item in text_evidence}
            text_count = len(deduped_text_evidence)
            tile_count = rs_count_by_project.get(subject.id, 0)
            if text_count > 0 and tile_count > 0:
                continue
            target = dominant_rs_target.get(subject.id) or (next(iter(deduped_text_evidence.values())) if deduped_text_evidence else subject)
            metrics = {
                "text_evidence_count": text_count,
                "remote_sensing_tile_count": tile_count,
                "evidence_complete": False,
                "project_id": project_keys[0] if project_keys else "",
                "evidence_coverage": round(min(1.0, (text_count + tile_count) / 2.0), 4),
            }
            hit = _build_rule_hit(
                rule=rule,
                state_version_id=state_version.id,
                subject=subject,
                target=target if isinstance(target, TwmStateObject) else subject,
                metrics=metrics,
                explanation=f"{rule.title}: project {subject.object_code} lacks text evidence or remote sensing coverage",
                severity=rule.severity,
                hit_status="open",
                risk_score=self._risk_score(rule, metrics, {"review": {"policy": review_policy}}, subject, target if isinstance(target, TwmStateObject) else subject),
                geom=subject.geom,
            )
            hits.append(hit)
            evidence_items.extend(self._build_evidence_items(hit, rule, subject, target if isinstance(target, TwmStateObject) else subject, metrics, {"constraint": {"target_role": "multimodal_evidence_index"}}, review_policy))
            review_tasks.append(TwmReviewTask(rule_hit_id=hit.id, status="pending"))
        return {"hits": hits, "evidence_items": evidence_items, "review_tasks": review_tasks}

    def _match_targets(
        self,
        subject: TwmStateObject,
        targets: list[TwmStateObject],
        spatial_predicate: str,
        body: dict[str, Any],
        relations: list[TwmStateRelation],
        object_map: dict[str, TwmStateObject],
    ) -> list[TwmStateObject]:
        if spatial_predicate == "within" or spatial_predicate == "contains" or spatial_predicate == "intersects" or spatial_predicate == "distance_lt" or spatial_predicate == "overlap_area_gt":
            relation_type = body.get("constraint", {}).get("target_role")
            matched: list[TwmStateObject] = []
            for target in targets:
                if self._relation_matches(subject, target, spatial_predicate, body, relations, object_map):
                    matched.append(target)
            return matched
        if spatial_predicate == "eq":
            return [target for target in targets if self._attribute_match(subject, target, body)]
        return [target for target in targets if self._relation_matches(subject, target, "intersects", body, relations, object_map)]

    def _relation_matches(
        self,
        subject: TwmStateObject,
        target: TwmStateObject,
        spatial_predicate: str,
        body: dict[str, Any],
        relations: list[TwmStateRelation],
        object_map: dict[str, TwmStateObject],
    ) -> bool:
        if subject.id == target.id:
            return False
        target_role = compact_text(body.get("constraint", {}).get("target_role"))
        direct_relations = [
            rel for rel in relations
            if rel.subject_object_id == subject.id
            and rel.object_object_id == target.id
            and (
                not target_role
                or rel.source_target_role == target_role
                or target.canonical_role == target_role
                or target.source_role == target_role
            )
        ]
        if spatial_predicate == "within":
            return any(rel.predicate == "within" or rel.relation_type.endswith("within_admin_unit") for rel in direct_relations)
        if spatial_predicate == "contains":
            return any(rel.predicate == "contains" for rel in direct_relations)
        if spatial_predicate == "distance_lt":
            max_distance = _float(body.get("constraint", {}).get("max_distance_m"), 0.0)
            return any(_float(rel.metrics.get("distance_m"), 0.0) < max_distance for rel in direct_relations)
        if spatial_predicate == "overlap_area_gt":
            threshold = _float(body.get("constraint", {}).get("min_overlap_area_m2"), 0.0)
            return any(_float(rel.metrics.get("overlap_area_m2"), 0.0) > threshold for rel in direct_relations)
        return any(rel.predicate == "intersects" and _float(rel.metrics.get("overlap_area_m2"), 0.0) > 0 for rel in direct_relations)

    def _attribute_match(self, subject: TwmStateObject, target: TwmStateObject, body: dict[str, Any]) -> bool:
        subject_where = body.get("subject", {}).get("where") or {}
        constraint = body.get("constraint") or {}
        for field, expected in subject_where.items():
            actual = subject.attributes.get(field)
            if isinstance(expected, dict):
                if not _matches_condition(actual, expected):
                    return False
                continue
            values = expected if isinstance(expected, list) else [expected]
            if actual not in values:
                return False
        target_field = compact_text(constraint.get("target_attribute") or "")
        if target_field:
            expected = constraint.get("target_value")
            if expected is not None and target.attributes.get(target_field) != expected:
                return False
        return True

    def _build_metrics(
        self,
        subject: TwmStateObject,
        target: TwmStateObject,
        spatial_predicate: str,
        body: dict[str, Any],
        relations: list[TwmStateRelation],
    ) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        rel = next(
            (
                item for item in relations
                if item.subject_object_id == subject.id
                and item.object_object_id == target.id
            ),
            None,
        )
        if rel is not None:
            metrics.update(rel.metrics)
        metrics.setdefault("subject_area_m2", _float(subject.attributes.get("geom_area_m2") or subject.attributes.get("area_m2") or subject.attributes.get("planned_area_m2"), 0.0))
        metrics.setdefault("target_area_m2", _float(target.attributes.get("geom_area_m2") or target.attributes.get("area_m2") or target.attributes.get("zone_area_m2") or target.attributes.get("boundary_area_m2"), 0.0))
        metrics.setdefault("overlap_area_m2", _float(metrics.get("overlap_area_m2"), 0.0))
        metrics.setdefault("overlap_ratio_left", _float(metrics.get("overlap_ratio_left"), 0.0))
        metrics.setdefault("overlap_ratio_right", _float(metrics.get("overlap_ratio_right"), 0.0))
        metrics["spatial_predicate"] = spatial_predicate
        metrics["subject_object_code"] = subject.object_code
        metrics["target_object_code"] = target.object_code
        metrics["subject_role"] = subject.source_role
        metrics["target_role"] = target.source_role
        return metrics

    def _risk_score(
        self,
        rule: TwmPolicyRule,
        metrics: dict[str, Any],
        body: dict[str, Any],
        subject: TwmStateObject,
        target: TwmStateObject,
    ) -> float:
        overlap = _float(metrics.get("overlap_area_m2"), 0.0)
        ratio = max(_float(metrics.get("overlap_ratio_left"), 0.0), _float(metrics.get("overlap_ratio_right"), 0.0))
        score = 0.0
        if overlap > 0:
            score += min(0.6, overlap / max(1.0, _float(subject.attributes.get("planned_area_m2") or subject.attributes.get("geom_area_m2") or 10000.0)))
        score += min(0.3, ratio)
        if body.get("constraint", {}).get("target_role") == "planning_zone" and metrics.get("dominant_zone_type") and metrics.get("expected_zone_type"):
            if metrics.get("dominant_zone_type") != metrics.get("expected_zone_type"):
                score += 0.35
        if rule.severity == "critical":
            score += 0.35
        elif rule.severity == "high":
            score += 0.25
        elif rule.severity == "medium":
            score += 0.15
        if body.get("review", {}).get("policy") == "always_review":
            score += 0.15
        if truthy(subject.attributes.get("synthetic")) or truthy(target.attributes.get("synthetic")):
            score += 0.02
        if metrics.get("evidence_complete") is False:
            score += 0.08
        if metrics.get("inside_urban_boundary") is False and rule.rule_code == "TWM-URBAN-001":
            score += 0.2
        return min(1.0, round(score, 4))

    def _build_explanation(
        self,
        rule: TwmPolicyRule,
        subject: TwmStateObject,
        target: TwmStateObject,
        metrics: dict[str, Any],
        body: dict[str, Any],
    ) -> str:
        if rule.rule_code == "TWM-PLAN-001":
            return (
                f"{rule.title}: project_type={subject.attributes.get('project_type')} "
                f"dominant_plan_zone={target.attributes.get('plan_zone_type')} "
                f"overlap_area_m2={metrics.get('overlap_area_m2', 0.0)}"
            )
        if rule.rule_code == "TWM-EVD-001":
            return (
                f"{rule.title}: project {subject.object_code} requires text evidence "
                f"and remote sensing support; evidence coverage={metrics.get('evidence_coverage', 0.0)}"
            )
        if rule.rule_code == "TWM-GOV-001":
            return (
                f"{rule.title}: approval_status={subject.attributes.get('approval_status')} "
                f"decision_result={subject.attributes.get('decision_result')}"
            )
        if rule.rule_code == "TWM-DQ-001":
            return (
                f"{rule.title}: qa_use_for_rules={subject.qa_use_for_rules} "
                f"geometry_valid={subject.geom.is_valid if subject.geom is not None else True}"
            )
        return (
            f"{rule.title}: subject={subject.object_code} target={target.object_code} "
            f"predicate={metrics.get('spatial_predicate')} overlap_area_m2={metrics.get('overlap_area_m2', 0.0)}"
        )

    def _build_evidence_items(
        self,
        hit: TwmRuleHit,
        rule: TwmPolicyRule,
        subject: TwmStateObject,
        target: TwmStateObject,
        metrics: dict[str, Any],
        body: dict[str, Any],
        review_policy: str,
    ) -> list[TwmEvidenceItem]:
        source_feature = {
            "subject": subject.to_dict(),
            "target": target.to_dict(),
        }
        rule_clause = {
            "rule_id": rule.rule_code,
            "title": rule.title,
            "severity": rule.severity,
            "rule_body": body,
        }
        spatial_calc = {
            "predicate": metrics.get("spatial_predicate"),
            "metrics": metrics,
            "review_policy": review_policy,
        }
        semantic_mapping = {
            "subject_role": subject.source_role,
            "target_role": target.source_role,
            "canonical_roles": [subject.canonical_role, target.canonical_role],
            "qa_use_for_rules": subject.qa_use_for_rules,
        }
        model_output = None
        if hit.rule_id == "TWM-GOV-001":
            model_output = {
                "approval_status": _approval_status_value(subject),
                "decision_result": subject.attributes.get("decision_result"),
                "standard_alignment": subject.attributes.get("standard_version"),
            }
        chain = build_evidence_chain(
            rule_hit=hit,
            source_feature=source_feature,
            rule_clause=rule_clause,
            spatial_calc=spatial_calc,
            semantic_mapping=semantic_mapping,
            model_output=model_output,
            reviewer_note=None,
        )
        if hit.rule_id == "TWM-EVD-001":
            for item in chain:
                if item.evidence_type == "source_feature":
                    item.payload["evidence_coverage"] = 1.0
        return chain

    def _fallback_targets(self, role: str, objects: Iterable[TwmStateObject]) -> list[TwmStateObject]:
        if not role:
            return list(objects)
        return [obj for obj in objects if obj.object_type == role or obj.canonical_role == role or obj.source_role == role]

    def _evaluate_data_quality_rule(self, state_bundle: StateBuildResult) -> list[TwmRuleHit]:
        hits: list[TwmRuleHit] = []
        objects = list(state_bundle.objects)
        invalid_count = sum(1 for obj in objects if not obj.qa_use_for_rules)
        if invalid_count <= 0:
            return hits
        severity = "blocking" if invalid_count > 25 else "high"
        metrics = {
            "invalid_feature_count": invalid_count,
            "object_count": len(objects),
            "invalid_ratio": round(invalid_count / max(1, len(objects)), 6),
        }
        rule = TwmPolicyRule(
            rule_set_id=state_bundle.state_version.rule_set_id or "",
            rule_code="TWM-DQ-001",
            title="空间数据质量门槛",
            category="quality",
            severity=severity,
            rule_body={
                "subject": {"object_type": "all_vector_layers"},
                "constraint": {"target_role": "", "spatial_predicate": "exists"},
            },
            legal_basis={"source": "demo"},
            review_policy="always_review",
            enabled=True,
        )
        subject = objects[0]
        hit = _build_rule_hit(
            rule=rule,
            state_version_id=state_bundle.state_version.id,
            subject=subject,
            target=subject,
            metrics=metrics,
            explanation=(
                f"空间数据质量门槛: {invalid_count} features have qa_use_for_rules=false"
            ),
            severity=severity,
            hit_status="open",
            risk_score=min(1.0, invalid_count / max(1.0, len(objects))),
            geom=subject.geom,
        )
        hits.append(hit)
        return hits

    def _evaluate_approval_consistency(
        self,
        state_bundle: StateBuildResult,
        hits: list[TwmRuleHit],
    ) -> dict[str, Any]:
        objects = list(state_bundle.objects)
        state_version = state_bundle.state_version
        approval_objects = [obj for obj in objects if obj.object_type == "approval_record" or obj.source_role == "approval_records"]
        if not approval_objects:
            return {"hits": [], "evidence_items": [], "review_tasks": []}
        risk_hits = [hit for hit in hits if hit.severity in {"blocking", "critical", "high"}]
        if not risk_hits:
            return {"hits": [], "evidence_items": [], "review_tasks": []}
        results: list[TwmRuleHit] = []
        evidence_items: list[TwmEvidenceItem] = []
        review_tasks: list[TwmReviewTask] = []
        for approval in approval_objects:
            status = _approval_status_value(approval)
            if _review_status_allows_high_risk(status):
                continue
            metrics = {
                "high_or_critical_hit_count": len(risk_hits),
                "approval_status": status,
            }
            rule = TwmPolicyRule(
                rule_set_id=state_bundle.state_version.rule_set_id or "",
                rule_code="TWM-GOV-001",
                title="规则命中项目审批一致性审查",
                category="governance",
                severity="high",
                rule_body={},
                legal_basis={"source": "demo"},
                review_policy="always_review",
                enabled=True,
            )
            hit = _build_rule_hit(
                rule=rule,
                state_version_id=state_version.id,
                subject=approval,
                target=approval,
                metrics=metrics,
                explanation=(
                    f"规则命中项目审批一致性审查: high_or_critical={len(risk_hits)}, "
                    f"approval_status={status or 'unknown'}"
                ),
                severity="high",
                hit_status="open",
                risk_score=min(1.0, 0.4 + len(risk_hits) * 0.15),
                geom=approval.geom,
            )
            results.append(hit)
            evidence_items.extend(
                build_evidence_chain(
                    rule_hit=hit,
                    source_feature={"subject": approval.to_dict(), "rule_hits": [item.to_dict() for item in risk_hits]},
                    rule_clause={"rule_id": "TWM-GOV-001", "policy": "high or critical rule hits require specific approval states"},
                    spatial_calc={"high_or_critical_hit_count": len(risk_hits)},
                    semantic_mapping={"approval_status": status},
                    model_output=None,
                    reviewer_note=None,
                )
            )
            review_tasks.append(TwmReviewTask(rule_hit_id=hit.id, status="pending"))
        return {"hits": results, "evidence_items": evidence_items, "review_tasks": review_tasks}

    def _default_rules(self) -> list[TwmPolicyRule]:
        return [
            TwmPolicyRule(
                rule_set_id="default",
                rule_code="TWM-DQ-001",
                title="空间数据质量门槛",
                category="quality",
                severity="blocking",
                rule_body={
                    "version": "1.0",
                    "subject": {
                        "object_type": "all_vector_layers",
                    },
                    "constraint": {
                        "target_role": "quality_gate",
                        "spatial_predicate": "intersects",
                    },
                    "review": {"policy": "always_review"},
                },
                legal_basis={"source": "demo"},
                review_policy="always_review",
                enabled=True,
            ),
            TwmPolicyRule(
                rule_set_id="default",
                rule_code="TWM-FARM-001",
                title="永久基本农田占用审查",
                category="farmland",
                severity="high",
                rule_body={
                    "version": "1.0",
                    "subject": {
                        "object_type": "project",
                        "where": {
                            "project_type": ["construction_expansion", "non_agricultural", "development"],
                        },
                    },
                    "constraint": {
                        "target_role": "pbf",
                        "spatial_predicate": "intersects",
                        "max_overlap_area_m2": 0,
                    },
                    "hit_when": {
                        "overlap_area_m2": {"gt": 1},
                    },
                    "evidence": {
                        "require_source_feature": True,
                        "require_rule_clause": True,
                        "require_spatial_calc": True,
                    },
                    "review": {"policy": "review_required"},
                },
                legal_basis={"source": "demo"},
                review_policy="review_required",
                enabled=True,
            ),
            TwmPolicyRule(
                rule_set_id="default",
                rule_code="TWM-ECO-001",
                title="生态保护红线触碰审查",
                category="ecology",
                severity="critical",
                rule_body={
                    "version": "1.0",
                    "subject": {
                        "object_type": "project",
                        "where": {
                            "project_type": ["construction_expansion", "non_agricultural", "development"],
                        },
                    },
                    "constraint": {
                        "target_role": "eco_redline",
                        "spatial_predicate": "intersects",
                        "max_overlap_area_m2": 0,
                    },
                    "hit_when": {
                        "overlap_area_m2": {"gt": 1},
                    },
                    "review": {"policy": "always_review"},
                },
                legal_basis={"source": "demo"},
                review_policy="always_review",
                enabled=True,
            ),
            TwmPolicyRule(
                rule_set_id="default",
                rule_code="TWM-PLAN-001",
                title="用途管制分区一致性审查",
                category="planning",
                severity="medium",
                rule_body={
                    "version": "1.0",
                    "subject": {
                        "object_type": "project",
                        "where": {"project_type": {"exists": True}},
                    },
                    "constraint": {
                        "target_role": "planning_zone",
                        "spatial_predicate": "intersects",
                    },
                    "review": {"policy": "review_required"},
                },
                legal_basis={"source": "demo"},
                review_policy="review_required",
                enabled=True,
            ),
            TwmPolicyRule(
                rule_set_id="default",
                rule_code="TWM-URBAN-001",
                title="城镇开发边界内外审查",
                category="planning",
                severity="medium",
                rule_body={
                    "version": "1.0",
                    "subject": {
                        "object_type": "project",
                        "where": {"project_type": ["construction_expansion"]},
                    },
                    "constraint": {
                        "target_role": "urban_boundary",
                        "spatial_predicate": "intersects",
                    },
                    "review": {"policy": "review_required"},
                },
                legal_basis={"source": "demo"},
                review_policy="review_required",
                enabled=True,
            ),
            TwmPolicyRule(
                rule_set_id="default",
                rule_code="TWM-EVD-001",
                title="多模态证据完整性审查",
                category="evidence",
                severity="medium",
                rule_body={
                    "version": "1.0",
                    "subject": {"object_type": "project"},
                    "constraint": {
                        "target_role": "multimodal_evidence_index",
                        "spatial_predicate": "intersects",
                    },
                    "review": {"policy": "review_required"},
                },
                legal_basis={"source": "demo"},
                review_policy="review_required",
                enabled=True,
            ),
            TwmPolicyRule(
                rule_set_id="default",
                rule_code="TWM-GOV-001",
                title="规则命中项目审批一致性审查",
                category="governance",
                severity="high",
                rule_body={
                    "version": "1.0",
                    "subject": {
                        "object_type": "approval_record",
                        "where": {"approval_status": {"exists": True}},
                    },
                    "constraint": {
                        "target_role": "rule_hit",
                        "spatial_predicate": "intersects",
                    },
                    "review": {"policy": "always_review"},
                },
                legal_basis={"source": "demo"},
                review_policy="always_review",
                enabled=True,
            ),
        ]


def evaluate_rules(
    state_bundle: StateBuildResult,
    rule_set: TwmRuleSet | None = None,
    rules: Iterable[TwmPolicyRule] | None = None,
    *,
    repository=None,
    include_default_rules: bool = True,
) -> TwmRuleEvaluationResult:
    return RuleEvaluator(repository=repository).evaluate_state(
        state_bundle,
        rule_set=rule_set,
        rules=rules,
        include_default_rules=include_default_rules,
    )
