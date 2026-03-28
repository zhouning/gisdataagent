"""元数据管理器 - 统一的元数据操作接口"""
import json
from typing import Optional, List, Dict, Any
from sqlalchemy import text
from .db_engine import get_engine
from .user_context import current_user_id


class MetadataManager:
    """元数据管理器 - 统一的元数据操作接口"""

    def register_asset(
        self,
        asset_name: str,
        technical: dict,
        business: dict = None,
        operational: dict = None,
        lineage: dict = None,
        display_name: str = None,
    ) -> int:
        """注册新数据资产

        Args:
            asset_name: 资产名称
            technical: 技术元数据 (storage, spatial, structure, temporal)
            business: 业务元数据 (semantic, classification, geography, quality)
            operational: 操作元数据 (source, creation, version, access, lifecycle)
            lineage: 血缘元数据 (upstream, transformation, downstream)
            display_name: 显示名称

        Returns:
            asset_id: 新创建的资产ID
        """
        engine = get_engine()
        user_id = current_user_id.get()

        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    INSERT INTO agent_data_assets (
                        asset_name, display_name, owner_username,
                        technical_metadata, business_metadata,
                        operational_metadata, lineage_metadata
                    ) VALUES (
                        :name, :display, :owner,
                        CAST(:tech AS jsonb), CAST(:biz AS jsonb),
                        CAST(:ops AS jsonb), CAST(:lineage AS jsonb)
                    ) RETURNING id
                """),
                {
                    "name": asset_name,
                    "display": display_name or asset_name,
                    "owner": user_id,
                    "tech": json.dumps(technical),
                    "biz": json.dumps(business or {}),
                    "ops": json.dumps(operational or {}),
                    "lineage": json.dumps(lineage or {}),
                }
            )
            conn.commit()
            return result.fetchone()[0]

    def update_metadata(
        self,
        asset_id: int,
        technical: dict = None,
        business: dict = None,
        operational: dict = None,
        lineage: dict = None,
    ) -> bool:
        """更新元数据 (深度合并)"""
        engine = get_engine()
        updates = []
        params = {"id": asset_id}

        if technical:
            updates.append("technical_metadata = technical_metadata || CAST(:tech AS jsonb)")
            params["tech"] = json.dumps(technical)
        if business:
            updates.append("business_metadata = business_metadata || CAST(:biz AS jsonb)")
            params["biz"] = json.dumps(business)
        if operational:
            updates.append("operational_metadata = operational_metadata || CAST(:ops AS jsonb)")
            params["ops"] = json.dumps(operational)
        if lineage:
            updates.append("lineage_metadata = lineage_metadata || CAST(:lineage AS jsonb)")
            params["lineage"] = json.dumps(lineage)

        if not updates:
            return False

        updates.append("updated_at = NOW()")

        with engine.connect() as conn:
            conn.execute(
                text(f"UPDATE agent_data_assets SET {', '.join(updates)} WHERE id = :id"),
                params
            )
            conn.commit()
        return True

    def get_metadata(
        self, asset_id: int, layers: List[str] = None
    ) -> Optional[Dict[str, Any]]:
        """获取元数据

        Args:
            asset_id: 资产ID
            layers: 指定层 ['technical', 'business', 'operational', 'lineage']
                   None = 返回所有层
        """
        engine = get_engine()

        if layers:
            cols = ", ".join([f"{layer}_metadata" for layer in layers])
        else:
            cols = "technical_metadata, business_metadata, operational_metadata, lineage_metadata"

        with engine.connect() as conn:
            result = conn.execute(
                text(f"SELECT {cols} FROM agent_data_assets WHERE id = :id"),
                {"id": asset_id}
            )
            row = result.fetchone()
            if not row:
                return None

            if layers:
                return dict(zip(layers, row))
            else:
                return {
                    "technical": row[0],
                    "business": row[1],
                    "operational": row[2],
                    "lineage": row[3],
                }

    def search_assets(
        self,
        query: str = None,
        filters: dict = None,
        sort_by: str = "created_at",
        limit: int = 50,
    ) -> List[dict]:
        """检索数据资产"""
        engine = get_engine()
        user_id = current_user_id.get()

        conditions = ["owner_username = :user"]
        params = {"user": user_id, "limit": limit}

        if query:
            conditions.append(
                "(asset_name ILIKE :query OR display_name ILIKE :query "
                "OR business_metadata->'semantic'->>'keywords' ILIKE :query)"
            )
            params["query"] = f"%{query}%"

        if filters:
            if "region" in filters:
                conditions.append("business_metadata->'geography'->'region_tags' @> CAST(:region AS jsonb)")
                params["region"] = f'["{filters["region"]}"]'
            if "domain" in filters:
                conditions.append("business_metadata->'classification'->>'domain' = :domain")
                params["domain"] = filters["domain"]
            if "source_type" in filters:
                conditions.append("operational_metadata->'source'->>'type' = :stype")
                params["stype"] = filters["source_type"]

        where_clause = " AND ".join(conditions)

        with engine.connect() as conn:
            result = conn.execute(
                text(f"""
                    SELECT id, asset_name, display_name,
                           technical_metadata, business_metadata,
                           operational_metadata, created_at
                    FROM agent_data_assets
                    WHERE {where_clause}
                    ORDER BY {sort_by} DESC
                    LIMIT :limit
                """),
                params
            )
            return [dict(row._mapping) for row in result]

    def get_lineage(self, asset_id: int, direction: str = "both", depth: int = 3) -> dict:
        """获取血缘关系图"""
        engine = get_engine()
        
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT lineage_metadata FROM agent_data_assets WHERE id = :id"),
                {"id": asset_id}
            )
            row = result.fetchone()
            if not row:
                return {}
            
            return row[0] or {}
