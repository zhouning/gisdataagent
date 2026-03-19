"""
Workflow Templates — pre-built workflow definitions for cloning and reuse (v10.0.4).

Users can publish workflows as templates; others can browse, clone, and rate.
Admin or power users can also seed built-in templates.

All DB operations are non-fatal (never raise to caller).
"""
import json
from typing import Optional

from sqlalchemy import text

from .db_engine import get_engine
from .user_context import current_user_id

try:
    from .observability import get_logger
    logger = get_logger("workflow_templates")
except Exception:
    import logging
    logger = logging.getLogger("workflow_templates")


T_WORKFLOW_TEMPLATES = "agent_workflow_templates"


# ---------------------------------------------------------------------------
# Table management
# ---------------------------------------------------------------------------

def ensure_workflow_template_tables() -> bool:
    """Create agent_workflow_templates table if not exists."""
    engine = get_engine()
    if not engine:
        return False
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_WORKFLOW_TEMPLATES} (
                    id SERIAL PRIMARY KEY,
                    template_name VARCHAR(200) NOT NULL,
                    description TEXT DEFAULT '',
                    category VARCHAR(50) DEFAULT 'general',
                    author_username VARCHAR(100) NOT NULL,
                    pipeline_type VARCHAR(30) DEFAULT 'general',
                    steps JSONB NOT NULL,
                    default_parameters JSONB DEFAULT '{{}}'::jsonb,
                    tags TEXT[] DEFAULT '{{}}'::text[],
                    is_published BOOLEAN DEFAULT FALSE,
                    clone_count INTEGER DEFAULT 0,
                    rating_sum INTEGER DEFAULT 0,
                    rating_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.commit()
        return True
    except Exception as e:
        logger.warning("Failed to create workflow_templates table: %s", e)
        return False


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def _row_to_dict(row) -> dict:
    return {
        "id": row[0],
        "template_name": row[1],
        "description": row[2] or "",
        "category": row[3] or "general",
        "author_username": row[4],
        "pipeline_type": row[5] or "general",
        "steps": row[6] if isinstance(row[6], (list, dict)) else json.loads(row[6]) if row[6] else [],
        "default_parameters": row[7] if isinstance(row[7], dict) else json.loads(row[7]) if row[7] else {},
        "tags": row[8] or [],
        "is_published": bool(row[9]) if row[9] is not None else False,
        "clone_count": row[10] or 0,
        "rating_avg": round(row[11] / max(row[12], 1), 1) if row[12] else 0,
        "rating_count": row[12] or 0,
        "created_at": str(row[13]) if row[13] else None,
        "updated_at": str(row[14]) if row[14] else None,
    }


_SELECT_COLS = (
    "id, template_name, description, category, author_username, "
    "pipeline_type, steps, default_parameters, tags, is_published, "
    "clone_count, rating_sum, rating_count, created_at, updated_at"
)


def create_template(
    template_name: str,
    description: str = "",
    category: str = "general",
    pipeline_type: str = "general",
    steps: list = None,
    default_parameters: dict = None,
    tags: list = None,
) -> Optional[int]:
    """Create a new workflow template. Returns template ID or None."""
    author = current_user_id.get("")
    if not author:
        return None
    if not template_name or not steps:
        return None

    engine = get_engine()
    if not engine:
        return None

    try:
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                INSERT INTO {T_WORKFLOW_TEMPLATES}
                    (template_name, description, category, author_username,
                     pipeline_type, steps, default_parameters, tags)
                VALUES (:name, :desc, :category, :author, :pipeline_type,
                        CAST(:steps AS jsonb), CAST(:params AS jsonb), :tags)
                RETURNING id
            """), {
                "name": template_name,
                "desc": description,
                "category": category,
                "author": author,
                "pipeline_type": pipeline_type,
                "steps": json.dumps(steps or []),
                "params": json.dumps(default_parameters or {}),
                "tags": tags or [],
            })
            tid = result.scalar()
            conn.commit()
        return tid
    except Exception as e:
        logger.warning("Failed to create template: %s", e)
        return None


def list_templates(
    category: str = None,
    keyword: str = None,
    published_only: bool = True,
) -> list[dict]:
    """List workflow templates with optional filters."""
    engine = get_engine()
    if not engine:
        return []

    try:
        conditions = []
        params = {}
        if published_only:
            conditions.append("is_published = TRUE")
        if category:
            conditions.append("category = :cat")
            params["cat"] = category
        if keyword:
            conditions.append(
                "(template_name ILIKE :kw OR description ILIKE :kw OR :kw = ANY(tags))")
            params["kw"] = f"%{keyword}%"

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        with engine.connect() as conn:
            rows = conn.execute(text(
                f"SELECT {_SELECT_COLS} FROM {T_WORKFLOW_TEMPLATES} {where} "
                f"ORDER BY clone_count DESC, created_at DESC"
            ), params).fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        logger.warning("Failed to list templates: %s", e)
        return []


def get_template(template_id: int) -> Optional[dict]:
    """Get a single template by ID."""
    engine = get_engine()
    if not engine:
        return None

    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                f"SELECT {_SELECT_COLS} FROM {T_WORKFLOW_TEMPLATES} WHERE id = :id"
            ), {"id": template_id}).fetchone()
        return _row_to_dict(row) if row else None
    except Exception as e:
        logger.warning("Failed to get template %s: %s", template_id, e)
        return None


def update_template(template_id: int, **fields) -> bool:
    """Update a template (author only). Returns success."""
    author = current_user_id.get("")
    if not author:
        return False

    allowed = {"template_name", "description", "category", "pipeline_type",
               "steps", "default_parameters", "tags", "is_published"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False

    engine = get_engine()
    if not engine:
        return False

    try:
        set_parts = []
        params = {"id": template_id, "author": author}
        for k, v in updates.items():
            if k in ("steps", "default_parameters"):
                set_parts.append(f"{k} = CAST(:{k} AS jsonb)")
                params[k] = json.dumps(v)
            else:
                set_parts.append(f"{k} = :{k}")
                params[k] = v
        set_parts.append("updated_at = NOW()")

        with engine.connect() as conn:
            result = conn.execute(text(
                f"UPDATE {T_WORKFLOW_TEMPLATES} SET {', '.join(set_parts)} "
                f"WHERE id = :id AND author_username = :author"
            ), params)
            conn.commit()
        return result.rowcount > 0
    except Exception as e:
        logger.warning("Failed to update template %s: %s", template_id, e)
        return False


def delete_template(template_id: int) -> bool:
    """Delete a template (author or admin). Returns success."""
    author = current_user_id.get("")
    if not author:
        return False

    engine = get_engine()
    if not engine:
        return False

    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                f"DELETE FROM {T_WORKFLOW_TEMPLATES} WHERE id = :id AND author_username = :author"
            ), {"id": template_id, "author": author})
            conn.commit()
        return result.rowcount > 0
    except Exception as e:
        logger.warning("Failed to delete template %s: %s", template_id, e)
        return False


def publish_template(template_id: int) -> bool:
    """Publish a template (make visible to all). Author only."""
    return update_template(template_id, is_published=True)


def unpublish_template(template_id: int) -> bool:
    """Unpublish a template. Author only."""
    return update_template(template_id, is_published=False)


# ---------------------------------------------------------------------------
# Clone
# ---------------------------------------------------------------------------

def clone_template(template_id: int, workflow_name: str = None,
                   param_overrides: dict = None) -> Optional[int]:
    """Clone a template as a new workflow. Returns new workflow ID."""
    template = get_template(template_id)
    if not template:
        return None

    owner = current_user_id.get("")
    if not owner:
        return None

    wf_name = workflow_name or f"{template['template_name']}_copy"
    params = template.get("default_parameters", {})
    if param_overrides:
        params.update(param_overrides)

    engine = get_engine()
    if not engine:
        return None

    try:
        from .workflow_engine import T_WORKFLOWS
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                INSERT INTO {T_WORKFLOWS}
                    (workflow_name, description, owner_username, pipeline_type,
                     steps, parameters, is_shared)
                VALUES (:name, :desc, :owner, :pipeline_type,
                        CAST(:steps AS jsonb), CAST(:params AS jsonb), FALSE)
                RETURNING id
            """), {
                "name": wf_name,
                "desc": f"Cloned from template: {template['template_name']}",
                "owner": owner,
                "pipeline_type": template["pipeline_type"],
                "steps": json.dumps(template["steps"]),
                "params": json.dumps(params),
            })
            wf_id = result.scalar()

            # Increment clone count
            conn.execute(text(
                f"UPDATE {T_WORKFLOW_TEMPLATES} SET clone_count = clone_count + 1 "
                f"WHERE id = :id"
            ), {"id": template_id})
            conn.commit()

        return wf_id
    except Exception as e:
        logger.warning("Failed to clone template %s: %s", template_id, e)
        return None


# ---------------------------------------------------------------------------
# Rating
# ---------------------------------------------------------------------------

def rate_template(template_id: int, score: int) -> bool:
    """Rate a template (1-5). Adds to running average."""
    if score < 1 or score > 5:
        return False

    engine = get_engine()
    if not engine:
        return False

    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                f"UPDATE {T_WORKFLOW_TEMPLATES} "
                f"SET rating_sum = rating_sum + :score, rating_count = rating_count + 1 "
                f"WHERE id = :id"
            ), {"id": template_id, "score": score})
            conn.commit()
        return result.rowcount > 0
    except Exception as e:
        logger.warning("Failed to rate template %s: %s", template_id, e)
        return False


# ---------------------------------------------------------------------------
# Seed built-in templates
# ---------------------------------------------------------------------------

_BUILTIN_TEMPLATES = [
    {
        "template_name": "数据质量审计",
        "description": "对空间数据进行拓扑、属性完整性、规范符合性的全面审计",
        "category": "governance",
        "pipeline_type": "governance",
        "steps": [
            {"id": "explore", "prompt": "请对数据进行全面的质量探索和属性统计", "pipeline_type": "governance"},
            {"id": "audit", "prompt": "执行拓扑检查和规范符合性验证", "pipeline_type": "governance", "depends_on": ["explore"]},
            {"id": "report", "prompt": "生成数据质量审计报告", "pipeline_type": "governance", "depends_on": ["audit"]},
        ],
        "tags": ["quality", "audit", "governance", "topology"],
    },
    {
        "template_name": "用地优化分析",
        "description": "使用深度强化学习优化土地利用布局方案",
        "category": "optimization",
        "pipeline_type": "optimization",
        "steps": [
            {"id": "load", "prompt": "加载用地数据并进行基础分析", "pipeline_type": "optimization"},
            {"id": "optimize", "prompt": "运行DRL用地优化模型", "pipeline_type": "optimization", "depends_on": ["load"]},
            {"id": "viz", "prompt": "可视化优化结果并生成对比图", "pipeline_type": "optimization", "depends_on": ["optimize"]},
        ],
        "tags": ["optimization", "DRL", "land-use"],
    },
    {
        "template_name": "空间统计报告",
        "description": "热点分析 + 空间自相关 + 聚类分析的完整空间统计流程",
        "category": "analysis",
        "pipeline_type": "general",
        "steps": [
            {"id": "hotspot", "prompt": "执行Getis-Ord热点分析", "pipeline_type": "general"},
            {"id": "moran", "prompt": "计算全局Moran's I空间自相关", "pipeline_type": "general"},
            {"id": "cluster", "prompt": "执行DBSCAN空间聚类分析", "pipeline_type": "general"},
            {"id": "summary", "prompt": "汇总所有空间统计结果", "pipeline_type": "general",
             "depends_on": ["hotspot", "moran", "cluster"]},
        ],
        "tags": ["statistics", "hotspot", "cluster", "Moran"],
    },
    {
        "template_name": "多源数据融合",
        "description": "加载多个数据源并执行智能数据融合",
        "category": "analysis",
        "pipeline_type": "general",
        "steps": [
            {"id": "load", "prompt": "加载并描述所有输入数据集", "pipeline_type": "general"},
            {"id": "fuse", "prompt": "执行数据融合 (strategy=llm_auto)", "pipeline_type": "general",
             "depends_on": ["load"]},
            {"id": "validate", "prompt": "验证融合结果的质量", "pipeline_type": "general",
             "depends_on": ["fuse"]},
        ],
        "tags": ["fusion", "merge", "join"],
    },
    {
        "template_name": "时空变化检测",
        "description": "对比两个时期的空间数据，检测属性和几何变化",
        "category": "analysis",
        "pipeline_type": "general",
        "steps": [
            {"id": "detect", "prompt": "执行空间变化检测，比较{t1_file}和{t2_file}", "pipeline_type": "general"},
            {"id": "viz", "prompt": "可视化变化检测结果", "pipeline_type": "general", "depends_on": ["detect"]},
        ],
        "default_parameters": {"t1_file": "", "t2_file": ""},
        "tags": ["change-detection", "temporal", "comparison"],
    },
    # --- v12.1: 行业分析模板 ---
    {
        "template_name": "城市热岛效应分析",
        "description": "基于遥感影像计算地表温度(LST)，分析城市热岛效应空间分布与强度",
        "category": "城市规划",
        "pipeline_type": "general",
        "steps": [
            {"id": "load", "prompt": "加载研究区域遥感影像数据，提取热红外波段信息", "pipeline_type": "general"},
            {"id": "lst", "prompt": "计算地表温度(LST)并生成温度分布栅格", "pipeline_type": "general", "depends_on": ["load"]},
            {"id": "uhi", "prompt": "执行热岛效应空间统计分析，识别热岛中心和冷岛区域，计算UHI强度指数", "pipeline_type": "general", "depends_on": ["lst"]},
            {"id": "report", "prompt": "生成热岛效应分析报告，包含温度分布图、热岛强度等级图和统计摘要", "pipeline_type": "general", "depends_on": ["uhi"]},
        ],
        "tags": ["urban", "heat-island", "LST", "remote-sensing"],
    },
    {
        "template_name": "植被变化检测",
        "description": "对比两期遥感影像的NDVI指数，检测植被覆盖变化区域和趋势",
        "category": "环境监测",
        "pipeline_type": "general",
        "steps": [
            {"id": "load", "prompt": "加载两期遥感影像数据（{t1_file}和{t2_file}），提取近红外和红光波段", "pipeline_type": "general"},
            {"id": "ndvi", "prompt": "分别计算两期影像的NDVI植被指数", "pipeline_type": "general", "depends_on": ["load"]},
            {"id": "change", "prompt": "执行NDVI差值变化检测，识别植被增加、减少和稳定区域，统计变化面积", "pipeline_type": "general", "depends_on": ["ndvi"]},
            {"id": "report", "prompt": "生成植被变化检测报告，包含NDVI对比图、变化分类图和面积统计表", "pipeline_type": "general", "depends_on": ["change"]},
        ],
        "tags": ["vegetation", "NDVI", "change-detection", "remote-sensing"],
    },
    {
        "template_name": "土地利用优化方案",
        "description": "使用深度强化学习(DRL)优化土地利用布局，降低碎片化指数并提升空间效率",
        "category": "国土资源",
        "pipeline_type": "optimization",
        "steps": [
            {"id": "load", "prompt": "加载土地利用现状数据，分析用地类型分布和碎片化指数", "pipeline_type": "optimization"},
            {"id": "optimize", "prompt": "执行DRL土地利用优化，目标为降低碎片化指数、提升连片度", "pipeline_type": "optimization", "depends_on": ["load"]},
            {"id": "compare", "prompt": "对比优化前后的碎片化指数、面积变化和空间布局差异", "pipeline_type": "optimization", "depends_on": ["optimize"]},
            {"id": "report", "prompt": "生成优化方案报告，包含前后对比可视化和量化指标", "pipeline_type": "optimization", "depends_on": ["compare"]},
        ],
        "tags": ["land-use", "optimization", "DRL", "fragmentation"],
    },
]
    """Insert built-in templates if they don't exist. Returns count of inserted."""
    engine = get_engine()
    if not engine:
        return 0

    inserted = 0
    try:
        with engine.connect() as conn:
            for tmpl in _BUILTIN_TEMPLATES:
                # Check if already exists
                existing = conn.execute(text(
                    f"SELECT 1 FROM {T_WORKFLOW_TEMPLATES} "
                    f"WHERE template_name = :name AND author_username = 'system'"
                ), {"name": tmpl["template_name"]}).fetchone()
                if existing:
                    continue

                conn.execute(text(f"""
                    INSERT INTO {T_WORKFLOW_TEMPLATES}
                        (template_name, description, category, author_username,
                         pipeline_type, steps, default_parameters, tags, is_published)
                    VALUES (:name, :desc, :cat, 'system', :pt,
                            CAST(:steps AS jsonb), CAST(:params AS jsonb), :tags, TRUE)
                """), {
                    "name": tmpl["template_name"],
                    "desc": tmpl["description"],
                    "cat": tmpl["category"],
                    "pt": tmpl["pipeline_type"],
                    "steps": json.dumps(tmpl["steps"]),
                    "params": json.dumps(tmpl.get("default_parameters", {})),
                    "tags": tmpl.get("tags", []),
                })
                inserted += 1
            conn.commit()
    except Exception as e:
        logger.warning("Failed to seed templates: %s", e)
    return inserted
