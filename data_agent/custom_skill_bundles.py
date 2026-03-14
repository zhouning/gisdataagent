"""
Custom Skill Bundles — DB-driven user-defined toolset compositions (v10.0.2).

Users can compose named bundles of toolsets + ADK Skills for reuse.
Bundles are stored in PostgreSQL with owner isolation and optional sharing.

All DB operations are non-fatal (never raise to caller).
"""
import re
from typing import Optional

from sqlalchemy import text

from .db_engine import get_engine
from .user_context import current_user_id

try:
    from .observability import get_logger
    logger = get_logger("custom_skill_bundles")
except Exception:
    import logging
    logger = logging.getLogger("custom_skill_bundles")


T_SKILL_BUNDLES = "agent_skill_bundles"
MAX_BUNDLES_PER_USER = 30

# Audit action constants
ACTION_BUNDLE_CREATE = "bundle_create"
ACTION_BUNDLE_UPDATE = "bundle_update"
ACTION_BUNDLE_DELETE = "bundle_delete"

# ---------------------------------------------------------------------------
# ADK Skills directory listing (for validation)
# ---------------------------------------------------------------------------

_ADK_SKILL_NAMES: set[str] | None = None


def _get_adk_skill_names() -> set[str]:
    """List valid ADK skill directory names under data_agent/skills/."""
    global _ADK_SKILL_NAMES
    if _ADK_SKILL_NAMES is not None:
        return _ADK_SKILL_NAMES
    import os
    skills_dir = os.path.join(os.path.dirname(__file__), "skills")
    if not os.path.isdir(skills_dir):
        _ADK_SKILL_NAMES = set()
        return _ADK_SKILL_NAMES
    _ADK_SKILL_NAMES = {
        d for d in os.listdir(skills_dir)
        if os.path.isdir(os.path.join(skills_dir, d)) and not d.startswith("_")
    }
    return _ADK_SKILL_NAMES


# ---------------------------------------------------------------------------
# Table management
# ---------------------------------------------------------------------------

def ensure_skill_bundles_table() -> bool:
    """Create agent_skill_bundles table if not exists."""
    engine = get_engine()
    if not engine:
        return False
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_SKILL_BUNDLES} (
                    id SERIAL PRIMARY KEY,
                    owner_username VARCHAR(100) NOT NULL,
                    bundle_name VARCHAR(100) NOT NULL,
                    description TEXT DEFAULT '',
                    toolset_names TEXT[] DEFAULT '{{}}'::text[],
                    skill_names TEXT[] DEFAULT '{{}}'::text[],
                    intent_triggers TEXT[] DEFAULT '{{}}'::text[],
                    is_shared BOOLEAN DEFAULT FALSE,
                    enabled BOOLEAN DEFAULT TRUE,
                    use_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(owner_username, bundle_name)
                )
            """))
            conn.commit()
        return True
    except Exception as e:
        logger.warning("Failed to create skill_bundles table: %s", e)
        return False


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_bundle_name(name: str) -> Optional[str]:
    """Validate bundle name. Returns error message or None."""
    if not name or not name.strip():
        return "Bundle name is required"
    if len(name) > 100:
        return "Bundle name must be 100 characters or less"
    if not re.match(r'^[\w\u4e00-\u9fff\-]+$', name):
        return "Bundle name can only contain letters, numbers, Chinese, hyphens"
    return None


def validate_toolset_names(names: list[str]) -> Optional[str]:
    """Validate toolset names against known toolsets. Returns error or None."""
    from .custom_skills import TOOLSET_NAMES
    for name in names:
        if name not in TOOLSET_NAMES:
            return f"Unknown toolset: '{name}'. Valid: {sorted(TOOLSET_NAMES)}"
    return None


def validate_skill_names(names: list[str]) -> Optional[str]:
    """Validate ADK skill names against skills directory. Returns error or None."""
    valid = _get_adk_skill_names()
    for name in names:
        if name not in valid:
            return f"Unknown skill: '{name}'. Valid: {sorted(valid)}"
    return None


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def _row_to_dict(row) -> dict:
    """Convert a DB row to a dict."""
    return {
        "id": row[0],
        "owner_username": row[1],
        "bundle_name": row[2],
        "description": row[3] or "",
        "toolset_names": row[4] or [],
        "skill_names": row[5] or [],
        "intent_triggers": row[6] or [],
        "is_shared": bool(row[7]) if row[7] is not None else False,
        "enabled": bool(row[8]) if row[8] is not None else True,
        "use_count": row[9] or 0,
        "created_at": str(row[10]) if row[10] else None,
        "updated_at": str(row[11]) if row[11] else None,
    }


def create_skill_bundle(
    bundle_name: str,
    description: str = "",
    toolset_names: list[str] = None,
    skill_names: list[str] = None,
    intent_triggers: list[str] = None,
    is_shared: bool = False,
) -> Optional[int]:
    """Create a new skill bundle. Returns bundle ID or None."""
    owner = current_user_id.get("")
    if not owner:
        return None

    # Validate
    err = validate_bundle_name(bundle_name)
    if err:
        logger.warning("Bundle name validation failed: %s", err)
        return None

    toolset_names = toolset_names or []
    skill_names = skill_names or []
    intent_triggers = intent_triggers or []

    if toolset_names:
        err = validate_toolset_names(toolset_names)
        if err:
            logger.warning("Toolset validation failed: %s", err)
            return None

    if skill_names:
        err = validate_skill_names(skill_names)
        if err:
            logger.warning("Skill validation failed: %s", err)
            return None

    if not toolset_names and not skill_names:
        logger.warning("Bundle must include at least one toolset or skill")
        return None

    engine = get_engine()
    if not engine:
        return None

    try:
        with engine.connect() as conn:
            # Check quota
            count = conn.execute(text(
                f"SELECT COUNT(*) FROM {T_SKILL_BUNDLES} WHERE owner_username = :owner"
            ), {"owner": owner}).scalar()
            if count and count >= MAX_BUNDLES_PER_USER:
                logger.warning("Bundle quota exceeded for user %s", owner)
                return None

            result = conn.execute(text(f"""
                INSERT INTO {T_SKILL_BUNDLES}
                    (owner_username, bundle_name, description, toolset_names,
                     skill_names, intent_triggers, is_shared)
                VALUES (:owner, :name, :desc, :toolsets, :skills, :triggers, :shared)
                RETURNING id
            """), {
                "owner": owner,
                "name": bundle_name,
                "desc": description,
                "toolsets": toolset_names,
                "skills": skill_names,
                "triggers": intent_triggers,
                "shared": is_shared,
            })
            bundle_id = result.scalar()
            conn.commit()
        return bundle_id
    except Exception as e:
        logger.warning("Failed to create bundle: %s", e)
        return None


def list_skill_bundles(include_shared: bool = True) -> list[dict]:
    """List bundles visible to current user (own + shared)."""
    owner = current_user_id.get("")
    engine = get_engine()
    if not engine:
        return []

    try:
        with engine.connect() as conn:
            if include_shared and owner:
                rows = conn.execute(text(
                    f"SELECT id, owner_username, bundle_name, description, "
                    f"toolset_names, skill_names, intent_triggers, is_shared, "
                    f"enabled, use_count, created_at, updated_at "
                    f"FROM {T_SKILL_BUNDLES} "
                    f"WHERE (owner_username = :owner OR is_shared = TRUE) AND enabled = TRUE "
                    f"ORDER BY bundle_name"
                ), {"owner": owner}).fetchall()
            elif owner:
                rows = conn.execute(text(
                    f"SELECT id, owner_username, bundle_name, description, "
                    f"toolset_names, skill_names, intent_triggers, is_shared, "
                    f"enabled, use_count, created_at, updated_at "
                    f"FROM {T_SKILL_BUNDLES} "
                    f"WHERE owner_username = :owner AND enabled = TRUE "
                    f"ORDER BY bundle_name"
                ), {"owner": owner}).fetchall()
            else:
                return []
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        logger.warning("Failed to list bundles: %s", e)
        return []


def get_skill_bundle(bundle_id: int) -> Optional[dict]:
    """Get a single bundle by ID (owner or shared)."""
    owner = current_user_id.get("")
    engine = get_engine()
    if not engine:
        return None

    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                f"SELECT id, owner_username, bundle_name, description, "
                f"toolset_names, skill_names, intent_triggers, is_shared, "
                f"enabled, use_count, created_at, updated_at "
                f"FROM {T_SKILL_BUNDLES} "
                f"WHERE id = :id AND (owner_username = :owner OR is_shared = TRUE)"
            ), {"id": bundle_id, "owner": owner}).fetchone()
        return _row_to_dict(row) if row else None
    except Exception as e:
        logger.warning("Failed to get bundle %s: %s", bundle_id, e)
        return None


def update_skill_bundle(bundle_id: int, **fields) -> bool:
    """Update a bundle (owner only). Returns success."""
    owner = current_user_id.get("")
    if not owner:
        return False

    allowed = {"description", "toolset_names", "skill_names", "intent_triggers",
               "is_shared", "enabled", "bundle_name"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False

    if "bundle_name" in updates:
        err = validate_bundle_name(updates["bundle_name"])
        if err:
            return False
    if "toolset_names" in updates:
        err = validate_toolset_names(updates["toolset_names"])
        if err:
            return False
    if "skill_names" in updates:
        err = validate_skill_names(updates["skill_names"])
        if err:
            return False

    engine = get_engine()
    if not engine:
        return False

    try:
        set_parts = []
        params = {"id": bundle_id, "owner": owner}
        for k, v in updates.items():
            set_parts.append(f"{k} = :{k}")
            params[k] = v
        set_parts.append("updated_at = NOW()")
        set_clause = ", ".join(set_parts)

        with engine.connect() as conn:
            result = conn.execute(text(
                f"UPDATE {T_SKILL_BUNDLES} SET {set_clause} "
                f"WHERE id = :id AND owner_username = :owner"
            ), params)
            conn.commit()
        return result.rowcount > 0
    except Exception as e:
        logger.warning("Failed to update bundle %s: %s", bundle_id, e)
        return False


def delete_skill_bundle(bundle_id: int) -> bool:
    """Delete a bundle (owner only). Returns success."""
    owner = current_user_id.get("")
    if not owner:
        return False

    engine = get_engine()
    if not engine:
        return False

    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                f"DELETE FROM {T_SKILL_BUNDLES} WHERE id = :id AND owner_username = :owner"
            ), {"id": bundle_id, "owner": owner})
            conn.commit()
        return result.rowcount > 0
    except Exception as e:
        logger.warning("Failed to delete bundle %s: %s", bundle_id, e)
        return False


def increment_use_count(bundle_id: int):
    """Atomically increment bundle use counter."""
    engine = get_engine()
    if not engine:
        return
    try:
        with engine.connect() as conn:
            conn.execute(text(
                f"UPDATE {T_SKILL_BUNDLES} SET use_count = use_count + 1 WHERE id = :id"
            ), {"id": bundle_id})
            conn.commit()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def find_bundle_by_trigger(user_text: str) -> Optional[dict]:
    """Find a user bundle whose trigger keywords match the input text."""
    bundles = list_skill_bundles()
    if not bundles:
        return None

    text_lower = user_text.lower()
    for b in bundles:
        for kw in b.get("intent_triggers", []):
            if kw.lower() in text_lower:
                return b
    return None


def find_bundle_by_name(name: str) -> Optional[dict]:
    """Find a bundle by exact name (case-insensitive)."""
    bundles = list_skill_bundles()
    if not bundles:
        return None

    name_lower = name.lower()
    for b in bundles:
        if b["bundle_name"].lower() == name_lower:
            return b
    return None


# ---------------------------------------------------------------------------
# Factory — build toolsets from a bundle
# ---------------------------------------------------------------------------

def build_toolsets_from_bundle(bundle: dict) -> list:
    """Instantiate BaseToolset instances from a bundle's toolset_names + skill_names."""
    from .custom_skills import _get_toolset_registry

    registry = _get_toolset_registry()
    toolsets = []

    # Instantiate toolsets
    for name in bundle.get("toolset_names", []):
        cls = registry.get(name)
        if cls:
            try:
                toolsets.append(cls())
            except Exception as e:
                logger.warning("Failed to instantiate toolset %s: %s", name, e)

    # Load ADK skills as SkillToolset
    skill_names = bundle.get("skill_names", [])
    if skill_names:
        try:
            from .toolsets.skill_bundles import build_skill_toolset
            for sname in skill_names:
                ts = build_skill_toolset(sname)
                if ts:
                    toolsets.append(ts)
        except Exception as e:
            logger.warning("Failed to load skills: %s", e)

    return toolsets


def get_available_tools() -> dict:
    """Return lists of available toolset names and ADK skill names for bundle composition."""
    from .custom_skills import TOOLSET_NAMES
    return {
        "toolset_names": sorted(TOOLSET_NAMES),
        "skill_names": sorted(_get_adk_skill_names()),
    }
