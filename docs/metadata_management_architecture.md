# 数据资产元数据管理体系架构

> 版本：v2.0 (2026-03-28)
>
> 目标：构建完整的元数据管理体系，支撑数据资产的全生命周期管理

---

## 一、元数据体系分层架构

```
┌─────────────────────────────────────────────────────────────┐
│  应用层 (Application Layer)                                   │
│  - 数据发现与检索                                              │
│  - 数据血缘追踪                                                │
│  - 数据质量评估                                                │
│  - 数据治理报告                                                │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  元数据服务层 (Metadata Service Layer)                        │
│  - MetadataManager: 统一元数据管理接口                         │
│  - MetadataExtractor: 自动元数据提取                          │
│  - MetadataEnricher: 元数据增强与推理                         │
│  - MetadataValidator: 元数据质量校验                          │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  元数据存储层 (Metadata Storage Layer)                        │
│  - 技术元数据 (Technical Metadata)                            │
│  - 业务元数据 (Business Metadata)                             │
│  - 操作元数据 (Operational Metadata)                          │
│  - 血缘元数据 (Lineage Metadata)                              │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  数据资产层 (Data Asset Layer)                                │
│  - 文件系统 (Local/OBS)                                       │
│  - 数据库 (PostgreSQL/PostGIS)                                │
│  - 流数据 (IoT Streams)                                       │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、元数据分类体系

### 2.1 技术元数据 (Technical Metadata)

**定义**：描述数据的物理特征和技术属性

| 维度 | 字段 | 示例 |
|------|------|------|
| **存储属性** | storage_backend, storage_path, file_size_bytes, format | local, /uploads/user1/data.shp, 2048000, shapefile |
| **空间属性** | spatial_extent (bbox), crs, srid, geometry_type | {minx:105, miny:28, ...}, EPSG:4326, 4326, Polygon |
| **结构属性** | column_schema, feature_count, band_count, resolution | [{name:"pop",type:"int"}], 10000, 3, 30m |
| **时间属性** | temporal_extent, temporal_resolution | {start:"2020-01", end:"2023-12"}, monthly |

### 2.2 业务元数据 (Business Metadata)

**定义**：描述数据的业务含义和语义

| 维度 | 字段 | 示例 |
|------|------|------|
| **语义标识** | asset_name, display_name, description, keywords | chongqing_farmland.shp, 重庆耕地分布, 2023年重庆市耕地现状, [耕地,农业,重庆] |
| **分类标签** | domain, theme, category, tags | LAND_USE, 农业用地, 矢量数据, [基础地理,土地资源] |
| **地理标签** | region_tags, admin_level | [重庆市,西南,长江流域], province |
| **质量标签** | quality_score, completeness, accuracy_level | 0.95, 0.98, 高精度 |

### 2.3 操作元数据 (Operational Metadata)

**定义**：描述数据的生命周期和使用情况

| 维度 | 字段 | 示例 |
|------|------|------|
| **来源信息** | source_type, source_system, upload_method | uploaded, 用户上传, web_ui |
| **创建信息** | created_at, created_by, creation_tool, creation_params | 2026-03-28T10:00:00, user1, buffer_analysis, {distance:1000} |
| **版本信息** | version, parent_version, is_latest | v2, v1, true |
| **访问信息** | access_count, last_accessed_at, access_users | 15, 2026-03-28T15:30:00, [user1,user2] |
| **状态信息** | lifecycle_stage, is_archived, retention_policy | active, false, keep_90d |

### 2.4 血缘元数据 (Lineage Metadata)

**定义**：描述数据的来源、转换和依赖关系

| 维度 | 字段 | 示例 |
|------|------|------|
| **上游依赖** | source_assets, input_datasets | [asset_123, asset_456], [chongqing_boundary.shp] |
| **转换过程** | transformation_type, pipeline_run_id, workflow_id | spatial_join, run_789, wf_012 |
| **下游影响** | derived_assets, downstream_count | [asset_234, asset_567], 3 |

---

## 三、元数据模型设计

### 3.1 核心实体关系

```
DataAsset (数据资产)
  ├─ TechnicalMetadata (技术元数据)
  ├─ BusinessMetadata (业务元数据)
  ├─ OperationalMetadata (操作元数据)
  └─ LineageMetadata (血缘元数据)
       ├─ upstream: [DataAsset]
       └─ downstream: [DataAsset]

MetadataSchema (元数据模式)
  ├─ domain: str (领域)
  ├─ attributes: [MetadataAttribute]
  └─ validation_rules: [ValidationRule]

MetadataAttribute (元数据属性)
  ├─ name: str
  ├─ type: str (string/number/date/json/geometry)
  ├─ required: bool
  ├─ default_value: any
  └─ constraints: dict
```

### 3.2 数据库表结构

**主表：agent_data_assets (替代现有 agent_data_catalog)**

```sql
CREATE TABLE agent_data_assets (
    -- 基础标识
    id SERIAL PRIMARY KEY,
    asset_uuid UUID DEFAULT gen_random_uuid() UNIQUE,
    asset_name VARCHAR(255) NOT NULL,
    display_name VARCHAR(255),

    -- 技术元数据
    technical_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- {
    --   "storage": {"backend": "local", "path": "/uploads/...", "size_bytes": 2048000},
    --   "spatial": {"extent": {...}, "crs": "EPSG:4326", "srid": 4326, "geometry_type": "Polygon"},
    --   "structure": {"columns": [...], "feature_count": 10000},
    --   "temporal": {"extent": {...}, "resolution": "monthly"}
    -- }

    -- 业务元数据
    business_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- {
    --   "semantic": {"description": "...", "keywords": [...]},
    --   "classification": {"domain": "LAND_USE", "theme": "农业用地", "category": "矢量数据"},
    --   "geography": {"region_tags": ["重庆市","西南"], "admin_level": "province"},
    --   "quality": {"score": 0.95, "completeness": 0.98, "accuracy": "高精度"}
    -- }

    -- 操作元数据
    operational_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- {
    --   "source": {"type": "uploaded", "system": "web_ui", "method": "drag_drop"},
    --   "creation": {"tool": "buffer_analysis", "params": {...}},
    --   "version": {"version": "v2", "parent": "v1", "is_latest": true},
    --   "access": {"count": 15, "last_at": "...", "users": [...]},
    --   "lifecycle": {"stage": "active", "archived": false, "retention": "keep_90d"}
    -- }

    -- 血缘元数据
    lineage_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- {
    --   "upstream": {"asset_ids": [123, 456], "dataset_names": [...]},
    --   "transformation": {"type": "spatial_join", "pipeline_run_id": 789, "workflow_id": 12},
    --   "downstream": {"asset_ids": [234, 567], "count": 3}
    -- }

    -- 所有权与权限
    owner_username VARCHAR(100) NOT NULL,
    team_id INTEGER REFERENCES agent_teams(id),
    is_shared BOOLEAN DEFAULT false,
    access_level VARCHAR(20) DEFAULT 'private', -- private/team/public

    -- 时间戳
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    -- 索引优化
    CONSTRAINT valid_technical_metadata CHECK (jsonb_typeof(technical_metadata) = 'object'),
    CONSTRAINT valid_business_metadata CHECK (jsonb_typeof(business_metadata) = 'object')
);

-- GIN 索引支持 JSONB 查询
CREATE INDEX idx_assets_technical_meta ON agent_data_assets USING GIN (technical_metadata);
CREATE INDEX idx_assets_business_meta ON agent_data_assets USING GIN (business_metadata);
CREATE INDEX idx_assets_operational_meta ON agent_data_assets USING GIN (operational_metadata);
CREATE INDEX idx_assets_lineage_meta ON agent_data_assets USING GIN (lineage_metadata);

-- 常用查询索引
CREATE INDEX idx_assets_owner ON agent_data_assets(owner_username);
CREATE INDEX idx_assets_created ON agent_data_assets(created_at DESC);
```

**辅助表：agent_metadata_schemas (元数据模式定义)**

```sql
CREATE TABLE agent_metadata_schemas (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(100) NOT NULL UNIQUE, -- LAND_USE, ELEVATION, POPULATION, etc.
    schema_definition JSONB NOT NULL,
    -- {
    --   "attributes": [
    --     {"name": "region_tags", "type": "array", "required": true, "constraints": {...}},
    --     {"name": "quality_score", "type": "number", "required": false, "default": 0.0}
    --   ],
    --   "validation_rules": [...]
    -- }
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

---

## 四、元数据服务接口设计

### 4.1 MetadataManager (统一管理接口)

```python
class MetadataManager:
    """元数据管理器 - 统一的元数据操作接口"""

    def register_asset(
        self,
        asset_name: str,
        technical: dict,
        business: dict = None,
        operational: dict = None,
        lineage: dict = None,
    ) -> int:
        """注册新数据资产"""

    def update_metadata(
        self, asset_id: int,
        technical: dict = None,
        business: dict = None,
        operational: dict = None,
        lineage: dict = None,
    ) -> bool:
        """更新元数据"""

    def get_metadata(self, asset_id: int, layers: list[str] = None) -> dict:
        """获取元数据（可指定层：technical/business/operational/lineage）"""

    def search_assets(
        self,
        query: str = None,
        filters: dict = None,
        sort_by: str = "created_at",
        limit: int = 50,
    ) -> list[dict]:
        """检索数据资产"""

    def get_lineage(self, asset_id: int, direction: str = "both", depth: int = 3) -> dict:
        """获取血缘关系图（upstream/downstream/both）"""
```

### 4.2 MetadataExtractor (自动提取)

```python
class MetadataExtractor:
    """元数据提取器 - 从数据文件自动提取元数据"""

    def extract_from_file(self, file_path: str) -> dict:
        """从文件提取完整元数据"""

    def extract_spatial_metadata(self, file_path: str) -> dict:
        """提取空间元数据（bbox, crs, geometry_type）"""

    def extract_schema_metadata(self, file_path: str) -> dict:
        """提取结构元数据（columns, feature_count）"""

    def extract_temporal_metadata(self, file_path: str) -> dict:
        """提取时间元数据（temporal_extent）"""
```

### 4.3 MetadataEnricher (元数据增强)

```python
class MetadataEnricher:
    """元数据增强器 - 推理和补充元数据"""

    def enrich_geography(self, bbox: dict) -> dict:
        """根据 bbox 推理地区标签"""

    def enrich_domain(self, asset_name: str, keywords: list) -> str:
        """根据名称和关键词推理领域分类"""

    def enrich_quality(self, asset_id: int) -> dict:
        """评估数据质量指标"""

    def enrich_lineage(self, asset_id: int) -> dict:
        """补充血缘关系"""
```

---

## 五、实施方案

### 5.1 数据库迁移 (Migration 044)

**文件**: `data_agent/migrations/044_metadata_system.sql`

```sql
-- Step 1: 创建新表 agent_data_assets
CREATE TABLE agent_data_assets (
    id SERIAL PRIMARY KEY,
    asset_uuid UUID DEFAULT gen_random_uuid() UNIQUE,
    asset_name VARCHAR(255) NOT NULL,
    display_name VARCHAR(255),

    technical_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    business_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    operational_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    lineage_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    owner_username VARCHAR(100) NOT NULL,
    team_id INTEGER REFERENCES agent_teams(id),
    is_shared BOOLEAN DEFAULT false,
    access_level VARCHAR(20) DEFAULT 'private',

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT valid_technical_metadata CHECK (jsonb_typeof(technical_metadata) = 'object'),
    CONSTRAINT valid_business_metadata CHECK (jsonb_typeof(business_metadata) = 'object'),
    CONSTRAINT valid_operational_metadata CHECK (jsonb_typeof(operational_metadata) = 'object'),
    CONSTRAINT valid_lineage_metadata CHECK (jsonb_typeof(lineage_metadata) = 'object')
);

-- Step 2: 创建索引
CREATE INDEX idx_assets_technical_meta ON agent_data_assets USING GIN (technical_metadata);
CREATE INDEX idx_assets_business_meta ON agent_data_assets USING GIN (business_metadata);
CREATE INDEX idx_assets_operational_meta ON agent_data_assets USING GIN (operational_metadata);
CREATE INDEX idx_assets_lineage_meta ON agent_data_assets USING GIN (lineage_metadata);
CREATE INDEX idx_assets_owner ON agent_data_assets(owner_username);
CREATE INDEX idx_assets_created ON agent_data_assets(created_at DESC);

-- Step 3: 创建元数据模式表
CREATE TABLE agent_metadata_schemas (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(100) NOT NULL UNIQUE,
    schema_definition JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Step 4: 数据迁移 (从 agent_data_catalog 迁移到 agent_data_assets)
INSERT INTO agent_data_assets (
    asset_name, display_name, owner_username, team_id, is_shared,
    technical_metadata, business_metadata, operational_metadata, lineage_metadata,
    created_at, updated_at
)
SELECT
    asset_name,
    asset_name as display_name,
    owner_username,
    team_id,
    is_shared,
    -- 技术元数据
    jsonb_build_object(
        'storage', jsonb_build_object(
            'backend', storage_backend,
            'path', storage_path,
            'size_bytes', file_size_bytes,
            'format', format
        ),
        'spatial', jsonb_build_object(
            'extent', spatial_extent,
            'crs', crs,
            'srid', srid,
            'geometry_type', geometry_type
        ),
        'structure', jsonb_build_object(
            'columns', column_schema,
            'feature_count', feature_count
        ),
        'temporal', jsonb_build_object(
            'extent', temporal_extent
        )
    ),
    -- 业务元数据
    jsonb_build_object(
        'semantic', jsonb_build_object(
            'description', description,
            'keywords', tags
        ),
        'classification', jsonb_build_object(
            'domain', domain,
            'theme', theme,
            'category', asset_type
        )
    ),
    -- 操作元数据
    jsonb_build_object(
        'source', jsonb_build_object(
            'type', COALESCE(source_type, 'unknown')
        ),
        'creation', jsonb_build_object(
            'tool', creation_tool
        ),
        'version', jsonb_build_object(
            'version', version,
            'is_latest', true
        )
    ),
    -- 血缘元数据
    jsonb_build_object(
        'upstream', jsonb_build_object(
            'asset_ids', COALESCE(source_assets, '[]'::jsonb)
        )
    ),
    created_at,
    updated_at
FROM agent_data_catalog;

-- Step 5: 预置元数据模式
INSERT INTO agent_metadata_schemas (domain, schema_definition) VALUES
('LAND_USE', '{
    "attributes": [
        {"name": "region_tags", "type": "array", "required": true},
        {"name": "quality_score", "type": "number", "required": false, "default": 0.0}
    ],
    "validation_rules": []
}'::jsonb),
('ELEVATION', '{
    "attributes": [
        {"name": "vertical_datum", "type": "string", "required": true},
        {"name": "resolution", "type": "string", "required": true}
    ]
}'::jsonb);
```

### 5.2 MetadataManager 实现

**文件**: `data_agent/metadata_manager.py` (NEW)

```python
"""元数据管理器 - 统一的元数据操作接口"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy import text
from .db_engine import get_engine
from .user_context import get_current_user_id

class MetadataManager:
    """元数据管理器"""

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
        user_id = get_current_user_id()

        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    INSERT INTO agent_data_assets (
                        asset_name, display_name, owner_username,
                        technical_metadata, business_metadata,
                        operational_metadata, lineage_metadata
                    ) VALUES (
                        :name, :display, :owner,
                        :tech::jsonb, :biz::jsonb, :ops::jsonb, :lineage::jsonb
                    ) RETURNING id
                """),
                {
                    "name": asset_name,
                    "display": display_name or asset_name,
                    "owner": user_id,
                    "tech": technical,
                    "biz": business or {},
                    "ops": operational or {},
                    "lineage": lineage or {},
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
            updates.append("technical_metadata = technical_metadata || :tech::jsonb")
            params["tech"] = technical
        if business:
            updates.append("business_metadata = business_metadata || :biz::jsonb")
            params["biz"] = business
        if operational:
            updates.append("operational_metadata = operational_metadata || :ops::jsonb")
            params["ops"] = operational
        if lineage:
            updates.append("lineage_metadata = lineage_metadata || :lineage::jsonb")
            params["lineage"] = lineage

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
        """检索数据资产

        Args:
            query: 关键词搜索 (asset_name, display_name, keywords)
            filters: 过滤条件 {
                "region": "重庆市",
                "domain": "LAND_USE",
                "source_type": "uploaded",
                "owner": "user1"
            }
            sort_by: 排序字段
            limit: 返回数量
        """
        engine = get_engine()
        user_id = get_current_user_id()

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
                conditions.append("business_metadata->'geography'->'region_tags' @> :region::jsonb")
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
```

### 5.3 MetadataExtractor 实现

**文件**: `data_agent/metadata_extractor.py` (NEW)

```python
"""元数据提取器 - 从数据文件自动提取元数据"""
import geopandas as gpd
import rasterio
from pathlib import Path
from typing import Dict, Any, Optional

class MetadataExtractor:
    """元数据提取器"""

    def extract_from_file(self, file_path: str) -> Dict[str, Any]:
        """从文件提取完整元数据"""
        path = Path(file_path)
        suffix = path.suffix.lower()

        metadata = {
            "technical": {},
            "business": {},
            "operational": {
                "source": {"type": "uploaded", "method": "file_upload"},
                "creation": {"timestamp": path.stat().st_ctime},
            }
        }

        # 提取空间元数据
        if suffix in [".shp", ".geojson", ".gpkg", ".kml"]:
            metadata["technical"].update(self.extract_spatial_metadata(file_path))
            metadata["technical"].update(self.extract_schema_metadata(file_path))
        elif suffix in [".tif", ".tiff"]:
            metadata["technical"].update(self._extract_raster_metadata(file_path))

        # 提取存储元数据
        metadata["technical"]["storage"] = {
            "path": str(file_path),
            "size_bytes": path.stat().st_size,
            "format": suffix[1:],
        }

        return metadata

    def extract_spatial_metadata(self, file_path: str) -> dict:
        """提取空间元数据 (bbox, crs, geometry_type)"""
        try:
            gdf = gpd.read_file(file_path)
            bounds = gdf.total_bounds  # [minx, miny, maxx, maxy]

            return {
                "spatial": {
                    "extent": {
                        "minx": float(bounds[0]),
                        "miny": float(bounds[1]),
                        "maxx": float(bounds[2]),
                        "maxy": float(bounds[3]),
                    },
                    "crs": str(gdf.crs) if gdf.crs else None,
                    "srid": gdf.crs.to_epsg() if gdf.crs else None,
                    "geometry_type": gdf.geom_type.mode()[0] if len(gdf) > 0 else None,
                }
            }
        except Exception as e:
            return {"spatial": {"error": str(e)}}

    def extract_schema_metadata(self, file_path: str) -> dict:
        """提取结构元数据 (columns, feature_count)"""
        try:
            gdf = gpd.read_file(file_path)
            columns = [
                {"name": col, "type": str(gdf[col].dtype)}
                for col in gdf.columns if col != "geometry"
            ]

            return {
                "structure": {
                    "columns": columns,
                    "feature_count": len(gdf),
                }
            }
        except Exception as e:
            return {"structure": {"error": str(e)}}

    def _extract_raster_metadata(self, file_path: str) -> dict:
        """提取栅格元数据"""
        try:
            with rasterio.open(file_path) as src:
                bounds = src.bounds
                return {
                    "spatial": {
                        "extent": {
                            "minx": bounds.left,
                            "miny": bounds.bottom,
                            "maxx": bounds.right,
                            "maxy": bounds.top,
                        },
                        "crs": str(src.crs),
                        "srid": src.crs.to_epsg() if src.crs else None,
                    },
                    "structure": {
                        "band_count": src.count,
                        "width": src.width,
                        "height": src.height,
                        "resolution": src.res,
                    }
                }
        except Exception as e:
            return {"spatial": {"error": str(e)}}
```


### 5.4 MetadataEnricher 实现

**文件**: `data_agent/metadata_enricher.py` (NEW)

```python
"""元数据增强器 - 推理和补充元数据"""
from typing import Dict, List, Optional

class MetadataEnricher:
    """元数据增强器"""

    REGION_BBOXES = {
        "重庆市": (105.28, 28.16, 110.19, 32.20),
        "四川省": (97.35, 26.05, 108.55, 34.32),
        "上海市": (120.86, 30.68, 122.12, 31.87),
    }

    REGION_GROUPS = {
        "西南": ["四川省", "云南省", "贵州省", "西藏自治区", "重庆市"],
        "华东": ["上海市", "江苏省", "浙江省", "安徽省", "福建省"],
    }

    def enrich_geography(self, bbox: dict) -> dict:
        """根据 bbox 推理地区标签"""
        if not bbox:
            return {"region_tags": []}

        tags = []
        data_box = (bbox["minx"], bbox["miny"], bbox["maxx"], bbox["maxy"])

        for region, region_box in self.REGION_BBOXES.items():
            if self._boxes_overlap(data_box, region_box):
                tags.append(region)

        for group, provinces in self.REGION_GROUPS.items():
            if any(p in tags for p in provinces):
                tags.append(group)

        return {"region_tags": list(set(tags))}

    def enrich_domain(self, asset_name: str, keywords: List[str]) -> Optional[str]:
        """根据名称和关键词推理领域分类"""
        text = f"{asset_name} {' '.join(keywords)}".lower()

        domain_keywords = {
            "LAND_USE": ["土地", "耕地", "林地", "用地"],
            "ELEVATION": ["高程", "dem", "dsm"],
            "POPULATION": ["人口", "population"],
        }

        for domain, kws in domain_keywords.items():
            if any(kw in text for kw in kws):
                return domain
        return None

    @staticmethod
    def _boxes_overlap(box1: tuple, box2: tuple) -> bool:
        """判断两个 bbox 是否重叠"""
        return not (
            box1[2] < box2[0] or box1[0] > box2[2] or
            box1[3] < box2[1] or box1[1] > box2[3]
        )
```

### 5.5 集成到文件上传流程

**文件**: `data_agent/app.py` (修改上传处理逻辑，约 line 2800)

```python
from data_agent.metadata_manager import MetadataManager
from data_agent.metadata_extractor import MetadataExtractor
from data_agent.metadata_enricher import MetadataEnricher

# 在文件保存后
extractor = MetadataExtractor()
enricher = MetadataEnricher()
manager = MetadataManager()

# 提取元数据
extracted = extractor.extract_from_file(str(file_path))

# 增强元数据
if "spatial" in extracted["technical"]:
    bbox = extracted["technical"]["spatial"].get("extent")
    if bbox:
        geo_info = enricher.enrich_geography(bbox)
        extracted["business"]["geography"] = geo_info

domain = enricher.enrich_domain(filename, [])
if domain:
    extracted["business"]["classification"] = {"domain": domain}

# 注册到数据目录
asset_id = manager.register_asset(
    asset_name=filename,
    technical=extracted["technical"],
    business=extracted["business"],
    operational=extracted["operational"],
)
```

### 5.6 增强 ExplorationToolset

**文件**: `data_agent/toolsets/exploration_tools.py` (新增工具)

```python
def search_user_data(query: str = "", region: str = "", source_type: str = "all") -> str:
    """按条件检索用户数据
    
    Args:
        query: 关键词（文件名、标签）
        region: 地区名称（如"重庆"、"西南"）
        source_type: 来源类型（uploaded/generated/all）
    """
    from data_agent.metadata_manager import MetadataManager
    
    manager = MetadataManager()
    filters = {}
    if region:
        filters["region"] = region
    if source_type != "all":
        filters["source_type"] = source_type
    
    results = manager.search_assets(query=query, filters=filters, limit=50)
    
    if not results:
        return f"未找到匹配的数据（查询: {query}, 地区: {region or '全部'}）"
    
    # 按来源分类
    uploaded = [r for r in results if r["operational_metadata"].get("source", {}).get("type") == "uploaded"]
    generated = [r for r in results if r["operational_metadata"].get("source", {}).get("type") == "generated"]
    
    output = [f"📁 找到 {len(results)} 个数据集\n"]
    
    if uploaded:
        output.append(f"\n📥 原始数据 ({len(uploaded)} 个)")
        for r in uploaded[:5]:
            size_mb = r["technical_metadata"].get("storage", {}).get("size_bytes", 0) / 1024 / 1024
            tags = r["business_metadata"].get("geography", {}).get("region_tags", [])
            output.append(f"  • {r['display_name']} ({size_mb:.1f}MB) {tags}")
    
    if generated:
        output.append(f"\n📊 分析结果 ({len(generated)} 个)")
        for r in generated[:5]:
            tool = r["operational_metadata"].get("creation", {}).get("tool", "未知")
            output.append(f"  • {r['display_name']} — {tool}")
    
    return "\n".join(output)
```

### 5.7 改进 list_user_files

**文件**: `data_agent/toolsets/file_tools.py` (修改现有函数)

```python
def list_user_files() -> str:
    """列出用户数据文件，按来源分类展示"""
    from data_agent.metadata_manager import MetadataManager
    
    manager = MetadataManager()
    results = manager.search_assets(limit=100)
    
    # 按来源分类
    uploaded = [r for r in results if r["operational_metadata"].get("source", {}).get("type") == "uploaded"]
    generated = [r for r in results if r["operational_metadata"].get("source", {}).get("type") == "generated"]
    
    output = [f"📁 用户数据概览 (共 {len(results)} 个文件)\n"]
    
    if uploaded:
        output.append(f"📥 原始数据 ({len(uploaded)} 个)")
        for r in uploaded:
            size_mb = r["technical_metadata"].get("storage", {}).get("size_bytes", 0) / 1024 / 1024
            tags = r["business_metadata"].get("geography", {}).get("region_tags", [])
            created = r["created_at"].strftime("%Y-%m-%d")
            output.append(f"  {r['id']}. {r['display_name']} ({size_mb:.1f}MB) {tags} — {created}")
    
    if generated:
        output.append(f"\n📊 分析结果 ({len(generated)} 个)")
        for r in generated:
            tool = r["operational_metadata"].get("creation", {}).get("tool", "未知")
            output.append(f"  {r['id']}. {r['display_name']} — {tool}")
    
    return "\n".join(output)
```

---

## 六、测试方案

### 6.1 单元测试

**文件**: `data_agent/test_metadata_system.py` (NEW)

```python
import pytest
from unittest.mock import patch, MagicMock
from data_agent.metadata_manager import MetadataManager
from data_agent.metadata_extractor import MetadataExtractor
from data_agent.metadata_enricher import MetadataEnricher

@patch("data_agent.metadata_manager.get_engine")
@patch("data_agent.metadata_manager.get_current_user_id", return_value="test_user")
def test_register_asset(mock_user, mock_engine):
    """测试资产注册"""
    mock_conn = MagicMock()
    mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.fetchone.return_value = [123]
    
    manager = MetadataManager()
    asset_id = manager.register_asset(
        asset_name="test.shp",
        technical={"storage": {"path": "/test.shp"}},
    )
    
    assert asset_id == 123
    assert mock_conn.execute.called

def test_extract_spatial_metadata(tmp_path):
    """测试空间元数据提取"""
    # 创建测试 GeoJSON
    import geopandas as gpd
    from shapely.geometry import Point
    
    gdf = gpd.GeoDataFrame(
        {"name": ["A"]},
        geometry=[Point(105, 30)],
        crs="EPSG:4326"
    )
    test_file = tmp_path / "test.geojson"
    gdf.to_file(test_file, driver="GeoJSON")
    
    extractor = MetadataExtractor()
    result = extractor.extract_spatial_metadata(str(test_file))
    
    assert "spatial" in result
    assert "extent" in result["spatial"]
    assert result["spatial"]["srid"] == 4326

def test_enrich_geography():
    """测试地区标签推理"""
    enricher = MetadataEnricher()
    
    # 重庆市范围内的 bbox
    bbox = {"minx": 106.0, "miny": 29.0, "maxx": 109.0, "maxy": 31.0}
    result = enricher.enrich_geography(bbox)
    
    assert "重庆市" in result["region_tags"]
    assert "西南" in result["region_tags"]
```

### 6.2 集成测试

```python
@patch("data_agent.metadata_manager.get_engine")
def test_full_metadata_pipeline(mock_engine, tmp_path):
    """测试完整元数据流程：提取 → 增强 → 注册"""
    # 创建测试文件
    import geopandas as gpd
    from shapely.geometry import Point
    
    gdf = gpd.GeoDataFrame(
        {"land_use": ["耕地"]},
        geometry=[Point(106, 30)],
        crs="EPSG:4326"
    )
    test_file = tmp_path / "重庆耕地.geojson"
    gdf.to_file(test_file, driver="GeoJSON")
    
    # 提取
    extractor = MetadataExtractor()
    extracted = extractor.extract_from_file(str(test_file))
    
    # 增强
    enricher = MetadataEnricher()
    bbox = extracted["technical"]["spatial"]["extent"]
    geo_info = enricher.enrich_geography(bbox)
    domain = enricher.enrich_domain("重庆耕地", [])
    
    assert "重庆市" in geo_info["region_tags"]
    assert domain == "LAND_USE"
```

---

## 七、实施路线图

### Phase 1: 核心基础设施 (Week 1)

| 任务 | 文件 | 工作量 |
|------|------|--------|
| 数据库迁移 | `migrations/044_metadata_system.sql` | 2h |
| MetadataManager | `metadata_manager.py` | 4h |
| MetadataExtractor | `metadata_extractor.py` | 4h |
| MetadataEnricher | `metadata_enricher.py` | 3h |
| 单元测试 | `test_metadata_system.py` | 3h |

**交付物**: 元数据管理核心模块 + 数据库表结构

### Phase 2: 集成现有流程 (Week 2)

| 任务 | 文件 | 工作量 |
|------|------|--------|
| 上传流程集成 | `app.py` 文件上传处理 | 2h |
| GIS 处理集成 | `gis_processors.py` | 2h |
| ExplorationToolset 增强 | `toolsets/exploration_tools.py` | 3h |
| FileToolset 改进 | `toolsets/file_tools.py` | 2h |
| 集成测试 | `test_metadata_integration.py` | 3h |

**交付物**: 自动元数据提取 + 增强检索能力

### Phase 3: 前端展示 (Week 3)

| 任务 | 文件 | 工作量 |
|------|------|--------|
| 元数据详情面板 | `frontend/src/components/MetadataPanel.tsx` | 4h |
| 数据目录增强 | `datapanel/CatalogTab.tsx` | 3h |
| 高级搜索界面 | `datapanel/SearchTab.tsx` | 4h |

**交付物**: 元数据可视化 + 高级搜索 UI

---

## 八、预期效果对比

### 改进前

```
用户: 我有哪些与重庆相关的数据？
Agent: 您的文件列表：
  - 重庆耕地.shp (2.3MB)
  - buffer_a3f2.geojson (3.1MB)
  - 重庆耕地.dbf (1.2MB)
  - 四川林地.geojson (1.1MB)  ← 不相关
  ...（杂乱无章）
```

### 改进后

```
用户: 我有哪些与重庆相关的数据？
Agent: 📁 找到 5 个与重庆相关的数据集

📥 原始数据 (1 个)
  • 重庆耕地.shp (2.3MB) [重庆市, 西南] — 2026-03-25

📊 分析结果 (3 个)
  • buffer_重庆耕地_a3f2.geojson (3.1MB) — 缓冲区分析
  • ffi_result_b7c1.geojson (2.8MB) — 碎片化指数计算
  • optimized_layout_c9d4.geojson (2.9MB) — DRL优化

📈 可视化 (1 个)
  • heatmap_f2g6.html (1.2MB) — 热力图

提示：这些数据来自 3 次分析流程，最近一次是 2026-03-28 的 DRL 优化。
```

---

## 九、扩展方向

### 9.1 数据血缘可视化

基于 `lineage_metadata`，构建交互式血缘图：
- 上游数据源追溯
- 下游影响分析
- 转换过程可视化

### 9.2 数据质量评分

集成 GovernanceToolset，自动评估：
- 完整性评分
- 精度等级
- 时效性检查

### 9.3 智能推荐

基于元数据相似度推荐：
- "与此数据相关的其他数据集"
- "常用的分析流程"
- "相似场景的案例"

---

## 十、总结

本元数据管理体系通过 **四层架构** + **四类元数据** + **三大服务**，实现了：

1. **自动化**: 上传/生成时自动提取和增强元数据
2. **结构化**: JSONB 灵活存储 + GIN 索引高效查询
3. **语义化**: 地区标签 + 领域分类 + 质量评分
4. **可追溯**: 完整血缘关系 + 版本管理

**核心价值**:
- 解决"我有哪些数据"的杂乱问题 → 分类展示
- 解决"与XX相关的数据"的不精确问题 → 地区标签匹配
- 解决数据来源不清问题 → source_type 标记
- 为数据治理、质量管理、智能推荐奠定基础

**下一步**: 用户审阅架构方案，确定实施范围和优先级。
