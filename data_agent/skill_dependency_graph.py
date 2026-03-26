"""Skill dependency graph — build, validate, and query skill dependency relationships."""

import logging
from collections import defaultdict, deque
from typing import Optional

from .db_engine import get_engine
from sqlalchemy import text

logger = logging.getLogger("data_agent.skill_dependency_graph")


def _load_skills_with_deps(username: str) -> dict:
    """Load all skills and their depends_on arrays for a user."""
    engine = get_engine()
    if not engine:
        return {}
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT id, skill_name, depends_on FROM agent_custom_skills "
                "WHERE owner_username = :u OR is_shared = TRUE"
            ), {"u": username}).fetchall()
            return {r.id: {"name": r.skill_name, "depends_on": list(r.depends_on or [])} for r in rows}
    except Exception as e:
        logger.warning("Failed to load skills: %s", e)
        return {}


def build_skill_graph(username: str) -> dict:
    """Build a dependency graph for all skills visible to a user.

    Returns:
        {
            "nodes": [{"id": int, "name": str, "depends_on": list[int]}],
            "edges": [{"from": int, "to": int}],
            "has_cycle": bool
        }
    """
    skills = _load_skills_with_deps(username)
    nodes = [{"id": sid, "name": info["name"], "depends_on": info["depends_on"]} for sid, info in skills.items()]
    edges = []
    for sid, info in skills.items():
        for dep_id in info["depends_on"]:
            if dep_id in skills:
                edges.append({"from": dep_id, "to": sid})

    cycle = _detect_cycle(skills)
    return {"nodes": nodes, "edges": edges, "has_cycle": cycle}


def _detect_cycle(skills: dict) -> bool:
    """Detect if there is a cycle in the dependency graph using Kahn's algorithm."""
    in_degree = defaultdict(int)
    adj = defaultdict(list)
    all_ids = set(skills.keys())

    for sid, info in skills.items():
        for dep in info["depends_on"]:
            if dep in all_ids:
                adj[dep].append(sid)
                in_degree[sid] += 1

    queue = deque(sid for sid in all_ids if in_degree[sid] == 0)
    visited = 0
    while queue:
        node = queue.popleft()
        visited += 1
        for neighbor in adj[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    return visited < len(all_ids)


def get_dependents(skill_id: int, username: str) -> list[int]:
    """Get all skills that depend on the given skill (reverse edges)."""
    skills = _load_skills_with_deps(username)
    return [sid for sid, info in skills.items() if skill_id in info["depends_on"]]


def get_dependencies(skill_id: int, username: str) -> list[int]:
    """Get all skills that the given skill depends on."""
    skills = _load_skills_with_deps(username)
    if skill_id in skills:
        return [d for d in skills[skill_id]["depends_on"] if d in skills]
    return []


def get_execution_order(skill_ids: list[int], username: str) -> list[list[int]]:
    """Topological sort of skill_ids into execution waves."""
    skills = _load_skills_with_deps(username)
    subset = {sid: skills[sid] for sid in skill_ids if sid in skills}

    in_degree = defaultdict(int)
    adj = defaultdict(list)

    for sid, info in subset.items():
        for dep in info["depends_on"]:
            if dep in subset:
                adj[dep].append(sid)
                in_degree[sid] += 1

    waves = []
    remaining = set(subset.keys())
    while remaining:
        wave = [sid for sid in remaining if in_degree[sid] == 0]
        if not wave:
            # Cycle detected, break with remaining
            waves.append(list(remaining))
            break
        waves.append(wave)
        for sid in wave:
            remaining.discard(sid)
            for neighbor in adj[sid]:
                in_degree[neighbor] -= 1

    return waves


def validate_dependency(skill_id: int, new_dep_id: int, username: str) -> dict:
    """Validate adding new_dep_id as a dependency of skill_id.

    Returns:
        {"valid": True} or {"valid": False, "reason": str}
    """
    if skill_id == new_dep_id:
        return {"valid": False, "reason": "技能不能依赖自身"}

    skills = _load_skills_with_deps(username)
    if new_dep_id not in skills:
        return {"valid": False, "reason": f"依赖技能 ID {new_dep_id} 不存在"}
    if skill_id not in skills:
        return {"valid": False, "reason": f"技能 ID {skill_id} 不存在"}

    # Simulate adding the dependency and check for cycles
    test_skills = {sid: {"name": info["name"], "depends_on": list(info["depends_on"])} for sid, info in skills.items()}
    if new_dep_id not in test_skills[skill_id]["depends_on"]:
        test_skills[skill_id]["depends_on"].append(new_dep_id)

    if _detect_cycle(test_skills):
        return {"valid": False, "reason": "添加此依赖会形成循环"}

    return {"valid": True}


def update_dependencies(skill_id: int, depends_on: list[int], username: str) -> dict:
    """Update the depends_on array for a skill after validation."""
    # Validate all dependencies
    skills = _load_skills_with_deps(username)
    if skill_id not in skills:
        return {"status": "error", "message": f"技能 {skill_id} 不存在"}

    # Check ownership
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库不可用"}

    # Simulate and check for cycles
    test_skills = {sid: {"name": info["name"], "depends_on": list(info["depends_on"])} for sid, info in skills.items()}
    test_skills[skill_id]["depends_on"] = depends_on
    if _detect_cycle(test_skills):
        return {"status": "error", "message": "依赖关系存在循环"}

    try:
        with engine.connect() as conn:
            conn.execute(text(
                "UPDATE agent_custom_skills SET depends_on = :deps WHERE id = :id AND owner_username = :u"
            ), {"deps": depends_on, "id": skill_id, "u": username})
            conn.commit()
        return {"status": "ok", "depends_on": depends_on}
    except Exception as e:
        logger.warning("Failed to update dependencies: %s", e)
        return {"status": "error", "message": str(e)}
