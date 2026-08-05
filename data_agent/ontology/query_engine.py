"""Governed ontology analysis over RDF, authority metadata, and GIS scenarios."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from typing import Any

from .okf_bundle import okf_reference
from .package_reader import DOMAIN_MODEL_KINDS
from .query_contracts import OntologyQueryPlan, OntologyQueryType
from .sparql_adapter import SparqlProjectionUnavailable, SparqlReadAdapter


class OntologyQueryEngine:
    """Execute closed query plans and emit agent/UI-ready evidence."""

    MAX_PATH_VISITS = 120

    def __init__(self, service):
        self.service = service
        self.sparql = SparqlReadAdapter()

    def execute(self, plan: OntologyQueryPlan | dict[str, Any]) -> dict[str, Any]:
        if not isinstance(plan, OntologyQueryPlan):
            plan = OntologyQueryPlan.model_validate(plan)

        if plan.query_type == OntologyQueryType.SCHEMA_MAPPING:
            payload = self._schema_mapping(plan)
        elif plan.query_type == OntologyQueryType.DEMO_SCENARIO_ANALYSIS:
            payload = self._demo_scenario(plan)
        else:
            subject = self._resolve(plan.subject, plan.domain_id)
            if subject.get("status") != "resolved":
                return self._envelope(plan, subject, workspace_update={"tab": "ontology"})
            concept = subject["concept"]
            if plan.query_type == OntologyQueryType.CONCEPT_EXPLANATION:
                payload = self._concept_explanation(concept, plan)
            elif plan.query_type == OntologyQueryType.HIERARCHY:
                payload = self._hierarchy(concept, plan)
            elif plan.query_type == OntologyQueryType.TRANSITION_RULES:
                target_concept = None
                if plan.target:
                    target = self._resolve(plan.target, plan.domain_id)
                    if target.get("status") != "resolved":
                        return self._envelope(
                            plan,
                            target,
                            workspace_update={
                                "tab": "ontology",
                                "concept_id": concept["concept_id"],
                            },
                        )
                    target_concept = target["concept"]
                payload = self._transition_rules(concept, plan, target_concept)
            elif plan.query_type == OntologyQueryType.RELATION_PATH:
                target = self._resolve(plan.target, plan.domain_id)
                if target.get("status") != "resolved":
                    return self._envelope(
                        plan,
                        target,
                        workspace_update={
                            "tab": "ontology",
                            "concept_id": concept["concept_id"],
                        },
                    )
                payload = self._relation_path(concept, target["concept"], plan)
            else:  # pragma: no cover - Pydantic enum makes this unreachable
                raise ValueError("unsupported ontology query type")

        workspace = payload.pop("workspace_update", None) or {"tab": "ontology"}
        return self._envelope(plan, payload, workspace_update=workspace)

    def _resolve(self, reference: str, domain_id: str | None) -> dict[str, Any]:
        if not reference:
            return {"status": "invalid_plan", "message": "subject concept is required"}
        exact = self.service.get_concept(reference)
        if exact:
            return {"status": "resolved", "concept": exact}
        result = self.service.search_concepts(
            query=reference,
            domain_id=domain_id,
            kinds=DOMAIN_MODEL_KINDS,
            limit=10,
        )
        items = result.get("items") or []
        exact_labels = [
            item
            for item in items
            if reference.casefold()
            in {
                str(item.get("code") or "").casefold(),
                str(item.get("pref_label") or "").casefold(),
                *(str(label).casefold() for label in item.get("alt_labels") or []),
            }
        ]
        if len(exact_labels) == 1:
            return {"status": "resolved", "concept": exact_labels[0]}
        if len(items) == 1:
            return {"status": "resolved", "concept": items[0]}
        return {
            "status": "needs_disambiguation" if items else "not_found",
            "message": "存在多个本体候选，请使用稳定 ID 指定概念。"
            if items
            else "未找到匹配的领域概念。",
            "reference": reference,
            "candidates": [self._concept_summary(item) for item in items],
        }

    def _concept_explanation(
        self, concept: dict[str, Any], plan: OntologyQueryPlan
    ) -> dict[str, Any]:
        relations = (
            self.service.get_relations(
                concept["concept_id"],
                direction="both",
                limit=plan.limit,
            ).get("items")
            or []
        )
        projection, warning = self._projection("concept_summary", concept, plan.limit)
        parents = [
            row
            for row in relations
            if row["relation_type"] == "subClassOf" and row["traversal_direction"] == "out"
        ]
        children = [
            row
            for row in relations
            if row["relation_type"] == "subClassOf" and row["traversal_direction"] == "in"
        ]
        semantic_relations = [
            row for row in relations if row["relation_type"] != "hasDomainConcept"
        ]
        return {
            "status": "ok",
            "concept": self._concept_summary(concept, include_definition=True),
            "parents": [row["other_concept"] for row in parents],
            "children": [row["other_concept"] for row in children],
            "relations": semantic_relations[: plan.limit],
            "answer_facts": [
                f"{concept['pref_label']}是{concept.get('definition') or '尚待领域定义的概念'}",
                f"直接上位类 {len(parents)} 个，直接下位类 {len(children)} 个。",
            ],
            "rdf_projection": projection,
            "warnings": [warning] if warning else [],
            "workspace_update": {"tab": "ontology", "concept_id": concept["concept_id"]},
        }

    def _hierarchy(self, concept: dict[str, Any], plan: OntologyQueryPlan) -> dict[str, Any]:
        graph = self.service.get_graph(
            root_id=concept["concept_id"],
            depth=min(plan.depth, 3),
            limit=min(plan.limit, 100),
            include_mappings=False,
        )
        projection, warning = self._projection("direct_hierarchy", concept, plan.limit)
        edges = [
            edge
            for edge in graph.get("edges") or []
            if (edge.get("data") or {}).get("relationType") == "subClassOf"
        ]
        return {
            "status": "ok",
            "root": self._concept_summary(concept, include_definition=True),
            "hierarchy": {**graph, "edges": edges, "edge_count": len(edges)},
            "answer_facts": [
                f"以{concept['pref_label']}为中心返回 {graph.get('node_count', 0)} 个领域概念。",
                "层级边采用 rdfs:subClassOf，方向为子类指向父类。",
            ],
            "rdf_projection": projection,
            "warnings": [warning] if warning else [],
            "workspace_update": {"tab": "ontology", "concept_id": concept["concept_id"]},
        }

    def _transition_rules(
        self,
        concept: dict[str, Any],
        plan: OntologyQueryPlan,
        target_concept: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if concept.get("kind") != "ProcessClass":
            return self._transitions_for_land_concept(concept, plan, target_concept)
        details = self._transition_process(concept, plan, include_projection=True)
        if target_concept is None:
            return details

        target_state, target_interpretation = self._land_use_state_for(target_concept, plan.depth)
        target_scope = self._state_scope(target_state, plan.depth) if target_state else []
        target_scope_ids = {item["concept_id"] for item in target_scope}
        matches_target = any(
            item.get("concept_id") in target_scope_ids for item in details["allowed_target_states"]
        )
        details.update(
            {
                "target": self._concept_summary(target_concept, include_definition=True),
                "interpreted_target_state": self._concept_summary(
                    target_state, include_definition=True
                )
                if target_state
                else None,
                "target_interpretation": target_interpretation,
                "target_state_scope": [self._concept_summary(item) for item in target_scope],
                "matches_target": matches_target,
            }
        )
        details["answer_facts"].insert(
            0,
            (
                f"{concept['pref_label']}"
                + ("允许" if matches_target else "未注册为允许")
                + f"转为{target_concept['pref_label']}。"
            ),
        )
        return details

    def _transition_process(
        self,
        concept: dict[str, Any],
        plan: OntologyQueryPlan,
        *,
        include_projection: bool,
    ) -> dict[str, Any]:
        direct = (
            self.service.get_relations(concept["concept_id"], direction="out", limit=100).get(
                "items"
            )
            or []
        )
        rules = [
            row for row in direct if row.get("relation_type") in {"allowedSource", "allowedTarget"}
        ]
        inherited: list[dict[str, Any]] = []
        frontier = [
            row["target_concept_id"] for row in direct if row.get("relation_type") == "subClassOf"
        ]
        visited: set[str] = set()
        for _ in range(min(plan.depth, 4)):
            next_frontier: list[str] = []
            for parent_id in frontier:
                if parent_id in visited:
                    continue
                visited.add(parent_id)
                parent_rows = (
                    self.service.get_relations(parent_id, direction="out", limit=100).get("items")
                    or []
                )
                inherited.extend(
                    row for row in parent_rows if row.get("relation_type") == "objectProperty"
                )
                next_frontier.extend(
                    row["target_concept_id"]
                    for row in parent_rows
                    if row.get("relation_type") == "subClassOf"
                )
            frontier = next_frontier
        projection, warning = (None, None)
        if include_projection:
            projection, warning = self._projection("transition_rules", concept, plan.limit)
        source_states = [
            row["other_concept"] for row in rules if row["relation_type"] == "allowedSource"
        ]
        target_states = [
            row["other_concept"] for row in rules if row["relation_type"] == "allowedTarget"
        ]
        requirements = [
            {
                "property": (row.get("provenance") or {}).get("property_name"),
                "label": row.get("pref_label"),
                "target": row.get("other_concept"),
                "inherited_from": row.get("source_concept_id"),
            }
            for row in inherited
        ]
        return {
            "status": "ok",
            "process": self._concept_summary(concept, include_definition=True),
            "allowed_source_states": source_states,
            "allowed_target_states": target_states,
            "semantic_requirements": requirements,
            "answer_facts": [
                (
                    f"{concept['pref_label']}允许 {len(source_states)} 类源状态和 "
                    f"{len(target_states)} 类目标状态。"
                ),
                "批准文件、法律依据等要求来自过程上位类的对象属性及发布包 SHACL 约束。",
            ],
            "rdf_projection": projection,
            "warnings": [warning] if warning else [],
            "workspace_update": {"tab": "ontology", "concept_id": concept["concept_id"]},
        }

    def _transitions_for_land_concept(
        self,
        concept: dict[str, Any],
        plan: OntologyQueryPlan,
        target_concept: dict[str, Any] | None,
    ) -> dict[str, Any]:
        state, interpretation = self._land_use_state_for(concept, plan.depth)
        if state is None:
            return {
                "status": "ok",
                "subject": self._concept_summary(concept, include_definition=True),
                "interpreted_state": None,
                "interpretation": interpretation,
                "state_scope": [],
                "processes": [],
                "answer_facts": [
                    f"{concept['pref_label']}尚未注册到土地利用状态类，因此没有可执行的转换规则。",
                    "这不代表业务上绝对不存在转换，只表示当前发布本体没有形成受治理规则。",
                ],
                "rdf_projection": None,
                "warnings": [],
                "workspace_update": {
                    "tab": "ontology",
                    "concept_id": concept["concept_id"],
                },
            }

        target_state = None
        target_interpretation = None
        target_scope: list[dict[str, Any]] = []
        if target_concept is not None:
            target_state, target_interpretation = self._land_use_state_for(
                target_concept, plan.depth
            )
            if target_state is None:
                return {
                    "status": "ok",
                    "subject": self._concept_summary(concept, include_definition=True),
                    "interpreted_state": self._concept_summary(state, include_definition=True),
                    "interpretation": interpretation,
                    "target": self._concept_summary(target_concept, include_definition=True),
                    "interpreted_target_state": None,
                    "target_interpretation": target_interpretation,
                    "state_scope": [],
                    "target_state_scope": [],
                    "processes": [],
                    "answer_facts": [
                        f"{target_concept['pref_label']}尚未注册到土地利用状态类，无法形成受治理的目标状态过滤。"
                    ],
                    "rdf_projection": None,
                    "warnings": [],
                    "workspace_update": {
                        "tab": "ontology",
                        "concept_id": concept["concept_id"],
                    },
                }
            target_scope = self._state_scope(target_state, plan.depth)

        state_scope = self._state_scope(state, plan.depth)
        target_scope_ids = {item["concept_id"] for item in target_scope}
        matches: dict[str, list[dict[str, Any]]] = {}
        for scoped_state in state_scope:
            rows = (
                self.service.get_relations(
                    scoped_state["concept_id"], direction="in", limit=100
                ).get("items")
                or []
            )
            for row in rows:
                allowed_relations = (
                    {"allowedSource"}
                    if target_concept is not None
                    else {"allowedSource", "allowedTarget"}
                )
                if row.get("relation_type") not in allowed_relations:
                    continue
                process_id = row.get("source_concept_id")
                if not process_id:
                    continue
                matches.setdefault(process_id, []).append(
                    {
                        "rule": row.get("relation_type"),
                        "state": self._concept_summary(scoped_state),
                    }
                )

        processes: list[dict[str, Any]] = []
        for process_id in sorted(matches):
            process = self.service.get_concept(process_id)
            if not process or process.get("kind") != "ProcessClass":
                continue
            details = self._transition_process(process, plan, include_projection=False)
            details.pop("workspace_update", None)
            details.pop("rdf_projection", None)
            details.pop("warnings", None)
            if target_scope_ids and not any(
                item.get("concept_id") in target_scope_ids
                for item in details["allowed_target_states"]
            ):
                continue
            details["matched_state_rules"] = matches[process_id]
            processes.append(details)

        if target_concept is not None:
            projection, warning = self._transition_process_projection(
                [item["process"] for item in processes], plan.limit
            )
        else:
            projection, warning = self._projection("state_transition_processes", state, plan.limit)
        target_label = target_concept["pref_label"] if target_concept else None
        return {
            "status": "ok",
            "subject": self._concept_summary(concept, include_definition=True),
            "interpreted_state": self._concept_summary(state, include_definition=True),
            "interpretation": interpretation,
            "target": self._concept_summary(target_concept, include_definition=True)
            if target_concept
            else None,
            "interpreted_target_state": self._concept_summary(target_state, include_definition=True)
            if target_state
            else None,
            "target_interpretation": target_interpretation,
            "state_scope": [self._concept_summary(item) for item in state_scope],
            "target_state_scope": [self._concept_summary(item) for item in target_scope],
            "processes": processes,
            "answer_facts": [
                (
                    f"将{concept['pref_label']}按{state['pref_label']}解释，"
                    + (
                        f"以{target_label}为目标过滤后找到 {len(processes)} 个受治理转换过程。"
                        if target_label
                        else f"在其上下位状态范围内找到 {len(processes)} 个受治理转换过程。"
                    )
                ),
                "每个过程分别给出允许源状态、允许目标状态及继承的审批/依据要求。",
            ],
            "rdf_projection": projection,
            "warnings": [warning] if warning else [],
            "workspace_update": {
                "tab": "ontology",
                "concept_id": concept["concept_id"],
            },
        }

    def _transition_process_projection(
        self,
        processes: list[dict[str, Any]],
        limit: int,
    ) -> tuple[dict[str, Any] | None, str | None]:
        if not self.sparql.configured:
            return (
                None,
                "Fuseki RDF projection is not configured; authority/package result was used.",
            )
        rows: list[dict[str, Any]] = []
        try:
            for process in processes:
                remaining = min(limit, self.sparql.MAX_ROWS) - len(rows)
                if remaining <= 0:
                    break
                result = self.sparql.select(
                    "transition_rules",
                    concept_uri=process["uri"],
                    limit=remaining,
                )
                rows.extend(
                    {
                        "process": process["uri"],
                        "processLabel": process["pref_label"],
                        **row,
                    }
                    for row in result.rows
                )
        except SparqlProjectionUnavailable as exc:
            return None, f"RDF projection unavailable; governed fallback used: {exc}"
        return {
            "backend": "apache_jena_fuseki_tdb2",
            "template_id": "transition_rules_by_process",
            "row_count": len(rows),
            "rows": rows,
        }, None

    def _land_use_state_for(
        self, concept: dict[str, Any], depth: int
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if concept.get("kind") == "StateClass":
            return concept, {
                "method": "exact_state_class",
                "source_concept_id": concept["concept_id"],
                "state_concept_id": concept["concept_id"],
            }
        if concept.get("kind") != "DomainClass":
            return None, {
                "method": "no_registered_land_use_state",
                "source_concept_id": concept["concept_id"],
            }

        current = concept
        for distance in range(min(depth, 4) + 1):
            code = str(current.get("code") or "")
            candidate = self.service.get_concept(f"gda:nr:class:{code}UseState")
            if candidate and candidate.get("kind") == "StateClass":
                return candidate, {
                    "method": (
                        "domain_code_to_state_class"
                        if distance == 0
                        else "ancestor_domain_code_to_state_class"
                    ),
                    "source_concept_id": concept["concept_id"],
                    "matched_domain_concept_id": current["concept_id"],
                    "state_concept_id": candidate["concept_id"],
                    "hierarchy_distance": distance,
                }
            parents = [
                row.get("other_concept")
                for row in (
                    self.service.get_relations(
                        current["concept_id"], direction="out", limit=50
                    ).get("items")
                    or []
                )
                if row.get("relation_type") == "subClassOf"
                and (row.get("other_concept") or {}).get("kind") == "DomainClass"
            ]
            if len(parents) != 1:
                break
            parent = self.service.get_concept(parents[0]["concept_id"])
            if not parent:
                break
            current = parent
        return None, {
            "method": "no_registered_land_use_state",
            "source_concept_id": concept["concept_id"],
        }

    def _state_scope(self, root: dict[str, Any], depth: int) -> list[dict[str, Any]]:
        scope = {root["concept_id"]: root}
        max_depth = min(depth, 4)
        for direction, traversal_direction in (("out", "out"), ("in", "in")):
            frontier = [root]
            visited = {root["concept_id"]}
            for _ in range(max_depth):
                next_frontier: list[dict[str, Any]] = []
                for current in frontier:
                    rows = (
                        self.service.get_relations(
                            current["concept_id"], direction=direction, limit=100
                        ).get("items")
                        or []
                    )
                    for row in rows:
                        other = row.get("other_concept") or {}
                        other_id = other.get("concept_id")
                        if (
                            row.get("relation_type") != "subClassOf"
                            or row.get("traversal_direction") != traversal_direction
                            or other.get("kind") != "StateClass"
                            or not other_id
                            or other_id in visited
                        ):
                            continue
                        resolved = self.service.get_concept(other_id)
                        if resolved:
                            visited.add(other_id)
                            scope[other_id] = resolved
                            next_frontier.append(resolved)
                frontier = next_frontier
        return [scope[key] for key in sorted(scope)]

    def _relation_path(
        self,
        source: dict[str, Any],
        target: dict[str, Any],
        plan: OntologyQueryPlan,
    ) -> dict[str, Any]:
        queue = deque([(source["concept_id"], [])])
        visited = {source["concept_id"]}
        found: list[dict[str, Any]] | None = None
        while queue and len(visited) <= self.MAX_PATH_VISITS:
            current, path = queue.popleft()
            if len(path) >= plan.depth:
                continue
            rows = (
                self.service.get_relations(current, direction="both", limit=100).get("items") or []
            )
            for row in rows:
                other = row.get("other_concept") or {}
                other_id = other.get("concept_id")
                if not other_id or other.get("kind") not in DOMAIN_MODEL_KINDS:
                    continue
                step = {
                    "source": current,
                    "relation_type": row.get("relation_type"),
                    "label": row.get("pref_label"),
                    "direction": row.get("traversal_direction"),
                    "target": other_id,
                    "target_label": other.get("pref_label"),
                }
                next_path = [*path, step]
                if other_id == target["concept_id"]:
                    found = next_path
                    queue.clear()
                    break
                if other_id not in visited:
                    visited.add(other_id)
                    queue.append((other_id, next_path))
        return {
            "status": "ok" if found else "not_found",
            "source": self._concept_summary(source),
            "target": self._concept_summary(target),
            "path": found or [],
            "visited_count": len(visited),
            "answer_facts": [
                f"在最大 {plan.depth} 跳、{self.MAX_PATH_VISITS} 节点预算内"
                + (f"找到 {len(found)} 跳语义路径。" if found else "未找到关系路径。")
            ],
            "workspace_update": {
                "tab": "ontology",
                "concept_id": source["concept_id"],
                "relation_path": found or [],
            },
        }

    def _schema_mapping(self, plan: OntologyQueryPlan) -> dict[str, Any]:
        if not plan.field_codes:
            return {"status": "invalid_plan", "message": "field_codes is required"}
        aligned = self.service.align_fields(
            [{"code": code, "name": code} for code in plan.field_codes],
            domain_id=plan.domain_id,
        )
        curated: list[dict[str, Any]] = []
        try:
            from ..natural_resource_ontology_demo import get_natural_resource_ontology_demo

            demo_mappings = (
                get_natural_resource_ontology_demo().evidence().get("field_mappings") or []
            )
            for code in plan.field_codes:
                matches = [
                    row
                    for row in demo_mappings
                    if str(row.get("source") or "").casefold().endswith(f".{code}".casefold())
                ]
                curated.extend(matches)
        except Exception:
            pass
        return {
            "status": "ok",
            "field_alignment": aligned,
            "curated_application_mappings": curated,
            "answer_facts": [
                (
                    f"对 {len(plan.field_codes)} 个字段执行代码/名称确定性匹配；"
                    "候选结果不会自动晋升为正式映射。"
                ),
                f"命中 {len(curated)} 条已版本化演示应用映射。",
            ],
            "workspace_update": {"tab": "ontology", "view": "mappings"},
        }

    def _demo_scenario(self, plan: OntologyQueryPlan) -> dict[str, Any]:
        from ..natural_resource_ontology_demo import get_natural_resource_ontology_demo

        scenario_id = plan.scenario_id or "heping_review"
        demo = get_natural_resource_ontology_demo()
        result = demo.run(scenario_id)
        attestation = result.get("attestation") or {}
        if result.get("status") != "completed" or attestation.get("passed") is not True:
            return {
                "status": "attestation_failed",
                "scenario_result": result,
                "answer_facts": [
                    "场景执行证明未通过，业务结果和地图图层已阻止展示。"
                ],
                "workspace_update": {
                    "tab": "ontology_demo",
                    "scenario_id": scenario_id,
                    "auto_run": False,
                    "view": "results",
                },
            }
        map_update = demo.map_payload(scenario_id)
        return {
            "status": "ok",
            "scenario_result": result,
            "map_update": {key: value for key, value in map_update.items() if key != "scenario_id"},
            "answer_facts": [result["headline"], result["decision_scope"]],
            "workspace_update": {
                "tab": "ontology_demo",
                "scenario_id": scenario_id,
                "auto_run": True,
                "view": "results",
            },
        }

    def _projection(
        self,
        template_id: str,
        concept: dict[str, Any],
        limit: int,
    ) -> tuple[dict[str, Any] | None, str | None]:
        if not self.sparql.configured:
            return (
                None,
                "Fuseki RDF projection is not configured; authority/package result was used.",
            )
        try:
            result = self.sparql.select(
                template_id,
                concept_uri=concept["uri"],
                limit=limit,
            )
            return {
                "backend": "apache_jena_fuseki_tdb2",
                "template_id": result.template_id,
                "row_count": len(result.rows),
                "rows": result.rows,
            }, None
        except SparqlProjectionUnavailable as exc:
            return None, f"RDF projection unavailable; governed fallback used: {exc}"

    def _envelope(
        self,
        plan: OntologyQueryPlan,
        result: dict[str, Any],
        *,
        workspace_update: dict[str, Any],
    ) -> dict[str, Any]:
        manifest = self.service.reader.manifest
        warnings = result.get("warnings") or []
        authority = self.service.reader.status()
        generated_at = datetime.now(UTC).isoformat()
        payload = {
            "status": result.get("status", "ok"),
            "query_plan": plan.audit_parameters(),
            "result": result,
            "workspace_update": workspace_update,
            "ontology_evidence": {
                "semantic_version": manifest.semantic_version,
                "content_sha256": manifest.content_sha256,
                "package_id": manifest.package_id,
                "authority_backend": authority.get("backend"),
                "rdf_store": "apache_jena_fuseki_tdb2"
                if self.sparql.configured
                else "not_configured",
                "warnings": warnings,
            },
            "query_provenance": {
                "generated": {
                    "by": "gda-ontology-query-engine/2.0",
                    "at": generated_at,
                },
                "executor": "google-adk/OntologyAnalysisAgent",
                "parameters": plan.audit_parameters(),
                "sources": [
                    {
                        "id": manifest.package_id,
                        "resource": "/api/ontology/export/manifest",
                        "digest": {"sha256": manifest.content_sha256},
                    }
                ],
            },
            "okf_reference": okf_reference(
                query_type=plan.query_type.value,
                scenario_id=plan.scenario_id,
            ),
        }
        scenario_attestation = (result.get("scenario_result") or {}).get("attestation")
        if scenario_attestation:
            payload["attestation"] = scenario_attestation
        return payload

    @staticmethod
    def _concept_summary(
        concept: dict[str, Any], *, include_definition: bool = False
    ) -> dict[str, Any]:
        keys = ["concept_id", "uri", "code", "pref_label", "kind", "domain_id", "source_system"]
        if include_definition:
            keys.extend(["definition", "alt_labels", "provenance"])
        return {key: concept.get(key) for key in keys if concept.get(key) not in (None, "")}
