-- Governed, version-bound map publications backed by one stable Martin source.

CREATE SCHEMA IF NOT EXISTS map_serving;

CREATE TABLE IF NOT EXISTS public.agent_map_publications (
    publication_id UUID PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    asset_id INTEGER NOT NULL REFERENCES public.agent_data_assets(id) ON DELETE CASCADE,
    asset_version INTEGER NOT NULL CHECK (asset_version > 0),
    source_content_sha256 CHAR(64) NOT NULL,
    config_sha256 CHAR(64) NOT NULL,
    publication_run_id UUID NOT NULL,
    serving_kind VARCHAR(20) NOT NULL DEFAULT 'mvt',
    source_schema VARCHAR(63) NOT NULL,
    source_table VARCHAR(63) NOT NULL,
    geometry_column VARCHAR(63) NOT NULL,
    geometry_type VARCHAR(40) NOT NULL,
    geometry_srid INTEGER NOT NULL CHECK (geometry_srid > 0),
    feature_id_column VARCHAR(63) NOT NULL,
    property_allowlist JSONB NOT NULL DEFAULT '[]'::jsonb,
    data_extent JSONB NOT NULL DEFAULT '{}'::jsonb,
    display_extent JSONB NOT NULL DEFAULT '{}'::jsonb,
    min_zoom SMALLINT NOT NULL DEFAULT 0 CHECK (min_zoom BETWEEN 0 AND 30),
    max_zoom SMALLINT NOT NULL DEFAULT 20 CHECK (max_zoom BETWEEN 0 AND 30),
    max_features_per_tile INTEGER NOT NULL DEFAULT 50000
        CHECK (max_features_per_tile BETWEEN 100 AND 100000),
    style_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(20) NOT NULL DEFAULT 'building',
    error_message TEXT,
    created_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    retired_at TIMESTAMPTZ,
    CONSTRAINT ck_agent_map_publication_status
        CHECK (status IN ('pending', 'building', 'ready', 'failed', 'stale', 'retired')),
    CONSTRAINT ck_agent_map_publication_zoom_range CHECK (max_zoom >= min_zoom),
    CONSTRAINT ck_agent_map_publication_properties
        CHECK (jsonb_typeof(property_allowlist) = 'array'),
    CONSTRAINT ck_agent_map_publication_data_extent
        CHECK (jsonb_typeof(data_extent) = 'object'),
    CONSTRAINT ck_agent_map_publication_display_extent
        CHECK (jsonb_typeof(display_extent) = 'object'),
    CONSTRAINT ck_agent_map_publication_style
        CHECK (jsonb_typeof(style_config) = 'object'),
    UNIQUE (tenant_id, asset_id, asset_version, config_sha256)
);

CREATE INDEX IF NOT EXISTS idx_agent_map_publication_asset
    ON public.agent_map_publications(asset_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_map_publication_current
    ON public.agent_map_publications(asset_id, asset_version, published_at DESC)
    WHERE status = 'ready';

CREATE TABLE IF NOT EXISTS public.agent_map_publication_events (
    event_id BIGSERIAL PRIMARY KEY,
    publication_id UUID NOT NULL
        REFERENCES public.agent_map_publications(publication_id) ON DELETE CASCADE,
    event_type VARCHAR(40) NOT NULL,
    status VARCHAR(20) NOT NULL,
    actor VARCHAR(100) NOT NULL,
    publication_run_id UUID NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_agent_map_publication_event_details
        CHECK (jsonb_typeof(details) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_agent_map_publication_event_history
    ON public.agent_map_publication_events(publication_id, created_at DESC);

ALTER TABLE public.agent_map_publications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_map_publications FORCE ROW LEVEL SECURITY;

CREATE POLICY agent_map_publications_select
    ON public.agent_map_publications FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.agent_data_assets asset
            WHERE asset.id = agent_map_publications.asset_id
        )
    );

CREATE POLICY agent_map_publications_insert
    ON public.agent_map_publications FOR INSERT
    WITH CHECK (
        created_by = current_setting('app.current_user', true)
        AND EXISTS (
            SELECT 1 FROM public.agent_data_assets asset
            WHERE asset.id = agent_map_publications.asset_id
              AND (
                  asset.owner_username = current_setting('app.current_user', true)
                  OR current_setting('app.current_user_role', true) = 'admin'
              )
        )
    );

CREATE POLICY agent_map_publications_update
    ON public.agent_map_publications FOR UPDATE
    USING (
        created_by = current_setting('app.current_user', true)
        OR current_setting('app.current_user_role', true) = 'admin'
    )
    WITH CHECK (
        created_by = current_setting('app.current_user', true)
        OR current_setting('app.current_user_role', true) = 'admin'
    );

ALTER TABLE public.agent_map_publication_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_map_publication_events FORCE ROW LEVEL SECURITY;

CREATE POLICY agent_map_publication_events_select
    ON public.agent_map_publication_events FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.agent_map_publications publication
            WHERE publication.publication_id = agent_map_publication_events.publication_id
        )
    );

CREATE POLICY agent_map_publication_events_insert
    ON public.agent_map_publication_events FOR INSERT
    WITH CHECK (
        actor = current_setting('app.current_user', true)
        OR current_setting('app.current_user_role', true) = 'admin'
    );

-- Martin discovers this single function at startup. The function resolves a
-- publication internally and generates MVT only from its governed columns.
CREATE OR REPLACE FUNCTION map_serving.publication_mvt(
    z INTEGER,
    x INTEGER,
    y INTEGER,
    query_params JSON
) RETURNS BYTEA
LANGUAGE plpgsql
STABLE
STRICT
PARALLEL SAFE
SECURITY DEFINER
SET search_path = pg_catalog, public, map_serving
AS $function$
DECLARE
    requested_id UUID;
    publication RECORD;
    property_sql TEXT;
    geometry_sql TEXT;
    tile_sql TEXT;
    tile BYTEA;
    collection_type INTEGER;
BEGIN
    BEGIN
        requested_id := NULLIF(query_params->>'publication_id', '')::UUID;
    EXCEPTION WHEN invalid_text_representation THEN
        RETURN '\x'::BYTEA;
    END;

    SELECT * INTO publication
    FROM public.agent_map_publications
    WHERE publication_id = requested_id
      AND status = 'ready';

    IF NOT FOUND OR z < publication.min_zoom OR z > publication.max_zoom THEN
        RETURN '\x'::BYTEA;
    END IF;

    SELECT string_agg(format('%I', property_name), ', ' ORDER BY ordinal)
    INTO property_sql
    FROM (
        SELECT property_name, ordinal
        FROM jsonb_array_elements_text(publication.property_allowlist)
            WITH ORDINALITY AS properties(property_name, ordinal)
        WHERE property_name <> publication.feature_id_column
    ) allowed;

    IF property_sql IS NULL OR property_sql = '' THEN
        property_sql := '';
    ELSE
        property_sql := ', ' || property_sql;
    END IF;

    collection_type := CASE
        WHEN upper(publication.geometry_type) LIKE '%POLYGON%' THEN 3
        WHEN upper(publication.geometry_type) LIKE '%LINESTRING%' THEN 2
        WHEN upper(publication.geometry_type) LIKE '%POINT%' THEN 1
        ELSE 0
    END;

    IF collection_type > 0 THEN
        geometry_sql := format(
            'ST_Multi(ST_CollectionExtract(CASE WHEN ST_IsValid(%1$I) '
            'THEN ST_Force2D(%1$I) ELSE ST_MakeValid(ST_Force2D(%1$I)) END, %2$s))',
            publication.geometry_column,
            collection_type
        );
    ELSE
        geometry_sql := format(
            'CASE WHEN ST_IsValid(%1$I) THEN ST_Force2D(%1$I) '
            'ELSE ST_MakeValid(ST_Force2D(%1$I)) END',
            publication.geometry_column
        );
    END IF;

    tile_sql := format(
        'SELECT ST_AsMVT(tile, %L, 4096, ''geom'') FROM ('
        'SELECT %I::text AS feature_id%s, '
        'ST_AsMVTGeom(ST_Transform(ST_CurveToLine(%s), 3857), '
        'ST_TileEnvelope($1, $2, $3), 4096, 64, true) AS geom '
        'FROM %I.%I '
        'WHERE %I IS NOT NULL AND NOT ST_IsEmpty(%I) '
        'AND %I && ST_Transform(ST_TileEnvelope($1, $2, $3), %s) '
        'LIMIT %s) tile WHERE geom IS NOT NULL',
        'map_publication',
        publication.feature_id_column,
        property_sql,
        geometry_sql,
        publication.source_schema,
        publication.source_table,
        publication.geometry_column,
        publication.geometry_column,
        publication.geometry_column,
        publication.geometry_srid,
        publication.max_features_per_tile
    );

    EXECUTE tile_sql INTO tile USING z, x, y;
    RETURN COALESCE(tile, '\x'::BYTEA);
END
$function$;

COMMENT ON FUNCTION map_serving.publication_mvt(INTEGER, INTEGER, INTEGER, JSON)
IS '{"description":"Governed GIS Data Agent map publications","vector_layers":[{"id":"map_publication","fields":{"feature_id":"String"}}]}';

GRANT USAGE ON SCHEMA map_serving TO agent_user;
GRANT SELECT, INSERT, UPDATE ON public.agent_map_publications TO agent_user;
GRANT SELECT, INSERT ON public.agent_map_publication_events TO agent_user;
GRANT USAGE, SELECT ON SEQUENCE public.agent_map_publication_events_event_id_seq TO agent_user;
GRANT EXECUTE ON FUNCTION map_serving.publication_mvt(INTEGER, INTEGER, INTEGER, JSON)
    TO agent_user;
