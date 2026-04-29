"""Seed reusable NL2SQL spatial query patterns into the reference query store."""
from __future__ import annotations
from typing import Optional

_PATTERNS = [
    {
        "query_text": "查找某个AOI区域（如景点、商圈）周边指定距离范围内，满足楼层数或层高条件的建筑物，返回建筑物ID和楼层数",
        "description": "AOI距离查询 + 建筑物属性过滤模式: ST_DWithin + geography + 属性WHERE",
        "response_summary": (
            'SELECT b."Id", b."Floor" '
            "FROM cq_buildings_2021 b "
            "JOIN cq_baidu_aoi_2024 a "
            "  ON ST_DWithin(b.geometry::geography, ST_Transform(a.shape, 4326)::geography, 1000) "
            "WHERE a.\"名称\" LIKE '%解放碑%' AND b.\"Floor\" > 30;"
        ),
        "tags": ["spatial", "distance", "aoi", "buildings", "dwithin", "geography"],
    },
    {
        "query_text": "计算两个面图层（如规划区、管制区）的空间交集总面积，以公顷或平方米为单位返回单个汇总结果",
        "description": "面面相交 + 总面积聚合模式: ST_Intersects + ST_Intersection + SUM(ST_Area)",
        "response_summary": (
            "SELECT SUM(ST_Area(ST_Intersection(j.shape, g.shape))) / 10000.0 AS intersect_area_ha "
            "FROM cq_jsydgzq j "
            "JOIN cq_ghfw g ON ST_Intersects(j.shape, g.shape);"
        ),
        "tags": ["spatial", "intersection", "area", "aggregation", "polygon"],
    },
]


def seed_nl2sql_patterns(created_by: Optional[str] = None) -> list[Optional[int]]:
    """Insert canonical NL2SQL spatial patterns into the reference query store.

    Idempotent via ReferenceQueryStore's built-in cosine dedup (>0.92 threshold).
    """
    from .reference_queries import ReferenceQueryStore
    store = ReferenceQueryStore()
    ids = []
    for p in _PATTERNS:
        ref_id = store.add(
            query_text=p["query_text"],
            description=p["description"],
            response_summary=p["response_summary"],
            tags=p["tags"],
            task_type="nl2sql",
            source="benchmark_pattern",
            created_by=created_by,
        )
        ids.append(ref_id)
    return ids
