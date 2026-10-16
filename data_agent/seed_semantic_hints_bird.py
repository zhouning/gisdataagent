"""Publish the public BIRD semantic contracts into the semantic layer.

The NL2SQL renderer consumes ``agent_semantic_hints``; this module is the
repeatable publication step for the reviewed BIRD dictionary rules.  It does
not contain benchmark questions, Gold SQL, expected answers, or model output.
"""
from __future__ import annotations

import json
from .bird_semantic_contracts import _DATABASE_CONTRACTS

SOURCE_TAG = "bird_public_semantics_v1"
OWNER = "bird_benchmark"


def _rows() -> list[dict]:
    rows: list[dict] = []
    for db_id, contract in _DATABASE_CONTRACTS.items():
        for rule in (str(contract["population"]), *map(str, contract["rules"])):
            rows.append({
                "scope_type": "dataset", "scope_ref": f"bird_{db_id}",
                "hint_kind": "other", "severity": "info",
                "hint_text_zh": rule, "hint_text_en": rule,
                "trigger_keywords": [],
            })
    return rows


def seed_semantic_hints_bird(owner: str = OWNER) -> dict:
    """Idempotently publish the contracts and invalidate semantic caches."""
    from sqlalchemy import text
    from .db_engine import get_engine
    from .semantic_layer import invalidate_semantic_cache

    engine = get_engine()
    if engine is None:
        return {"status": "no_db", "hints": 0}
    rows = _rows()
    with engine.begin() as conn:
        # Replace only this publisher's own bundle, so revised text cannot
        # leave contradictory stale rules behind on subsequent publication.
        conn.execute(text("""
            DELETE FROM agent_semantic_hints
            WHERE source_tag=:source_tag AND owner_username=:owner
              AND scope_type='dataset' AND scope_ref=ANY(:scopes)
        """), {"source_tag": SOURCE_TAG, "owner": owner,
                "scopes": sorted({row["scope_ref"] for row in rows})})
        for row in rows:
            conn.execute(text("""
                INSERT INTO agent_semantic_hints
                    (scope_type, scope_ref, hint_kind, hint_text_zh,
                     hint_text_en, severity, trigger_keywords,
                     source_tag, owner_username)
                VALUES (:scope_type, :scope_ref, :hint_kind, :hint_text_zh,
                        :hint_text_en, :severity, CAST(:trigger_keywords AS jsonb),
                        :source_tag, :owner)
                ON CONFLICT (scope_ref, hint_kind, hint_text_zh)
                DO UPDATE SET hint_text_en=EXCLUDED.hint_text_en,
                              severity=EXCLUDED.severity,
                              trigger_keywords=EXCLUDED.trigger_keywords,
                              source_tag=EXCLUDED.source_tag,
                              owner_username=EXCLUDED.owner_username,
                              updated_at=NOW()
            """), {**row, "trigger_keywords": json.dumps(row["trigger_keywords"]),
                    "source_tag": SOURCE_TAG, "owner": owner})
    invalidate_semantic_cache()
    return {"status": "ok", "hints": len(rows), "source_tag": SOURCE_TAG}


if __name__ == "__main__":
    from pathlib import Path
    from dotenv import load_dotenv

    # Keep the module CLI consistent with the other semantic publishers: the
    # control-database URL belongs to the project environment, not the shell.
    load_dotenv(str(Path(__file__).resolve().with_name(".env")), override=False)
    print(json.dumps(seed_semantic_hints_bird(), ensure_ascii=False))
