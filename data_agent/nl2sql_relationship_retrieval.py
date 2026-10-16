"""Retrieve relationship roles from the current authorized physical catalog.

Registered foreign keys supply endpoints, not business intent or observed
cardinality. Table/field descriptions distinguish roles. No new joins or SQL
rewrites are inferred from lexical relevance or graph distance.
"""
from __future__ import annotations

import hashlib
import json

from .nl2sql_prompt_metadata import field_prompt_annotations, field_prompt_description
from .nl2sql_observability import observe_stage


def relationship_catalog(tables: list[dict]) -> list[dict]:
    by_name = {t["table_name"]: t for t in tables}
    result = {}
    for source_name, table in sorted(by_name.items()):
        source_columns = {c["column_name"]: c for c in table.get("columns") or []}
        for fk in table.get("foreign_keys") or []:
            # Resolve a bare target in the source schema; never fall back to
            # an unrelated authorized schema sharing the same table name.
            target_name = fk.get("target_table")
            if not isinstance(target_name, str):
                continue
            if "." not in target_name and "." in source_name:
                target_name = source_name.rsplit(".", 1)[0] + "." + target_name
            target = by_name.get(target_name)
            if target is None:
                continue
            target_columns = {c["column_name"]: c for c in target.get("columns") or []}
            a, b = fk.get("column"), fk.get("target_column")
            if not isinstance(a, str) or not isinstance(b, str) or a not in source_columns or b not in target_columns:
                continue
            left, right = source_columns[a], target_columns[b]
            aliases, semantics = field_prompt_annotations(left)
            description = field_prompt_description(left)
            identity = json.dumps([source_name, a, target_name, b], separators=(",", ":"))
            key = "relation:" + hashlib.sha256(identity.encode()).hexdigest()[:20]
            result[key] = {
                "id": key, "source_table": source_name, "source_field": a,
                "target_table": target_name, "target_field": b,
                "source_role": {"description": description, "aliases": aliases, "semantics": semantics},
                "target_description": field_prompt_description(right),
                # A partial composite key cannot prove a unique target. No
                # source uniqueness, non-NULL or referential coverage claim.
                "target_is_registered_single_primary_key": target.get("primary_keys") == [b],
                "multiplicity_note": "Multiple source rows may refer to one target; joined entity counts and sums require an explicit grain.",
                "intent_status": "candidate_requires_question_interpretation",
            }
    return sorted(result.values(), key=lambda r: r["id"])


@observe_stage("retrieval.dependencies")
def retrieve_relationships(question: str, tables: list[dict], anchor_tables: list[str]) -> dict:
    from .nl2sql_semantic_retrieval import rank_documents

    catalog = relationship_catalog(tables)
    table_names = {t["table_name"] for t in tables}
    anchors = set(anchor_tables) & table_names
    documents = []
    for relation in catalog:
        role = relation["source_role"]
        documents.append({
            "id": relation["id"], "aliases": role["aliases"],
            "search_text": " ".join([
                relation["source_table"].rsplit(".", 1)[-1], relation["source_field"],
                relation["target_table"].rsplit(".", 1)[-1], role["description"],
                json.dumps(role["semantics"], ensure_ascii=False),
            ]), "relation": relation,
        })
    ranked = rank_documents(question, documents)
    hits = [{**d["relation"], "retrieval": {k: d[k] for k in ("score", "matched_terms", "matched_aliases")}}
            for d in ranked[:6]]
    # Surface competing roles whenever one relationship to a shared target
    # matches. Never collapse residence/branch or first/second endpoint roles.
    matched_targets = {r["target_table"] for r in hits}
    alternatives = [{"target_table": target,
                     "relation_ids": [r["id"] for r in catalog if r["target_table"] == target],
                     "selection_status": "unresolved_choose_by_requested_role"}
                    for target in sorted(matched_targets)
                    if sum(r["target_table"] == target for r in catalog) > 1]
    # A role can be recalled even when its table was absent from lexical field
    # hits. Include its authorized endpoints (and competing roles' endpoints)
    # as path anchors, otherwise a recalled account role can still lose the
    # person--disposition--account bridge to a residence-only lexical match.
    role_ids = {r["id"] for r in hits} | {r for g in alternatives for r in g["relation_ids"]}
    anchors.update(name for r in catalog if r["id"] in role_ids
                   for name in (r["source_table"], r["target_table"]))
    # Keep all authorized edges in a compact form so alternatives cannot
    # name an edge the model cannot inspect, even below the lexical hit cap.
    edges = [{k: r[k] for k in ("id", "source_table", "source_field", "target_table", "target_field",
                                "source_role", "target_is_registered_single_primary_key")}
             for r in catalog]
    adjacency = {name: [] for name in table_names}
    for r in catalog:
        if r["source_table"] == r["target_table"]:
            continue
        adjacency[r["source_table"]].append((r["target_table"], r["id"]))
        adjacency[r["target_table"]].append((r["source_table"], r["id"]))
    # Only two-edge paths are enumerated here. Preserve each parallel role
    # path and direct edge; a shortest path cannot decide business meaning.
    paths = {}
    for start in sorted(anchors):
        for bridge, first in sorted(adjacency[start]):
            for end, second in sorted(adjacency[bridge]):
                if end not in anchors or start >= end or second == first:
                    continue
                key = (start, bridge, end, first, second)
                paths[key] = {"tables": [start, bridge, end], "relation_ids": [first, second],
                              "status": "candidate_not_selected_by_graph_distance"}
    ordered_paths = [paths[key] for key in sorted(paths)]
    return {
        "catalog_sha256": hashlib.sha256(json.dumps(catalog, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        "registered_relationship_count": len(catalog), "relationships": edges,
        "path_anchor_tables": sorted(anchors),
        "role_hits": hits, "role_alternatives": alternatives,
        "two_edge_paths": ordered_paths[:16], "paths_truncated": len(ordered_paths) > 16,
        "limitations": "Registered endpoints and primary keys are metadata, not observed integrity or a proof of requested role, population, multiplicity or SQL correctness. Only two-edge paths are enumerated; all direct edges remain available.",
    }


def relationship_guidance(packet: dict) -> str:
    if not packet or not packet.get("registered_relationship_count"):
        return ""
    # Keep stable catalog IDs and full retrieval evidence in the audit packet.
    # The prompt uses local references and renders each role only once, rather
    # than repeating the same field semantics in hits, alternatives and paths.
    references = {r["id"]: f"r{i}" for i, r in enumerate(packet["relationships"], 1)}
    table_names = sorted({r[key] for r in packet["relationships"] for key in ("source_table", "target_table")})
    table_references = {name: f"t{i}" for i, name in enumerate(table_names, 1)}
    relationships = []
    for relation in packet["relationships"]:
        item = {
            "id": references[relation["id"]],
            "source": [table_references[relation["source_table"]], relation["source_field"]],
            "target": [table_references[relation["target_table"]], relation["target_field"]],
            "role": {k: v for k, v in relation["source_role"].items() if v},
        }
        relationships.append(item)
    compact = {
        "tables": {ref: name for name, ref in table_references.items()},
        "relationships": relationships,
        "relations_targeting_registered_single_primary_key": [
            references[r["id"]] for r in packet["relationships"] if r["target_is_registered_single_primary_key"]
        ],
        "ranked_role_candidates": [references[r["id"]] for r in packet["role_hits"]],
        "unresolved_alternative_roles": [
            {"target": table_references[group["target_table"]], "relations": [references[r] for r in group["relation_ids"]]}
            for group in packet["role_alternatives"]
        ],
        "two_edge_path_candidates": [
            {"tables": [table_references[t] for t in path["tables"]],
             "relations": [references[r] for r in path["relation_ids"]]}
            for path in packet["two_edge_paths"]
        ],
        "paths_truncated": packet["paths_truncated"],
    }
    return (
        "\n## Authorized relationship roles and bridge candidates\n"
        "Choose each relationship by its source field meaning and the question's role. "
        "The same lookup table can represent different roles. A direct or shortest path is not necessarily the requested relationship. "
        "Retain necessary bridge tables; two entities sharing a parent are not thereby directly related. "
        "When a detail relation only tests membership, consider EXISTS to retain the requested entity grain; "
        "do not add DISTINCT or merge equal measure values without a grain contract. "
        "Multiple source rows may refer to one target. Registered endpoints and primary keys are metadata, "
        "not observed integrity or proof of role, population, multiplicity or SQL correctness. "
        "Only two-edge paths are enumerated (at most 16); all registered authorized edges remain below. "
        "Ranked roles, alternative roles and paths are unselected candidates. "
        "These candidates do not authorize extra tables, filters, joins or automatic SQL changes.\n"
        + json.dumps(compact, ensure_ascii=False, separators=(",", ":")) + "\n"
    )
