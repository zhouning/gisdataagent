"""
Proactive Explorer — background data monitoring + analysis suggestions (v11.0.3).

Monitors user upload directories, auto-profiles spatial data files,
and generates analysis suggestions using LLM.

All operations are non-fatal (never raise to caller).
"""
import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy import text

from .db_engine import get_engine
from .user_context import current_user_id

try:
    from .observability import get_logger
    logger = get_logger("proactive_explorer")
except Exception:
    import logging
    logger = logging.getLogger("proactive_explorer")


T_OBSERVATIONS = "agent_proactive_observations"
PROACTIVE_ENABLED = os.environ.get("PROACTIVE_ENABLED", "true").lower() == "true"
SCAN_INTERVAL = int(os.environ.get("PROACTIVE_SCAN_INTERVAL", "300"))  # seconds
MAX_SUGGESTIONS_PER_USER = 20
SPATIAL_EXTENSIONS = {".shp", ".geojson", ".gpkg", ".kml", ".kmz", ".csv", ".xlsx"}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AnalysisSuggestion:
    """A single analysis suggestion."""
    suggestion_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    title: str = ""
    description: str = ""
    pipeline_type: str = "general"
    prompt_template: str = ""
    relevance_score: float = 0.5
    category: str = "analysis"  # quality, pattern, optimization, visualization

    def to_dict(self) -> dict:
        return {
            "suggestion_id": self.suggestion_id,
            "title": self.title,
            "description": self.description,
            "pipeline_type": self.pipeline_type,
            "prompt_template": self.prompt_template,
            "relevance_score": round(self.relevance_score, 2),
            "category": self.category,
        }


@dataclass
class DataObservation:
    """An observation from profiling a data file."""
    observation_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    user_id: str = ""
    file_path: str = ""
    file_hash: str = ""
    data_profile: dict = field(default_factory=dict)
    suggestions: list[AnalysisSuggestion] = field(default_factory=list)
    dismissed: bool = False
    created_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "observation_id": self.observation_id,
            "user_id": self.user_id,
            "file_path": self.file_path,
            "data_profile": self.data_profile,
            "suggestions": [s.to_dict() for s in self.suggestions],
            "dismissed": self.dismissed,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Table management
# ---------------------------------------------------------------------------

def ensure_observations_table() -> bool:
    engine = get_engine()
    if not engine:
        return False
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_OBSERVATIONS} (
                    id SERIAL PRIMARY KEY,
                    observation_id VARCHAR(36) UNIQUE NOT NULL,
                    user_id VARCHAR(100) NOT NULL,
                    file_path TEXT NOT NULL,
                    file_hash VARCHAR(64),
                    data_profile JSONB DEFAULT '{{}}'::jsonb,
                    suggestions JSONB DEFAULT '[]'::jsonb,
                    dismissed BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.commit()
        return True
    except Exception as e:
        logger.warning("Failed to create observations table: %s", e)
        return False


# ---------------------------------------------------------------------------
# File profiling
# ---------------------------------------------------------------------------

def _compute_file_hash(file_path: str) -> str:
    """Compute SHA-256 hash of a file (first 1MB for large files)."""
    try:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            chunk = f.read(1024 * 1024)  # first 1MB
            h.update(chunk)
        return h.hexdigest()[:16]
    except Exception:
        return ""


def _is_already_profiled(user_id: str, file_hash: str) -> bool:
    """Check if a file with this hash was already profiled for this user."""
    engine = get_engine()
    if not engine or not file_hash:
        return False
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                f"SELECT 1 FROM {T_OBSERVATIONS} "
                f"WHERE user_id = :uid AND file_hash = :hash LIMIT 1"
            ), {"uid": user_id, "hash": file_hash}).fetchone()
        return row is not None
    except Exception:
        return False


def profile_file(file_path: str) -> dict:
    """Profile a spatial data file. Returns a profile dict."""
    ext = os.path.splitext(file_path)[1].lower()
    profile = {
        "file_name": os.path.basename(file_path),
        "file_size": os.path.getsize(file_path) if os.path.exists(file_path) else 0,
        "extension": ext,
    }

    try:
        if ext in (".shp", ".geojson", ".gpkg", ".kml"):
            import geopandas as gpd
            gdf = gpd.read_file(file_path)
            profile["row_count"] = len(gdf)
            profile["columns"] = list(gdf.columns)
            profile["geometry_types"] = list(gdf.geom_type.unique()) if "geometry" in gdf.columns else []
            profile["crs"] = str(gdf.crs) if gdf.crs else None
            # Numeric column stats
            numeric_cols = gdf.select_dtypes(include="number").columns.tolist()
            if numeric_cols:
                profile["numeric_columns"] = numeric_cols
                profile["null_rates"] = {c: round(gdf[c].isna().mean(), 3) for c in numeric_cols[:5]}

        elif ext == ".csv":
            import pandas as pd
            df = pd.read_csv(file_path, nrows=1000)
            profile["row_count"] = len(df)
            profile["columns"] = list(df.columns)
            # Check for coordinate columns
            coord_cols = [c for c in df.columns if c.lower() in
                         ("lng", "lon", "longitude", "x", "lat", "latitude", "y", "经度", "纬度")]
            profile["has_coordinates"] = len(coord_cols) >= 2
            profile["coordinate_columns"] = coord_cols

        elif ext == ".xlsx":
            import pandas as pd
            df = pd.read_excel(file_path, nrows=1000)
            profile["row_count"] = len(df)
            profile["columns"] = list(df.columns)

    except Exception as e:
        profile["error"] = str(e)[:200]

    return profile


# ---------------------------------------------------------------------------
# Suggestion generation
# ---------------------------------------------------------------------------

_SUGGESTION_TEMPLATES = [
    {
        "condition": lambda p: p.get("geometry_types") and "Polygon" in str(p.get("geometry_types", [])),
        "suggestion": AnalysisSuggestion(
            title="空间自相关分析",
            description="对多边形数据执行 Moran's I 空间自相关检验，发现空间聚类模式",
            pipeline_type="general",
            prompt_template="请对 {file} 执行空间自相关分析 (Moran's I)",
            relevance_score=0.8, category="pattern",
        ),
    },
    {
        "condition": lambda p: p.get("geometry_types") and "Point" in str(p.get("geometry_types", [])),
        "suggestion": AnalysisSuggestion(
            title="热点分析",
            description="对点数据执行 Getis-Ord Gi* 热点分析，识别统计显著的热/冷点",
            pipeline_type="general",
            prompt_template="请对 {file} 执行热点分析 (Getis-Ord Gi*)",
            relevance_score=0.85, category="pattern",
        ),
    },
    {
        "condition": lambda p: p.get("row_count", 0) > 100 and p.get("geometry_types"),
        "suggestion": AnalysisSuggestion(
            title="数据质量审计",
            description="对空间数据执行拓扑检查、属性完整性验证和规范符合性审计",
            pipeline_type="governance",
            prompt_template="请对 {file} 执行全面的数据质量审计",
            relevance_score=0.7, category="quality",
        ),
    },
    {
        "condition": lambda p: p.get("has_coordinates"),
        "suggestion": AnalysisSuggestion(
            title="空间可视化",
            description="将CSV坐标数据可视化为交互式地图",
            pipeline_type="general",
            prompt_template="请将 {file} 中的坐标数据可视化到地图上",
            relevance_score=0.75, category="visualization",
        ),
    },
    {
        "condition": lambda p: p.get("numeric_columns") and len(p.get("numeric_columns", [])) >= 2,
        "suggestion": AnalysisSuggestion(
            title="IDW 空间插值",
            description="使用反距离加权法对数值属性进行空间插值",
            pipeline_type="general",
            prompt_template="请对 {file} 的数值列执行 IDW 空间插值分析",
            relevance_score=0.65, category="analysis",
        ),
    },
]


def generate_suggestions(profile: dict, file_path: str) -> list[AnalysisSuggestion]:
    """Generate analysis suggestions based on data profile."""
    suggestions = []
    file_name = os.path.basename(file_path)

    for template in _SUGGESTION_TEMPLATES:
        try:
            if template["condition"](profile):
                suggestion = AnalysisSuggestion(
                    title=template["suggestion"].title,
                    description=template["suggestion"].description,
                    pipeline_type=template["suggestion"].pipeline_type,
                    prompt_template=template["suggestion"].prompt_template.replace("{file}", file_name),
                    relevance_score=template["suggestion"].relevance_score,
                    category=template["suggestion"].category,
                )
                suggestions.append(suggestion)
        except Exception:
            continue

    # Sort by relevance score
    suggestions.sort(key=lambda s: s.relevance_score, reverse=True)
    return suggestions[:5]  # max 5 suggestions per file


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def save_observation(obs: DataObservation) -> bool:
    """Save an observation to DB."""
    engine = get_engine()
    if not engine:
        return False
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                INSERT INTO {T_OBSERVATIONS}
                    (observation_id, user_id, file_path, file_hash, data_profile, suggestions)
                VALUES (:oid, :uid, :fp, :fh, CAST(:profile AS jsonb), CAST(:suggestions AS jsonb))
                ON CONFLICT (observation_id) DO NOTHING
            """), {
                "oid": obs.observation_id,
                "uid": obs.user_id,
                "fp": obs.file_path,
                "fh": obs.file_hash,
                "profile": json.dumps(obs.data_profile),
                "suggestions": json.dumps([s.to_dict() for s in obs.suggestions]),
            })
            conn.commit()
        return True
    except Exception as e:
        logger.warning("Failed to save observation: %s", e)
        return False


def get_suggestions(user_id: str, include_dismissed: bool = False) -> list[dict]:
    """Get pending suggestions for a user."""
    engine = get_engine()
    if not engine:
        return []
    try:
        where = "WHERE user_id = :uid"
        if not include_dismissed:
            where += " AND dismissed = FALSE"

        with engine.connect() as conn:
            rows = conn.execute(text(
                f"SELECT observation_id, file_path, suggestions, dismissed, created_at "
                f"FROM {T_OBSERVATIONS} {where} ORDER BY created_at DESC LIMIT 50"
            ), {"uid": user_id}).fetchall()

        results = []
        for r in rows:
            suggestions_data = r[2] if isinstance(r[2], list) else json.loads(r[2]) if r[2] else []
            results.append({
                "observation_id": r[0],
                "file_path": r[1],
                "suggestions": suggestions_data,
                "dismissed": bool(r[3]),
                "created_at": str(r[4]) if r[4] else None,
            })
        return results
    except Exception as e:
        logger.warning("Failed to get suggestions: %s", e)
        return []


def dismiss_suggestion(observation_id: str) -> bool:
    """Dismiss an observation's suggestions."""
    engine = get_engine()
    if not engine:
        return False
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                f"UPDATE {T_OBSERVATIONS} SET dismissed = TRUE "
                f"WHERE observation_id = :oid"
            ), {"oid": observation_id})
            conn.commit()
        return result.rowcount > 0
    except Exception as e:
        logger.warning("Failed to dismiss suggestion: %s", e)
        return False


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

def scan_user_uploads(user_id: str, uploads_dir: str = None) -> list[DataObservation]:
    """Scan a user's upload directory for new files and generate suggestions."""
    if not uploads_dir:
        uploads_dir = os.path.join(os.path.dirname(__file__), "uploads", user_id)
    if not os.path.isdir(uploads_dir):
        return []

    observations = []
    scanned = 0

    for fname in os.listdir(uploads_dir):
        ext = os.path.splitext(fname)[1].lower()
        if ext not in SPATIAL_EXTENSIONS:
            continue

        file_path = os.path.join(uploads_dir, fname)
        file_hash = _compute_file_hash(file_path)

        if _is_already_profiled(user_id, file_hash):
            continue

        # Profile the file
        profile = profile_file(file_path)
        if profile.get("error"):
            continue

        # Generate suggestions
        suggestions = generate_suggestions(profile, file_path)
        if not suggestions:
            continue

        obs = DataObservation(
            user_id=user_id,
            file_path=file_path,
            file_hash=file_hash,
            data_profile=profile,
            suggestions=suggestions,
        )
        save_observation(obs)
        observations.append(obs)

        scanned += 1
        if scanned >= 3:  # max 3 per scan cycle
            break

    return observations
