from __future__ import annotations

import json
import threading
from copy import deepcopy
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import text

from ..db_engine import get_engine
from .models import (
    StateBuildResult,
    TerritoryWorldModelAction,
    TerritoryWorldModelForecast,
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
    TwmScenario,
    TwmScenarioMetric,
    TwmScenarioPlan,
    TwmStateObject,
    TwmStateRelation,
    TwmStateVersion,
    jsonable,
    now_utc_iso,
)


_TABLES_READY = False
_TABLES_LOCK = threading.Lock()


def _json(value: Any) -> str:
    return json.dumps(jsonable(value), ensure_ascii=False, default=str)


def _dt(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value is not None else ""


def _geom_wkt(value: Any) -> str:
    return getattr(value, "wkt", "") if value is not None else ""


def _bbox_json(value: Any) -> list[Any] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return list(value)
    return jsonable(value)


class TwmRepository:
    """Persistence facade for TWM entities.

    The repository keeps an in-memory authoritative store so the service works
    without a database. When PostgreSQL is available, it also mirrors core
    entities into `twm_*` tables for auditability and later reuse.
    """

    def __init__(self, engine=None, *, persist_to_db: bool | None = None):
        self.engine = engine if engine is not None else get_engine()
        self.persist_to_db = bool(self.engine) if persist_to_db is None else bool(persist_to_db and self.engine)
        self._lock = threading.RLock()
        self._projects: dict[str, TwmProject] = {}
        self._layer_bindings: dict[str, TwmLayerBinding] = {}
        self._state_versions: dict[str, TwmStateVersion] = {}
        self._state_objects: dict[str, TwmStateObject] = {}
        self._state_relations: dict[str, TwmStateRelation] = {}
        self._rule_sets: dict[str, TwmRuleSet] = {}
        self._policy_rules: dict[str, TwmPolicyRule] = {}
        self._rule_hits: dict[str, TwmRuleHit] = {}
        self._evidence_items: dict[str, TwmEvidenceItem] = {}
        self._review_tasks: dict[str, TwmReviewTask] = {}
        self._scenarios: dict[str, TwmScenario] = {}
        self._scenario_metrics: dict[str, TwmScenarioMetric] = {}
        self._seeded_defaults = False
        self.ensure_schema()

    # ------------------------------------------------------------------
    # Schema / status
    # ------------------------------------------------------------------

    def ensure_schema(self) -> bool:
        if not self.persist_to_db or self.engine is None:
            return False

        global _TABLES_READY
        if _TABLES_READY:
            return True
        with _TABLES_LOCK:
            if _TABLES_READY:
                return True
            ddl = [
                """
                CREATE TABLE IF NOT EXISTS twm_project (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    region_code TEXT NOT NULL DEFAULT '',
                    business_scenario TEXT NOT NULL DEFAULT 'planning_supervision',
                    owner_username TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'draft',
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS twm_layer_binding (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT '',
                    canonical_role TEXT NOT NULL DEFAULT '',
                    object_type TEXT NOT NULL DEFAULT '',
                    layer_alias TEXT NOT NULL DEFAULT '',
                    source_path TEXT NOT NULL DEFAULT '',
                    semantic_product_path TEXT NOT NULL DEFAULT '',
                    asset_id INTEGER,
                    time_label TEXT NOT NULL DEFAULT '',
                    valid_from TEXT,
                    valid_to TEXT,
                    field_mapping JSONB NOT NULL DEFAULT '{}'::jsonb,
                    quality_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    synthetic BOOLEAN NOT NULL DEFAULT FALSE,
                    not_for_production BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS twm_state_version (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    state_time TIMESTAMPTZ NOT NULL DEFAULT now(),
                    label TEXT NOT NULL DEFAULT '',
                    source_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
                    rule_set_id TEXT,
                    object_count INTEGER NOT NULL DEFAULT 0,
                    relation_count INTEGER NOT NULL DEFAULT 0,
                    quality_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
                    build_status TEXT NOT NULL DEFAULT 'building',
                    build_log JSONB NOT NULL DEFAULT '{}'::jsonb,
                    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_by TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS twm_state_object (
                    id TEXT PRIMARY KEY,
                    state_version_id TEXT NOT NULL,
                    object_type TEXT NOT NULL DEFAULT '',
                    object_code TEXT NOT NULL DEFAULT '',
                    source_role TEXT NOT NULL DEFAULT '',
                    source_asset_id INTEGER,
                    source_feature_id TEXT,
                    source_path TEXT NOT NULL DEFAULT '',
                    canonical_role TEXT NOT NULL DEFAULT '',
                    attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
                    semantic_tags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
                    quality_score NUMERIC,
                    synthetic BOOLEAN NOT NULL DEFAULT FALSE,
                    not_for_production BOOLEAN NOT NULL DEFAULT FALSE,
                    qa_use_for_rules BOOLEAN NOT NULL DEFAULT TRUE,
                    geometry_crs TEXT NOT NULL DEFAULT 'EPSG:4326',
                    geom_wkt TEXT NOT NULL DEFAULT '',
                    bbox_json JSONB
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS twm_state_relation (
                    id TEXT PRIMARY KEY,
                    state_version_id TEXT NOT NULL,
                    subject_object_id TEXT NOT NULL,
                    predicate TEXT NOT NULL DEFAULT '',
                    object_object_id TEXT NOT NULL DEFAULT '',
                    relation_type TEXT NOT NULL DEFAULT '',
                    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
                    confidence NUMERIC NOT NULL DEFAULT 0,
                    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
                    geom_wkt TEXT NOT NULL DEFAULT '',
                    source_subject_role TEXT NOT NULL DEFAULT '',
                    source_target_role TEXT NOT NULL DEFAULT '',
                    synthetic BOOLEAN NOT NULL DEFAULT FALSE,
                    not_for_production BOOLEAN NOT NULL DEFAULT FALSE
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS twm_rule_set (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    version_label TEXT NOT NULL DEFAULT '',
                    source_std_version_id TEXT,
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_by TEXT NOT NULL DEFAULT '',
                    approved_by TEXT,
                    approved_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS twm_policy_rule (
                    id TEXT PRIMARY KEY,
                    rule_set_id TEXT NOT NULL,
                    rule_code TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT '',
                    severity TEXT NOT NULL DEFAULT 'medium',
                    rule_body JSONB NOT NULL DEFAULT '{}'::jsonb,
                    legal_basis JSONB NOT NULL DEFAULT '{}'::jsonb,
                    review_policy TEXT NOT NULL DEFAULT 'review_required',
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    std_derived_link_id TEXT,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS twm_rule_hit (
                    id TEXT PRIMARY KEY,
                    state_version_id TEXT NOT NULL,
                    rule_id TEXT NOT NULL DEFAULT '',
                    subject_object_id TEXT NOT NULL DEFAULT '',
                    target_object_id TEXT,
                    hit_status TEXT NOT NULL DEFAULT 'open',
                    severity TEXT NOT NULL DEFAULT 'medium',
                    risk_score NUMERIC NOT NULL DEFAULT 0,
                    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
                    explanation TEXT NOT NULL DEFAULT '',
                    geom_wkt TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    reviewed_at TIMESTAMPTZ,
                    review_task_id TEXT
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS twm_evidence_item (
                    id TEXT PRIMARY KEY,
                    rule_hit_id TEXT NOT NULL DEFAULT '',
                    evidence_type TEXT NOT NULL DEFAULT '',
                    source_system TEXT NOT NULL DEFAULT 'twm',
                    source_ref TEXT NOT NULL DEFAULT '',
                    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                    checksum TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS twm_review_task (
                    id TEXT PRIMARY KEY,
                    rule_hit_id TEXT NOT NULL DEFAULT '',
                    assignee TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    decision TEXT NOT NULL DEFAULT '',
                    comment TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS twm_scenario (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL DEFAULT '',
                    base_state_version_id TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL DEFAULT '',
                    scenario_type TEXT NOT NULL DEFAULT 'baseline',
                    input_changes JSONB NOT NULL DEFAULT '{}'::jsonb,
                    source_model TEXT,
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS twm_scenario_metric (
                    id TEXT PRIMARY KEY,
                    scenario_id TEXT NOT NULL DEFAULT '',
                    metric_code TEXT NOT NULL DEFAULT '',
                    metric_name TEXT NOT NULL DEFAULT '',
                    value NUMERIC NOT NULL DEFAULT 0,
                    unit TEXT NOT NULL DEFAULT '',
                    benchmark_value NUMERIC,
                    direction TEXT NOT NULL DEFAULT 'lower_better',
                    explanation TEXT NOT NULL DEFAULT ''
                )
                """,
            ]
            with self.engine.connect() as conn:
                for statement in ddl:
                    conn.execute(text(statement))
                conn.commit()
            _TABLES_READY = True
        return True

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "backend": "db+memory" if self.persist_to_db and self.engine is not None else "memory",
                "project_count": len(self._projects),
                "layer_binding_count": len(self._layer_bindings),
                "state_version_count": len(self._state_versions),
                "state_object_count": len(self._state_objects),
                "state_relation_count": len(self._state_relations),
                "rule_set_count": len(self._rule_sets),
                "policy_rule_count": len(self._policy_rules),
                "rule_hit_count": len(self._rule_hits),
                "evidence_item_count": len(self._evidence_items),
                "review_task_count": len(self._review_tasks),
                "scenario_count": len(self._scenarios),
                "scenario_metric_count": len(self._scenario_metrics),
            }

    # ------------------------------------------------------------------
    # Projects / bindings
    # ------------------------------------------------------------------

    def save_project(self, project: TwmProject) -> TwmProject:
        with self._lock:
            stored = deepcopy(project)
            self._projects[stored.id] = stored
            self._persist_project(stored)
            return deepcopy(stored)

    def get_project(self, project_id: str) -> TwmProject | None:
        with self._lock:
            project = self._projects.get(str(project_id))
            return deepcopy(project) if project else None

    def list_projects(self, *, owner_username: str | None = None) -> list[TwmProject]:
        with self._lock:
            projects = list(self._projects.values())
            if owner_username:
                projects = [item for item in projects if item.owner_username == owner_username]
            return [deepcopy(item) for item in sorted(projects, key=lambda item: item.created_at, reverse=True)]

    def save_layer_binding(self, binding: TwmLayerBinding) -> TwmLayerBinding:
        with self._lock:
            stored = deepcopy(binding)
            self._layer_bindings[stored.id] = stored
            self._persist_layer_binding(stored)
            return deepcopy(stored)

    def list_layer_bindings(self, project_id: str | None = None) -> list[TwmLayerBinding]:
        with self._lock:
            rows = list(self._layer_bindings.values())
            if project_id:
                rows = [item for item in rows if item.project_id == project_id]
            return [deepcopy(item) for item in sorted(rows, key=lambda item: item.created_at)]

    # ------------------------------------------------------------------
    # State versions / objects / relations
    # ------------------------------------------------------------------

    def save_state_version(self, state_version: TwmStateVersion) -> TwmStateVersion:
        with self._lock:
            stored = deepcopy(state_version)
            self._state_versions[stored.id] = stored
            self._persist_state_version(stored)
            return deepcopy(stored)

    def get_state_version(self, state_version_id: str) -> TwmStateVersion | None:
        with self._lock:
            state = self._state_versions.get(str(state_version_id))
            return deepcopy(state) if state else None

    def list_state_versions(self, project_id: str | None = None) -> list[TwmStateVersion]:
        with self._lock:
            rows = list(self._state_versions.values())
            if project_id:
                rows = [item for item in rows if item.project_id == project_id]
            return [deepcopy(item) for item in sorted(rows, key=lambda item: item.created_at, reverse=True)]

    def save_state_objects(self, objects: Iterable[TwmStateObject]) -> list[TwmStateObject]:
        stored_rows: list[TwmStateObject] = []
        with self._lock:
            for obj in objects:
                stored = deepcopy(obj)
                self._state_objects[stored.id] = stored
                self._persist_state_object(stored)
                stored_rows.append(deepcopy(stored))
        return stored_rows

    def list_state_objects(self, state_version_id: str | None = None) -> list[TwmStateObject]:
        with self._lock:
            rows = list(self._state_objects.values())
            if state_version_id:
                rows = [item for item in rows if item.state_version_id == state_version_id]
            return [deepcopy(item) for item in rows]

    def save_state_relations(self, relations: Iterable[TwmStateRelation]) -> list[TwmStateRelation]:
        stored_rows: list[TwmStateRelation] = []
        with self._lock:
            for rel in relations:
                stored = deepcopy(rel)
                self._state_relations[stored.id] = stored
                self._persist_state_relation(stored)
                stored_rows.append(deepcopy(stored))
        return stored_rows

    def list_state_relations(self, state_version_id: str | None = None) -> list[TwmStateRelation]:
        with self._lock:
            rows = list(self._state_relations.values())
            if state_version_id:
                rows = [item for item in rows if item.state_version_id == state_version_id]
            return [deepcopy(item) for item in rows]

    def get_state_bundle(self, state_version_id: str) -> dict[str, Any] | None:
        state = self.get_state_version(state_version_id)
        if state is None:
            return None
        return {
            "state_version": state,
            "objects": self.list_state_objects(state_version_id),
            "relations": self.list_state_relations(state_version_id),
            "hits": self.list_rule_hits(state_version_id=state_version_id),
            "evidence_items": self.list_evidence_items(state_version_id=state_version_id),
            "review_tasks": self.list_review_tasks(state_version_id=state_version_id),
        }

    def save_state_bundle(self, result: StateBuildResult) -> StateBuildResult:
        self.save_project(result.project)
        self.save_state_version(result.state_version)
        self.save_state_objects(result.objects)
        self.save_state_relations(result.relations)
        return deepcopy(result)

    # ------------------------------------------------------------------
    # Rule sets / policy rules
    # ------------------------------------------------------------------

    def save_rule_set(self, rule_set: TwmRuleSet) -> TwmRuleSet:
        with self._lock:
            stored = deepcopy(rule_set)
            self._rule_sets[stored.id] = stored
            self._persist_rule_set(stored)
            return deepcopy(stored)

    def get_rule_set(self, rule_set_id: str) -> TwmRuleSet | None:
        with self._lock:
            row = self._rule_sets.get(str(rule_set_id))
            return deepcopy(row) if row else None

    def list_rule_sets(self) -> list[TwmRuleSet]:
        with self._lock:
            return [deepcopy(item) for item in sorted(self._rule_sets.values(), key=lambda item: item.created_at, reverse=True)]

    def save_policy_rule(self, rule: TwmPolicyRule) -> TwmPolicyRule:
        with self._lock:
            stored = deepcopy(rule)
            self._policy_rules[stored.id] = stored
            self._persist_policy_rule(stored)
            return deepcopy(stored)

    def get_policy_rule(self, rule_id: str) -> TwmPolicyRule | None:
        with self._lock:
            row = self._policy_rules.get(str(rule_id))
            return deepcopy(row) if row else None

    def list_policy_rules(self, rule_set_id: str | None = None, *, enabled: bool | None = None) -> list[TwmPolicyRule]:
        with self._lock:
            rows = list(self._policy_rules.values())
            if rule_set_id:
                rows = [item for item in rows if item.rule_set_id == rule_set_id]
            if enabled is not None:
                rows = [item for item in rows if bool(item.enabled) is enabled]
            return [deepcopy(item) for item in sorted(rows, key=lambda item: item.created_at)]

    def ensure_default_rule_set(self, rule_set: TwmRuleSet, rules: Iterable[TwmPolicyRule]) -> TwmRuleSet:
        with self._lock:
            saved_rule_set = self.save_rule_set(rule_set)
            for rule in rules:
                stored_rule = deepcopy(rule)
                stored_rule.rule_set_id = saved_rule_set.id
                self.save_policy_rule(stored_rule)
            self._seeded_defaults = True
            return deepcopy(saved_rule_set)

    # ------------------------------------------------------------------
    # Rule hits / evidence / review
    # ------------------------------------------------------------------

    def save_rule_hit(self, hit: TwmRuleHit) -> TwmRuleHit:
        with self._lock:
            stored = deepcopy(hit)
            self._rule_hits[stored.id] = stored
            self._persist_rule_hit(stored)
            return deepcopy(stored)

    def save_rule_hits(self, hits: Iterable[TwmRuleHit]) -> list[TwmRuleHit]:
        return [self.save_rule_hit(hit) for hit in hits]

    def get_rule_hit(self, hit_id: str) -> TwmRuleHit | None:
        with self._lock:
            row = self._rule_hits.get(str(hit_id))
            return deepcopy(row) if row else None

    def list_rule_hits(
        self,
        *,
        state_version_id: str | None = None,
        rule_id: str | None = None,
        severity: str | None = None,
        status: str | None = None,
    ) -> list[TwmRuleHit]:
        with self._lock:
            rows = list(self._rule_hits.values())
            if state_version_id:
                rows = [item for item in rows if item.state_version_id == state_version_id]
            if rule_id:
                rows = [item for item in rows if item.rule_id == rule_id]
            if severity:
                rows = [item for item in rows if item.severity == severity]
            if status:
                rows = [item for item in rows if item.hit_status == status]
            return [deepcopy(item) for item in sorted(rows, key=lambda item: item.created_at, reverse=True)]

    def save_evidence_item(self, item: TwmEvidenceItem) -> TwmEvidenceItem:
        with self._lock:
            stored = deepcopy(item)
            self._evidence_items[stored.id] = stored
            self._persist_evidence_item(stored)
            return deepcopy(stored)

    def save_evidence_items(self, items: Iterable[TwmEvidenceItem]) -> list[TwmEvidenceItem]:
        return [self.save_evidence_item(item) for item in items]

    def list_evidence_items(
        self,
        *,
        state_version_id: str | None = None,
        rule_hit_id: str | None = None,
        evidence_type: str | None = None,
    ) -> list[TwmEvidenceItem]:
        with self._lock:
            rows = list(self._evidence_items.values())
            if rule_hit_id:
                rows = [item for item in rows if item.rule_hit_id == rule_hit_id]
            elif state_version_id:
                hit_ids = {hit.id for hit in self._rule_hits.values() if hit.state_version_id == state_version_id}
                rows = [item for item in rows if item.rule_hit_id in hit_ids]
            if evidence_type:
                rows = [item for item in rows if item.evidence_type == evidence_type]
            return [deepcopy(item) for item in sorted(rows, key=lambda item: item.created_at, reverse=True)]

    def save_review_task(self, task: TwmReviewTask) -> TwmReviewTask:
        with self._lock:
            stored = deepcopy(task)
            self._review_tasks[stored.id] = stored
            self._persist_review_task(stored)
            return deepcopy(stored)

    def save_review_tasks(self, tasks: Iterable[TwmReviewTask]) -> list[TwmReviewTask]:
        return [self.save_review_task(task) for task in tasks]

    def get_review_task(self, task_id: str) -> TwmReviewTask | None:
        with self._lock:
            row = self._review_tasks.get(str(task_id))
            return deepcopy(row) if row else None

    def list_review_tasks(
        self,
        *,
        state_version_id: str | None = None,
        rule_hit_id: str | None = None,
        status: str | None = None,
    ) -> list[TwmReviewTask]:
        with self._lock:
            rows = list(self._review_tasks.values())
            if rule_hit_id:
                rows = [item for item in rows if item.rule_hit_id == rule_hit_id]
            elif state_version_id:
                hit_ids = {hit.id for hit in self._rule_hits.values() if hit.state_version_id == state_version_id}
                rows = [item for item in rows if item.rule_hit_id in hit_ids]
            if status:
                rows = [item for item in rows if item.status == status]
            return [deepcopy(item) for item in sorted(rows, key=lambda item: item.created_at, reverse=True)]

    def review_rule_hit(
        self,
        hit_id: str,
        *,
        decision: str,
        comment: str = "",
        assignee: str | None = None,
        status: str | None = None,
    ) -> tuple[TwmRuleHit | None, TwmReviewTask | None]:
        with self._lock:
            hit = self._rule_hits.get(str(hit_id))
            if hit is None:
                return None, None
            task = None
            for candidate in self._review_tasks.values():
                if candidate.rule_hit_id == hit.id:
                    task = candidate
                    break
            if task is None:
                task = TwmReviewTask(rule_hit_id=hit.id, assignee=assignee, status="pending")
            task.decision = str(decision or "")
            task.comment = str(comment or "")
            task.assignee = assignee or task.assignee
            task.status = status or ("confirmed" if decision in {"confirmed", "approve", "approved"} else "dismissed" if decision in {"dismissed", "reject", "rejected"} else task.status)
            task.updated_at = now_utc_iso()
            self._review_tasks[task.id] = deepcopy(task)
            self._persist_review_task(task)

            hit.hit_status = "reviewed_confirmed" if task.status == "confirmed" else "reviewed_dismissed" if task.status == "dismissed" else hit.hit_status
            hit.review_task_id = task.id
            hit.reviewed_at = now_utc_iso()
            self._rule_hits[hit.id] = deepcopy(hit)
            self._persist_rule_hit(hit)
            return deepcopy(hit), deepcopy(task)

    # ------------------------------------------------------------------
    # Scenarios / metrics
    # ------------------------------------------------------------------

    def save_scenario(self, scenario: TwmScenario) -> TwmScenario:
        with self._lock:
            stored = deepcopy(scenario)
            self._scenarios[stored.id] = stored
            self._persist_scenario(stored)
            return deepcopy(stored)

    def save_scenarios(self, scenarios: Iterable[TwmScenario]) -> list[TwmScenario]:
        return [self.save_scenario(scenario) for scenario in scenarios]

    def get_scenario(self, scenario_id: str) -> TwmScenario | None:
        with self._lock:
            row = self._scenarios.get(str(scenario_id))
            return deepcopy(row) if row else None

    def list_scenarios(self, project_id: str | None = None) -> list[TwmScenario]:
        with self._lock:
            rows = list(self._scenarios.values())
            if project_id:
                rows = [item for item in rows if item.project_id == project_id]
            return [deepcopy(item) for item in sorted(rows, key=lambda item: item.created_at, reverse=True)]

    def save_scenario_metric(self, metric: TwmScenarioMetric) -> TwmScenarioMetric:
        with self._lock:
            stored = deepcopy(metric)
            self._scenario_metrics[stored.id] = stored
            self._persist_scenario_metric(stored)
            return deepcopy(stored)

    def save_scenario_metrics(self, metrics: Iterable[TwmScenarioMetric]) -> list[TwmScenarioMetric]:
        return [self.save_scenario_metric(metric) for metric in metrics]

    def list_scenario_metrics(self, scenario_id: str | None = None) -> list[TwmScenarioMetric]:
        with self._lock:
            rows = list(self._scenario_metrics.values())
            if scenario_id:
                rows = [item for item in rows if item.scenario_id == scenario_id]
            return [deepcopy(item) for item in sorted(rows, key=lambda item: item.metric_code)]

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _persist(self, sql: str, payload: dict[str, Any]) -> None:
        if not self.persist_to_db or self.engine is None:
            return
        with self.engine.connect() as conn:
            conn.execute(text(sql), payload)
            conn.commit()

    def _persist_project(self, project: TwmProject) -> None:
        self._persist(
            """
            INSERT INTO twm_project
                (id, name, description, region_code, business_scenario,
                 owner_username, status, metadata, created_at, updated_at)
            VALUES
                (:id, :name, :description, :region_code, :business_scenario,
                 :owner_username, :status, CAST(:metadata AS JSONB),
                 :created_at, :updated_at)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                region_code = EXCLUDED.region_code,
                business_scenario = EXCLUDED.business_scenario,
                owner_username = EXCLUDED.owner_username,
                status = EXCLUDED.status,
                metadata = EXCLUDED.metadata,
                updated_at = EXCLUDED.updated_at
            """,
            {
                "id": project.id,
                "name": project.name,
                "description": project.description,
                "region_code": project.region_code,
                "business_scenario": project.business_scenario,
                "owner_username": project.owner_username,
                "status": project.status,
                "metadata": _json(project.metadata),
                "created_at": project.created_at,
                "updated_at": project.updated_at,
            },
        )

    def _persist_layer_binding(self, binding: TwmLayerBinding) -> None:
        self._persist(
            """
            INSERT INTO twm_layer_binding
                (id, project_id, role, canonical_role, object_type, layer_alias,
                 source_path, semantic_product_path, asset_id, time_label,
                 valid_from, valid_to, field_mapping, quality_snapshot, metadata,
                 synthetic, not_for_production, created_at)
            VALUES
                (:id, :project_id, :role, :canonical_role, :object_type, :layer_alias,
                 :source_path, :semantic_product_path, :asset_id, :time_label,
                 :valid_from, :valid_to, CAST(:field_mapping AS JSONB),
                 CAST(:quality_snapshot AS JSONB), CAST(:metadata AS JSONB),
                 :synthetic, :not_for_production, :created_at)
            ON CONFLICT (id) DO UPDATE SET
                project_id = EXCLUDED.project_id,
                role = EXCLUDED.role,
                canonical_role = EXCLUDED.canonical_role,
                object_type = EXCLUDED.object_type,
                layer_alias = EXCLUDED.layer_alias,
                source_path = EXCLUDED.source_path,
                semantic_product_path = EXCLUDED.semantic_product_path,
                asset_id = EXCLUDED.asset_id,
                time_label = EXCLUDED.time_label,
                valid_from = EXCLUDED.valid_from,
                valid_to = EXCLUDED.valid_to,
                field_mapping = EXCLUDED.field_mapping,
                quality_snapshot = EXCLUDED.quality_snapshot,
                metadata = EXCLUDED.metadata,
                synthetic = EXCLUDED.synthetic,
                not_for_production = EXCLUDED.not_for_production
            """,
            {
                "id": binding.id,
                "project_id": binding.project_id,
                "role": binding.role,
                "canonical_role": binding.canonical_role,
                "object_type": binding.object_type,
                "layer_alias": binding.layer_alias,
                "source_path": binding.source_path,
                "semantic_product_path": binding.semantic_product_path,
                "asset_id": binding.asset_id,
                "time_label": binding.time_label,
                "valid_from": binding.valid_from,
                "valid_to": binding.valid_to,
                "field_mapping": _json(binding.field_mapping),
                "quality_snapshot": _json(binding.quality_snapshot),
                "metadata": _json(binding.metadata),
                "synthetic": binding.synthetic,
                "not_for_production": binding.not_for_production,
                "created_at": binding.created_at,
            },
        )

    def _persist_state_version(self, state_version: TwmStateVersion) -> None:
        self._persist(
            """
            INSERT INTO twm_state_version
                (id, project_id, state_time, label, source_manifest, rule_set_id,
                 object_count, relation_count, quality_summary, build_status,
                 build_log, summary, created_by, created_at)
            VALUES
                (:id, :project_id, :state_time, :label, CAST(:source_manifest AS JSONB),
                 :rule_set_id, :object_count, :relation_count,
                 CAST(:quality_summary AS JSONB), :build_status,
                 CAST(:build_log AS JSONB), CAST(:summary AS JSONB),
                 :created_by, :created_at)
            ON CONFLICT (id) DO UPDATE SET
                project_id = EXCLUDED.project_id,
                state_time = EXCLUDED.state_time,
                label = EXCLUDED.label,
                source_manifest = EXCLUDED.source_manifest,
                rule_set_id = EXCLUDED.rule_set_id,
                object_count = EXCLUDED.object_count,
                relation_count = EXCLUDED.relation_count,
                quality_summary = EXCLUDED.quality_summary,
                build_status = EXCLUDED.build_status,
                build_log = EXCLUDED.build_log,
                summary = EXCLUDED.summary,
                created_by = EXCLUDED.created_by
            """,
            {
                "id": state_version.id,
                "project_id": state_version.project_id,
                "state_time": state_version.state_time,
                "label": state_version.label,
                "source_manifest": _json(state_version.source_manifest),
                "rule_set_id": state_version.rule_set_id,
                "object_count": state_version.object_count,
                "relation_count": state_version.relation_count,
                "quality_summary": _json(state_version.quality_summary),
                "build_status": state_version.build_status,
                "build_log": _json(state_version.build_log),
                "summary": _json(state_version.summary),
                "created_by": state_version.created_by,
                "created_at": state_version.created_at,
            },
        )

    def _persist_state_object(self, obj: TwmStateObject) -> None:
        self._persist(
            """
            INSERT INTO twm_state_object
                (id, state_version_id, object_type, object_code, source_role,
                 source_asset_id, source_feature_id, source_path, canonical_role,
                 attributes, semantic_tags, quality_score, synthetic,
                 not_for_production, qa_use_for_rules, geometry_crs, geom_wkt,
                 bbox_json)
            VALUES
                (:id, :state_version_id, :object_type, :object_code, :source_role,
                 :source_asset_id, :source_feature_id, :source_path, :canonical_role,
                 CAST(:attributes AS JSONB), :semantic_tags, :quality_score,
                 :synthetic, :not_for_production, :qa_use_for_rules,
                 :geometry_crs, :geom_wkt, :bbox_json)
            ON CONFLICT (id) DO UPDATE SET
                state_version_id = EXCLUDED.state_version_id,
                object_type = EXCLUDED.object_type,
                object_code = EXCLUDED.object_code,
                source_role = EXCLUDED.source_role,
                source_asset_id = EXCLUDED.source_asset_id,
                source_feature_id = EXCLUDED.source_feature_id,
                source_path = EXCLUDED.source_path,
                canonical_role = EXCLUDED.canonical_role,
                attributes = EXCLUDED.attributes,
                semantic_tags = EXCLUDED.semantic_tags,
                quality_score = EXCLUDED.quality_score,
                synthetic = EXCLUDED.synthetic,
                not_for_production = EXCLUDED.not_for_production,
                qa_use_for_rules = EXCLUDED.qa_use_for_rules,
                geometry_crs = EXCLUDED.geometry_crs,
                geom_wkt = EXCLUDED.geom_wkt,
                bbox_json = EXCLUDED.bbox_json
            """,
            {
                "id": obj.id,
                "state_version_id": obj.state_version_id,
                "object_type": obj.object_type,
                "object_code": obj.object_code,
                "source_role": obj.source_role,
                "source_asset_id": obj.source_asset_id,
                "source_feature_id": obj.source_feature_id,
                "source_path": obj.source_path,
                "canonical_role": obj.canonical_role,
                "attributes": _json(obj.attributes),
                "semantic_tags": list(obj.semantic_tags),
                "quality_score": obj.quality_score,
                "synthetic": obj.synthetic,
                "not_for_production": obj.not_for_production,
                "qa_use_for_rules": obj.qa_use_for_rules,
                "geometry_crs": obj.geometry_crs,
                "geom_wkt": _geom_wkt(obj.geom),
                "bbox_json": _bbox_json(obj.bbox),
            },
        )

    def _persist_state_relation(self, rel: TwmStateRelation) -> None:
        self._persist(
            """
            INSERT INTO twm_state_relation
                (id, state_version_id, subject_object_id, predicate,
                 object_object_id, relation_type, metrics, confidence, evidence,
                 geom_wkt, source_subject_role, source_target_role, synthetic,
                 not_for_production)
            VALUES
                (:id, :state_version_id, :subject_object_id, :predicate,
                 :object_object_id, :relation_type, CAST(:metrics AS JSONB),
                 :confidence, CAST(:evidence AS JSONB), :geom_wkt,
                 :source_subject_role, :source_target_role, :synthetic,
                 :not_for_production)
            ON CONFLICT (id) DO UPDATE SET
                state_version_id = EXCLUDED.state_version_id,
                subject_object_id = EXCLUDED.subject_object_id,
                predicate = EXCLUDED.predicate,
                object_object_id = EXCLUDED.object_object_id,
                relation_type = EXCLUDED.relation_type,
                metrics = EXCLUDED.metrics,
                confidence = EXCLUDED.confidence,
                evidence = EXCLUDED.evidence,
                geom_wkt = EXCLUDED.geom_wkt,
                source_subject_role = EXCLUDED.source_subject_role,
                source_target_role = EXCLUDED.source_target_role,
                synthetic = EXCLUDED.synthetic,
                not_for_production = EXCLUDED.not_for_production
            """,
            {
                "id": rel.id,
                "state_version_id": rel.state_version_id,
                "subject_object_id": rel.subject_object_id,
                "predicate": rel.predicate,
                "object_object_id": rel.object_object_id,
                "relation_type": rel.relation_type,
                "metrics": _json(rel.metrics),
                "confidence": rel.confidence,
                "evidence": _json(rel.evidence),
                "geom_wkt": _geom_wkt(rel.geom),
                "source_subject_role": rel.source_subject_role,
                "source_target_role": rel.source_target_role,
                "synthetic": rel.synthetic,
                "not_for_production": rel.not_for_production,
            },
        )

    def _persist_rule_set(self, rule_set: TwmRuleSet) -> None:
        self._persist(
            """
            INSERT INTO twm_rule_set
                (id, name, version_label, source_std_version_id, status,
                 created_by, approved_by, approved_at, created_at)
            VALUES
                (:id, :name, :version_label, :source_std_version_id, :status,
                 :created_by, :approved_by, :approved_at, :created_at)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                version_label = EXCLUDED.version_label,
                source_std_version_id = EXCLUDED.source_std_version_id,
                status = EXCLUDED.status,
                created_by = EXCLUDED.created_by,
                approved_by = EXCLUDED.approved_by,
                approved_at = EXCLUDED.approved_at
            """,
            {
                "id": rule_set.id,
                "name": rule_set.name,
                "version_label": rule_set.version_label,
                "source_std_version_id": rule_set.source_std_version_id,
                "status": rule_set.status,
                "created_by": rule_set.created_by,
                "approved_by": rule_set.approved_by,
                "approved_at": rule_set.approved_at,
                "created_at": rule_set.created_at,
            },
        )

    def _persist_policy_rule(self, rule: TwmPolicyRule) -> None:
        self._persist(
            """
            INSERT INTO twm_policy_rule
                (id, rule_set_id, rule_code, title, category, severity,
                 rule_body, legal_basis, review_policy, enabled,
                 std_derived_link_id, metadata, created_at, updated_at)
            VALUES
                (:id, :rule_set_id, :rule_code, :title, :category, :severity,
                 CAST(:rule_body AS JSONB), CAST(:legal_basis AS JSONB),
                 :review_policy, :enabled, :std_derived_link_id,
                 CAST(:metadata AS JSONB), :created_at, :updated_at)
            ON CONFLICT (id) DO UPDATE SET
                rule_set_id = EXCLUDED.rule_set_id,
                rule_code = EXCLUDED.rule_code,
                title = EXCLUDED.title,
                category = EXCLUDED.category,
                severity = EXCLUDED.severity,
                rule_body = EXCLUDED.rule_body,
                legal_basis = EXCLUDED.legal_basis,
                review_policy = EXCLUDED.review_policy,
                enabled = EXCLUDED.enabled,
                std_derived_link_id = EXCLUDED.std_derived_link_id,
                metadata = EXCLUDED.metadata,
                updated_at = EXCLUDED.updated_at
            """,
            {
                "id": rule.id,
                "rule_set_id": rule.rule_set_id,
                "rule_code": rule.rule_code,
                "title": rule.title,
                "category": rule.category,
                "severity": rule.severity,
                "rule_body": _json(rule.rule_body),
                "legal_basis": _json(rule.legal_basis),
                "review_policy": rule.review_policy,
                "enabled": rule.enabled,
                "std_derived_link_id": rule.std_derived_link_id,
                "metadata": _json(rule.metadata),
                "created_at": rule.created_at,
                "updated_at": rule.updated_at,
            },
        )

    def _persist_rule_hit(self, hit: TwmRuleHit) -> None:
        self._persist(
            """
            INSERT INTO twm_rule_hit
                (id, state_version_id, rule_id, subject_object_id,
                 target_object_id, hit_status, severity, risk_score, metrics,
                 explanation, geom_wkt, created_at, reviewed_at, review_task_id)
            VALUES
                (:id, :state_version_id, :rule_id, :subject_object_id,
                 :target_object_id, :hit_status, :severity, :risk_score,
                 CAST(:metrics AS JSONB), :explanation, :geom_wkt,
                 :created_at, :reviewed_at, :review_task_id)
            ON CONFLICT (id) DO UPDATE SET
                state_version_id = EXCLUDED.state_version_id,
                rule_id = EXCLUDED.rule_id,
                subject_object_id = EXCLUDED.subject_object_id,
                target_object_id = EXCLUDED.target_object_id,
                hit_status = EXCLUDED.hit_status,
                severity = EXCLUDED.severity,
                risk_score = EXCLUDED.risk_score,
                metrics = EXCLUDED.metrics,
                explanation = EXCLUDED.explanation,
                geom_wkt = EXCLUDED.geom_wkt,
                reviewed_at = EXCLUDED.reviewed_at,
                review_task_id = EXCLUDED.review_task_id
            """,
            {
                "id": hit.id,
                "state_version_id": hit.state_version_id,
                "rule_id": hit.rule_id,
                "subject_object_id": hit.subject_object_id,
                "target_object_id": hit.target_object_id,
                "hit_status": hit.hit_status,
                "severity": hit.severity,
                "risk_score": hit.risk_score,
                "metrics": _json(hit.metrics),
                "explanation": hit.explanation,
                "geom_wkt": _geom_wkt(hit.geom),
                "created_at": hit.created_at,
                "reviewed_at": hit.reviewed_at,
                "review_task_id": hit.review_task_id,
            },
        )

    def _persist_evidence_item(self, item: TwmEvidenceItem) -> None:
        self._persist(
            """
            INSERT INTO twm_evidence_item
                (id, rule_hit_id, evidence_type, source_system, source_ref,
                 payload, checksum, created_at)
            VALUES
                (:id, :rule_hit_id, :evidence_type, :source_system, :source_ref,
                 CAST(:payload AS JSONB), :checksum, :created_at)
            ON CONFLICT (id) DO UPDATE SET
                rule_hit_id = EXCLUDED.rule_hit_id,
                evidence_type = EXCLUDED.evidence_type,
                source_system = EXCLUDED.source_system,
                source_ref = EXCLUDED.source_ref,
                payload = EXCLUDED.payload,
                checksum = EXCLUDED.checksum
            """,
            {
                "id": item.id,
                "rule_hit_id": item.rule_hit_id,
                "evidence_type": item.evidence_type,
                "source_system": item.source_system,
                "source_ref": item.source_ref,
                "payload": _json(item.payload),
                "checksum": item.checksum,
                "created_at": item.created_at,
            },
        )

    def _persist_review_task(self, task: TwmReviewTask) -> None:
        self._persist(
            """
            INSERT INTO twm_review_task
                (id, rule_hit_id, assignee, status, decision, comment,
                 created_at, updated_at)
            VALUES
                (:id, :rule_hit_id, :assignee, :status, :decision, :comment,
                 :created_at, :updated_at)
            ON CONFLICT (id) DO UPDATE SET
                rule_hit_id = EXCLUDED.rule_hit_id,
                assignee = EXCLUDED.assignee,
                status = EXCLUDED.status,
                decision = EXCLUDED.decision,
                comment = EXCLUDED.comment,
                updated_at = EXCLUDED.updated_at
            """,
            {
                "id": task.id,
                "rule_hit_id": task.rule_hit_id,
                "assignee": task.assignee,
                "status": task.status,
                "decision": task.decision,
                "comment": task.comment,
                "created_at": task.created_at,
                "updated_at": task.updated_at,
            },
        )

    def _persist_scenario(self, scenario: TwmScenario) -> None:
        self._persist(
            """
            INSERT INTO twm_scenario
                (id, project_id, base_state_version_id, name, scenario_type,
                 input_changes, source_model, status, created_at)
            VALUES
                (:id, :project_id, :base_state_version_id, :name,
                 :scenario_type, CAST(:input_changes AS JSONB), :source_model,
                 :status, :created_at)
            ON CONFLICT (id) DO UPDATE SET
                project_id = EXCLUDED.project_id,
                base_state_version_id = EXCLUDED.base_state_version_id,
                name = EXCLUDED.name,
                scenario_type = EXCLUDED.scenario_type,
                input_changes = EXCLUDED.input_changes,
                source_model = EXCLUDED.source_model,
                status = EXCLUDED.status
            """,
            {
                "id": scenario.id,
                "project_id": scenario.project_id,
                "base_state_version_id": scenario.base_state_version_id,
                "name": scenario.name,
                "scenario_type": scenario.scenario_type,
                "input_changes": _json(scenario.input_changes),
                "source_model": scenario.source_model,
                "status": scenario.status,
                "created_at": scenario.created_at,
            },
        )

    def _persist_scenario_metric(self, metric: TwmScenarioMetric) -> None:
        self._persist(
            """
            INSERT INTO twm_scenario_metric
                (id, scenario_id, metric_code, metric_name, value, unit,
                 benchmark_value, direction, explanation)
            VALUES
                (:id, :scenario_id, :metric_code, :metric_name, :value, :unit,
                 :benchmark_value, :direction, :explanation)
            ON CONFLICT (id) DO UPDATE SET
                scenario_id = EXCLUDED.scenario_id,
                metric_code = EXCLUDED.metric_code,
                metric_name = EXCLUDED.metric_name,
                value = EXCLUDED.value,
                unit = EXCLUDED.unit,
                benchmark_value = EXCLUDED.benchmark_value,
                direction = EXCLUDED.direction,
                explanation = EXCLUDED.explanation
            """,
            {
                "id": metric.id,
                "scenario_id": metric.scenario_id,
                "metric_code": metric.metric_code,
                "metric_name": metric.metric_name,
                "value": metric.value,
                "unit": metric.unit,
                "benchmark_value": metric.benchmark_value,
                "direction": metric.direction,
                "explanation": metric.explanation,
            },
        )


_INSTANCE: TwmRepository | None = None
_INSTANCE_LOCK = threading.Lock()


def get_twm_repository() -> TwmRepository:
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = TwmRepository()
    return _INSTANCE


def reset_twm_repository() -> None:
    global _INSTANCE
    with _INSTANCE_LOCK:
        _INSTANCE = None
