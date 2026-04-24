"""Intake Registry — review, activate, rollback semantic drafts into production.

Handles the reviewed → validated → active transitions and writes
confirmed semantic metadata into the production agent_semantic_sources
and agent_semantic_registry tables.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy import text

from .db_engine import get_engine

logger = logging.getLogger(__name__)


def review_draft(
    draft_id: int,
    approved_columns: Optional[list[str]] = None,
    blocked_columns: Optional[list[str]] = None,
    approved_joins: Optional[list[str]] = None,
    notes: str = "",
    reviewed_by: str = "admin",
) -> dict:
    """Mark a semantic draft as reviewed with human annotations.

    Args:
        draft_id: ID of the semantic draft.
        approved_columns: Column names confirmed as queryable.
        blocked_columns: Column names to exclude from NL2SQL.
        approved_joins: Target table names approved for cross-table queries.
        notes: Free-text review notes.
        reviewed_by: Username of the reviewer.
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "error": "no database engine"}

    with engine.begin() as conn:
        draft = conn.execute(text(
            "SELECT id, profile_id, table_name, columns_draft, join_candidates, status "
            "FROM agent_semantic_drafts WHERE id = :did"
        ), {"did": draft_id}).fetchone()
        if not draft:
            return {"status": "error", "error": "draft not found"}

        _, profile_id, table_name, cols_raw, joins_raw, status = draft
        if status not in ("drafted", "reviewed"):
            return {"status": "error", "error": f"cannot review draft in status '{status}'"}

        columns_draft = json.loads(cols_raw) if isinstance(cols_raw, str) else cols_raw
        join_candidates = json.loads(joins_raw) if isinstance(joins_raw, str) else joins_raw

        blocked = set(blocked_columns or [])
        for col in columns_draft:
            if col["column_name"] in blocked:
                col["blocked"] = True

        if approved_joins is not None:
            approved_set = set(approved_joins)
            for jc in join_candidates:
                jc["approved"] = jc.get("target_table") in approved_set

        conn.execute(text("""
            UPDATE agent_semantic_drafts
            SET columns_draft = :cols::jsonb,
                join_candidates = :joins::jsonb,
                review_notes = :notes,
                reviewed_by = :reviewer,
                reviewed_at = NOW(),
                status = 'reviewed',
                updated_at = NOW()
            WHERE id = :did
        """), {
            "cols": json.dumps(columns_draft, ensure_ascii=False),
            "joins": json.dumps(join_candidates, ensure_ascii=False),
            "notes": notes,
            "reviewer": reviewed_by,
            "did": draft_id,
        })

        conn.execute(text(
            "UPDATE agent_dataset_profiles SET status = 'reviewed', updated_at = NOW() WHERE id = :pid"
        ), {"pid": profile_id})

    return {"status": "ok", "draft_id": draft_id, "table_name": table_name}


def activate_draft(
    draft_id: int,
    eval_score: Optional[float] = None,
    eval_details: Optional[dict] = None,
    activated_by: str = "admin",
) -> dict:
    """Activate a reviewed draft: write into production semantic tables.

    This is the only path that writes to agent_semantic_sources and
    agent_semantic_registry from the intake pipeline.
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "error": "no database engine"}

    with engine.begin() as conn:
        draft = conn.execute(text(
            "SELECT id, profile_id, table_name, version, display_name, description, "
            "aliases_json, columns_draft, join_candidates "
            "FROM agent_semantic_drafts WHERE id = :did"
        ), {"did": draft_id}).fetchone()
        if not draft:
            return {"status": "error", "error": "draft not found"}

        did, profile_id, table_name, version, display_name, description, \
            aliases_raw, cols_raw, joins_raw = draft

        columns_draft = json.loads(cols_raw) if isinstance(cols_raw, str) else cols_raw
        aliases = json.loads(aliases_raw) if isinstance(aliases_raw, str) else (aliases_raw or [])

        # Get geometry info from profile
        profile = conn.execute(text(
            "SELECT geometry_type, srid FROM agent_dataset_profiles WHERE id = :pid"
        ), {"pid": profile_id}).fetchone()
        geom_type = profile[0] if profile else None
        srid = profile[1] if profile else None

        # Deactivate previous activations for this dataset
        conn.execute(text(
            "UPDATE agent_semantic_activations SET is_current = FALSE WHERE dataset_id = :pid"
        ), {"pid": profile_id})

        # Write to production semantic_sources
        conn.execute(text("""
            INSERT INTO agent_semantic_sources
                (table_name, display_name, description, geometry_type, srid,
                 synonyms, owner_username)
            VALUES (:tbl, :dn, :desc, :gt, :srid, :syns::jsonb, :owner)
            ON CONFLICT (table_name) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                description = EXCLUDED.description,
                geometry_type = EXCLUDED.geometry_type,
                srid = EXCLUDED.srid,
                synonyms = EXCLUDED.synonyms,
                updated_at = NOW()
        """), {
            "tbl": table_name, "dn": display_name, "desc": description,
            "gt": geom_type, "srid": srid,
            "syns": json.dumps(aliases, ensure_ascii=False),
            "owner": activated_by,
        })

        # Write to production semantic_registry (per-column)
        for col in columns_draft:
            if col.get("blocked"):
                continue
            is_geom = col.get("is_geometry", False)
            conn.execute(text("""
                INSERT INTO agent_semantic_registry
                    (table_name, column_name, semantic_domain, aliases,
                     unit, description, is_geometry, owner_username)
                VALUES (:tbl, :col, :domain, :aliases::jsonb,
                        :unit, :desc, :is_geom, :owner)
                ON CONFLICT (table_name, column_name) DO UPDATE SET
                    semantic_domain = EXCLUDED.semantic_domain,
                    aliases = EXCLUDED.aliases,
                    description = EXCLUDED.description,
                    is_geometry = EXCLUDED.is_geometry,
                    updated_at = NOW()
            """), {
                "tbl": table_name,
                "col": col["column_name"],
                "domain": col.get("semantic_domain"),
                "aliases": json.dumps(col.get("aliases", []), ensure_ascii=False),
                "unit": col.get("unit", ""),
                "desc": col.get("description", ""),
                "is_geom": is_geom,
                "owner": activated_by,
            })

        # Record activation
        conn.execute(text("""
            INSERT INTO agent_semantic_activations
                (dataset_id, draft_id, draft_version, eval_score, eval_details,
                 activated_by, is_current)
            VALUES (:pid, :did, :ver, :score, :details::jsonb, :user, TRUE)
        """), {
            "pid": profile_id, "did": draft_id, "ver": version,
            "score": eval_score, "details": json.dumps(eval_details or {}),
            "user": activated_by,
        })

        # Update statuses
        conn.execute(text(
            "UPDATE agent_semantic_drafts SET status = 'active', updated_at = NOW() WHERE id = :did"
        ), {"did": draft_id})
        conn.execute(text(
            "UPDATE agent_dataset_profiles SET status = 'active', updated_at = NOW() WHERE id = :pid"
        ), {"pid": profile_id})

        # Invalidate semantic cache
        try:
            from .semantic_layer import invalidate_semantic_cache
            invalidate_semantic_cache()
        except Exception:
            pass

    return {
        "status": "ok",
        "table_name": table_name,
        "version": version,
        "eval_score": eval_score,
    }


def rollback_activation(dataset_id: int) -> dict:
    """Rollback to the previous activation version for a dataset."""
    engine = get_engine()
    if not engine:
        return {"status": "error", "error": "no database engine"}

    with engine.begin() as conn:
        current = conn.execute(text(
            "SELECT id, draft_id FROM agent_semantic_activations "
            "WHERE dataset_id = :did AND is_current = TRUE"
        ), {"did": dataset_id}).fetchone()
        if not current:
            return {"status": "error", "error": "no current activation"}

        conn.execute(text(
            "UPDATE agent_semantic_activations SET is_current = FALSE, rolled_back_at = NOW() WHERE id = :aid"
        ), {"aid": current[0]})

        previous = conn.execute(text(
            "SELECT id, draft_id FROM agent_semantic_activations "
            "WHERE dataset_id = :did AND id < :cur ORDER BY id DESC LIMIT 1"
        ), {"did": dataset_id, "cur": current[0]}).fetchone()

        if previous:
            conn.execute(text(
                "UPDATE agent_semantic_activations SET is_current = TRUE WHERE id = :aid"
            ), {"aid": previous[0]})
            # Re-activate previous draft
            activate_draft(previous[1])
            return {"status": "ok", "rolled_back_to": previous[0]}

        # No previous version — remove from production semantic tables
        profile = conn.execute(text(
            "SELECT table_name FROM agent_dataset_profiles WHERE id = :did"
        ), {"did": dataset_id}).fetchone()
        if profile:
            tbl = profile[0]
            conn.execute(text("DELETE FROM agent_semantic_registry WHERE table_name = :t"), {"t": tbl})
            conn.execute(text("DELETE FROM agent_semantic_sources WHERE table_name = :t"), {"t": tbl})
            conn.execute(text(
                "UPDATE agent_dataset_profiles SET status = 'reviewed', updated_at = NOW() WHERE id = :did"
            ), {"did": dataset_id})

        try:
            from .semantic_layer import invalidate_semantic_cache
            invalidate_semantic_cache()
        except Exception:
            pass

    return {"status": "ok", "rolled_back_to": None, "removed_from_production": True}
