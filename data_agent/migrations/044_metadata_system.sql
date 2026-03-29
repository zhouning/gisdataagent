-- Migration 044: Metadata Management System
-- 元数据管理体系 - 完整四层架构

-- Step 1: 创建新表 agent_data_assets
CREATE TABLE IF NOT EXISTS agent_data_assets (
    id SERIAL PRIMARY KEY,
    asset_uuid UUID DEFAULT gen_random_uuid() UNIQUE,
    asset_name VARCHAR(255) NOT NULL,
    display_name VARCHAR(255),

    -- 四层元数据 (JSONB)
    technical_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    business_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    operational_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    lineage_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- 所有权与权限
    owner_username VARCHAR(100) NOT NULL,
    team_id INTEGER REFERENCES agent_teams(id),
    is_shared BOOLEAN DEFAULT false,
    access_level VARCHAR(20) DEFAULT 'private',

    -- 时间戳
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    -- 约束
    CONSTRAINT valid_technical_metadata CHECK (jsonb_typeof(technical_metadata) = 'object'),
    CONSTRAINT valid_business_metadata CHECK (jsonb_typeof(business_metadata) = 'object'),
    CONSTRAINT valid_operational_metadata CHECK (jsonb_typeof(operational_metadata) = 'object'),
    CONSTRAINT valid_lineage_metadata CHECK (jsonb_typeof(lineage_metadata) = 'object')
);

-- Step 2: 创建 GIN 索引支持 JSONB 查询
CREATE INDEX IF NOT EXISTS idx_assets_technical_meta ON agent_data_assets USING GIN (technical_metadata);
CREATE INDEX IF NOT EXISTS idx_assets_business_meta ON agent_data_assets USING GIN (business_metadata);
CREATE INDEX IF NOT EXISTS idx_assets_operational_meta ON agent_data_assets USING GIN (operational_metadata);
CREATE INDEX IF NOT EXISTS idx_assets_lineage_meta ON agent_data_assets USING GIN (lineage_metadata);

-- 常用查询索引
CREATE INDEX IF NOT EXISTS idx_assets_owner ON agent_data_assets(owner_username);
CREATE INDEX IF NOT EXISTS idx_assets_created ON agent_data_assets(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_assets_name ON agent_data_assets(asset_name);

-- Step 3: 创建元数据模式表
CREATE TABLE IF NOT EXISTS agent_metadata_schemas (
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
            'backend', COALESCE(storage_backend, 'local'),
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
            'columns', COALESCE(column_schema, '[]'::jsonb),
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
            'keywords', COALESCE(tags, '[]'::jsonb)
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
            'type', 'unknown'
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
FROM agent_data_catalog
WHERE NOT EXISTS (
    SELECT 1 FROM agent_data_assets WHERE agent_data_assets.asset_name = agent_data_catalog.asset_name
);

-- Step 5: 预置元数据模式
INSERT INTO agent_metadata_schemas (domain, schema_definition) VALUES
('LAND_USE', '{"attributes": [{"name": "region_tags", "type": "array", "required": true}, {"name": "quality_score", "type": "number", "required": false, "default": 0.0}]}'::jsonb),
('ELEVATION', '{"attributes": [{"name": "vertical_datum", "type": "string", "required": true}, {"name": "resolution", "type": "string", "required": true}]}'::jsonb),
('POPULATION', '{"attributes": [{"name": "census_year", "type": "number", "required": true}, {"name": "unit", "type": "string", "required": true}]}'::jsonb)
ON CONFLICT (domain) DO NOTHING;
