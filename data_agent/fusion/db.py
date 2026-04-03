"""Database recording for fusion operations."""
import json
from typing import Optional

from sqlalchemy import text

from ..db_engine import get_engine
from ..user_context import current_user_id
from .models import FusionSource
from .constants import T_FUSION_OPS


def ensure_fusion_tables():
    """Create fusion operations table if not exists. Called at startup."""
    engine = get_engine()
    if not engine:
        return

    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_FUSION_OPS} (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(100) NOT NULL,
                    source_files JSONB NOT NULL DEFAULT '[]'::jsonb,
                    strategy VARCHAR(50) NOT NULL,
                    parameters JSONB DEFAULT '{{}}'::jsonb,
                    output_file TEXT,
                    quality_score FLOAT,
                    quality_report JSONB DEFAULT '{{}}'::jsonb,
                    duration_s FLOAT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_fusion_ops_user "
                f"ON {T_FUSION_OPS} (username)"
            ))
            conn.commit()
    except Exception as e:
        print(f"[Fusion] WARNING: Failed to create tables: {e}")


def record_operation(
    sources: list[FusionSource],
    strategy: str,
    output_path: str,
    quality_score: float,
    quality_warnings: list[str],
    duration_s: float,
    params: Optional[dict] = None,
    temporal_log: Optional[str] = None,
    semantic_log: Optional[str] = None,
    conflict_log: Optional[str] = None,
    explainability_metadata: Optional[dict] = None,
) -> None:
    """Record a fusion operation to the database."""
    engine = get_engine()
    if not engine:
        return

    try:
        username = current_user_id.get()
        with engine.connect() as conn:
            conn.execute(text(f"""
                INSERT INTO {T_FUSION_OPS}
                (username, source_files, strategy, parameters, output_file,
                 quality_score, quality_report, duration_s,
                 temporal_alignment_log, semantic_enhancement_log,
                 conflict_resolution_log, explainability_metadata)
                VALUES (:username, :sources, :strategy, :params, :output,
                        :quality, :report, :duration,
                        :temporal_log, :semantic_log,
                        :conflict_log, :explain_meta)
            """), {
                "username": username,
                "sources": json.dumps([s.file_path for s in sources]),
                "strategy": strategy,
                "params": json.dumps(params or {}),
                "output": output_path,
                "quality": quality_score,
                "report": json.dumps({"warnings": quality_warnings}),
                "duration": duration_s,
                "temporal_log": temporal_log,
                "semantic_log": semantic_log,
                "conflict_log": conflict_log,
                "explain_meta": json.dumps(explainability_metadata) if explainability_metadata else None,
            })
            conn.commit()
    except Exception as e:
        print(f"[Fusion] WARNING: Failed to record operation: {e}")
