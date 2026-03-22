"""
Quality Rules — persistent governance rules + trend tracking (v14.5).

Users create quality rules linked to data standards. Rules can be executed
against datasets individually or in batch. Results are stored in the trends
table for historical analysis.
"""

import json
import logging
import os
from datetime import datetime, timezone

from sqlalchemy import text

from .db_engine import get_engine

logger = logging.getLogger(__name__)

T_QUALITY_RULES = "agent_quality_rules"
T_QUALITY_TRENDS = "agent_quality_trends"
T_DATA_CATALOG = "agent_data_catalog"

VALID_RULE_TYPES = {"field_check", "formula", "topology", "completeness", "custom"}
VALID_SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
MAX_RULES_PER_USER = 100

# ---------------------------------------------------------------------------
# Table init
# ---------------------------------------------------------------------------

def init_quality_tables():
    engine = get_engine()
    if not engine:
        return
    migrations_dir = os.path.join(os.path.dirname(__file__), "migrations")
    for fname in ("029_quality_rules.sql", "030_quality_trends.sql"):
        fpath = os.path.join(migrations_dir, fname)
        if os.path.isfile(fpath):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    sql = f.read()
                with engine.connect() as conn:
                    conn.execute(text(sql))
                    conn.commit()
            except Exception as e:
                logger.debug("Quality table init (%s): %s", fname, e)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def create_rule(rule_name: str, rule_type: str, config: dict,
                owner: str, standard_id: str = None,
                severity: str = "HIGH", is_shared: bool = False) -> dict:
    if not rule_name or len(rule_name) > 200:
        return {"status": "error", "message": "规则名称不能为空且不超过200字符"}
    if rule_type not in VALID_RULE_TYPES:
        return {"status": "error", "message": f"rule_type 必须是 {sorted(VALID_RULE_TYPES)} 之一"}
    if severity not in VALID_SEVERITIES:
        severity = "HIGH"
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库不可用"}
    try:
        with engine.connect() as conn:
            count = conn.execute(text(
                f"SELECT COUNT(*) FROM {T_QUALITY_RULES} WHERE owner_username = :o"
            ), {"o": owner}).scalar() or 0
            if count >= MAX_RULES_PER_USER:
                return {"status": "error", "message": f"每用户最多 {MAX_RULES_PER_USER} 条规则"}
            conn.execute(text(f"""
                INSERT INTO {T_QUALITY_RULES}
                (rule_name, rule_type, config, owner_username, standard_id, severity, is_shared)
                VALUES (:n, :t, :c, :o, :s, :sv, :sh)
            """), {"n": rule_name, "t": rule_type, "c": json.dumps(config, ensure_ascii=False),
                   "o": owner, "s": standard_id, "sv": severity, "sh": is_shared})
            conn.commit()
            rid = conn.execute(text(
                f"SELECT id FROM {T_QUALITY_RULES} WHERE rule_name = :n AND owner_username = :o"
            ), {"n": rule_name, "o": owner}).scalar()
        return {"status": "ok", "id": rid, "rule_name": rule_name}
    except Exception as e:
        logger.warning("create_rule failed: %s", e)
        return {"status": "error", "message": str(e)}


def list_rules(owner: str, include_shared: bool = True) -> list:
    engine = get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            if include_shared:
                rows = conn.execute(text(f"""
                    SELECT * FROM {T_QUALITY_RULES}
                    WHERE owner_username = :o OR is_shared = true
                    ORDER BY created_at DESC
                """), {"o": owner}).fetchall()
            else:
                rows = conn.execute(text(f"""
                    SELECT * FROM {T_QUALITY_RULES} WHERE owner_username = :o
                    ORDER BY created_at DESC
                """), {"o": owner}).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception as e:
        logger.warning("list_rules failed: %s", e)
        return []


def get_rule(rule_id: int, owner: str) -> dict:
    engine = get_engine()
    if not engine:
        return {}
    try:
        with engine.connect() as conn:
            row = conn.execute(text(f"""
                SELECT * FROM {T_QUALITY_RULES}
                WHERE id = :id AND (owner_username = :o OR is_shared = true)
            """), {"id": rule_id, "o": owner}).fetchone()
        return dict(row._mapping) if row else {}
    except Exception:
        return {}


def update_rule(rule_id: int, owner: str, **kwargs) -> dict:
    allowed = {"rule_name", "rule_type", "config", "standard_id", "severity", "enabled", "is_shared"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return {"status": "error", "message": "无可更新字段"}
    if "config" in updates and isinstance(updates["config"], dict):
        updates["config"] = json.dumps(updates["config"], ensure_ascii=False)
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库不可用"}
    try:
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        updates["id"] = rule_id
        updates["o"] = owner
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                UPDATE {T_QUALITY_RULES} SET {set_clause}, updated_at = NOW()
                WHERE id = :id AND owner_username = :o
            """), updates)
            conn.commit()
            if result.rowcount == 0:
                return {"status": "error", "message": "规则未找到或无权限"}
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def delete_rule(rule_id: int, owner: str) -> dict:
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库不可用"}
    try:
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                DELETE FROM {T_QUALITY_RULES} WHERE id = :id AND owner_username = :o
            """), {"id": rule_id, "o": owner})
            conn.commit()
            if result.rowcount == 0:
                return {"status": "error", "message": "规则未找到"}
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# Rule execution
# ---------------------------------------------------------------------------

def execute_rule(rule: dict, file_path: str) -> dict:
    """Execute a single quality rule against a file."""
    rule_type = rule.get("rule_type", "")
    config = rule.get("config", {})
    if isinstance(config, str):
        config = json.loads(config)

    try:
        if rule_type == "field_check":
            from .gis_processors import check_field_standards
            std_id = config.get("standard_id") or rule.get("standard_id", "")
            return check_field_standards(file_path, std_id)

        elif rule_type == "formula":
            from .toolsets.governance_tools import validate_field_formulas
            std_id = config.get("standard_id") or rule.get("standard_id", "")
            result_str = validate_field_formulas(file_path, standard_id=std_id)
            return json.loads(result_str)

        elif rule_type == "topology":
            from .gis_processors import check_topology
            return check_topology(file_path)

        elif rule_type == "completeness":
            from .toolsets.governance_tools import check_completeness
            return check_completeness(file_path)

        else:
            return {"status": "error", "message": f"不支持的规则类型: {rule_type}"}

    except Exception as e:
        return {"status": "error", "message": str(e)}


def execute_rules_batch(file_path: str, rule_ids: list = None, owner: str = "") -> dict:
    """Execute multiple rules against a file and return aggregate results."""
    rules = list_rules(owner, include_shared=True)
    if rule_ids:
        rules = [r for r in rules if r["id"] in rule_ids]
    rules = [r for r in rules if r.get("enabled", True)]

    results = []
    total_issues = 0
    for rule in rules:
        result = execute_rule(rule, file_path)
        passed = result.get("is_standard", True) and result.get("status") != "error"
        issue_count = len(result.get("missing_fields", [])) + len(result.get("invalid_values", []))
        total_issues += issue_count
        results.append({
            "rule_id": rule["id"],
            "rule_name": rule["rule_name"],
            "rule_type": rule["rule_type"],
            "severity": rule.get("severity", "HIGH"),
            "passed": passed,
            "issues": issue_count,
            "detail": result,
        })

    passed_count = sum(1 for r in results if r["passed"])
    return {
        "status": "ok",
        "file": file_path,
        "total_rules": len(results),
        "passed": passed_count,
        "failed": len(results) - passed_count,
        "total_issues": total_issues,
        "pass_rate": round(passed_count / len(results) * 100, 1) if results else 100.0,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Trend tracking
# ---------------------------------------------------------------------------

def record_trend(asset_name: str, standard_id: str, score: float,
                 dimension_scores: dict, issues_count: int,
                 rule_results: dict, run_by: str) -> dict:
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库不可用"}
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                INSERT INTO {T_QUALITY_TRENDS}
                (asset_name, standard_id, score, dimension_scores, issues_count, rule_results, run_by)
                VALUES (:a, :s, :sc, :ds, :ic, :rr, :rb)
            """), {
                "a": asset_name, "s": standard_id, "sc": score,
                "ds": json.dumps(dimension_scores, ensure_ascii=False),
                "ic": issues_count,
                "rr": json.dumps(rule_results, ensure_ascii=False, default=str),
                "rb": run_by,
            })
            conn.commit()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_trends(asset_name: str = None, days: int = 30) -> list:
    engine = get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            if asset_name:
                rows = conn.execute(text(f"""
                    SELECT * FROM {T_QUALITY_TRENDS}
                    WHERE asset_name = :a AND created_at >= NOW() - INTERVAL '{int(days)} days'
                    ORDER BY created_at DESC LIMIT 200
                """), {"a": asset_name}).fetchall()
            else:
                rows = conn.execute(text(f"""
                    SELECT * FROM {T_QUALITY_TRENDS}
                    WHERE created_at >= NOW() - INTERVAL '{int(days)} days'
                    ORDER BY created_at DESC LIMIT 200
                """)).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception as e:
        logger.warning("get_trends failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# Resource overview
# ---------------------------------------------------------------------------

def get_resource_overview(owner: str = None) -> dict:
    """Aggregate data resource statistics for the overview dashboard."""
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库不可用"}
    try:
        with engine.connect() as conn:
            # Asset counts by type
            asset_rows = conn.execute(text(f"""
                SELECT asset_type, COUNT(*) as cnt
                FROM {T_DATA_CATALOG}
                GROUP BY asset_type
            """)).fetchall()
            type_dist = {r._mapping["asset_type"]: r._mapping["cnt"] for r in asset_rows}
            total_assets = sum(type_dist.values())

            # Total rules
            rule_count = conn.execute(text(
                f"SELECT COUNT(*) FROM {T_QUALITY_RULES}"
            )).scalar() or 0

            enabled_rules = conn.execute(text(
                f"SELECT COUNT(*) FROM {T_QUALITY_RULES} WHERE enabled = true"
            )).scalar() or 0

            # Recent quality scores (last 10)
            recent = conn.execute(text(f"""
                SELECT asset_name, score, created_at
                FROM {T_QUALITY_TRENDS}
                ORDER BY created_at DESC LIMIT 10
            """)).fetchall()
            recent_scores = [
                {"asset": r._mapping["asset_name"], "score": float(r._mapping["score"] or 0),
                 "date": str(r._mapping["created_at"])}
                for r in recent
            ]

        return {
            "status": "ok",
            "total_assets": total_assets,
            "type_distribution": type_dist,
            "total_rules": rule_count,
            "enabled_rules": enabled_rules,
            "recent_scores": recent_scores,
        }
    except Exception as e:
        logger.warning("get_resource_overview failed: %s", e)
        return {"status": "error", "message": str(e)}
