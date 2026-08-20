WITH bounds AS (
    SELECT ST_Transform(ST_MakeEnvelope(54.2971553,24.2810331,54.7659108,24.601854,4326),32640) AS geom
), pipeline_references AS MATERIALIZED (
    SELECT v.endpoint_role, UPPER(BTRIM(v.reference_value)) AS reference_norm
    FROM layer.st_pipeline t CROSS JOIN bounds b
    CROSS JOIN LATERAL (VALUES ('asset_before'::text,t.asset_before),('asset_after'::text,t.asset_after)) v(endpoint_role,reference_value)
    WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom)
      AND NULLIF(BTRIM(v.reference_value),'') IS NOT NULL
      AND UPPER(BTRIM(v.reference_value)) NOT IN ('NC','N/C','N.A','N/A','NA','NONE','NULL','UNKNOWN','NOT CONNECTED','NOT APPLICABLE','0','-','NIL')
), facility_identifiers AS MATERIALIZED (
    SELECT DISTINCT 'inlet'::text facility_role, v.identifier_kind, UPPER(BTRIM(v.identifier_value)) identifier_norm FROM layer.st_inlet t CROSS JOIN bounds b CROSS JOIN LATERAL (VALUES ('unitid'::text,t.unitid),('uid'::text,t.uid)) v(identifier_kind,identifier_value) WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom) AND NULLIF(BTRIM(v.identifier_value),'') IS NOT NULL
    UNION ALL SELECT DISTINCT 'catchbasin', v.identifier_kind, UPPER(BTRIM(v.identifier_value)) FROM layer.st_catchbasin t CROSS JOIN bounds b CROSS JOIN LATERAL (VALUES ('unitid'::text,t.unitid),('uid'::text,t.uid)) v(identifier_kind,identifier_value) WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom) AND NULLIF(BTRIM(v.identifier_value),'') IS NOT NULL
    UNION ALL SELECT DISTINCT 'sw_node', v.identifier_kind, UPPER(BTRIM(v.identifier_value)) FROM layer.st_sw_node t CROSS JOIN bounds b CROSS JOIN LATERAL (VALUES ('unitid'::text,t.unitid),('uid'::text,t.uid)) v(identifier_kind,identifier_value) WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom) AND NULLIF(BTRIM(v.identifier_value),'') IS NOT NULL
    UNION ALL SELECT DISTINCT 'sw_junction', v.identifier_kind, UPPER(BTRIM(v.identifier_value)) FROM layer.st_sw_junction t CROSS JOIN bounds b CROSS JOIN LATERAL (VALUES ('unitid'::text,t.unitid),('uid'::text,t.uid)) v(identifier_kind,identifier_value) WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom) AND NULLIF(BTRIM(v.identifier_value),'') IS NOT NULL
    UNION ALL SELECT DISTINCT 'outfall', v.identifier_kind, UPPER(BTRIM(v.identifier_value)) FROM layer.st_outfall t CROSS JOIN bounds b CROSS JOIN LATERAL (VALUES ('unitid'::text,t.unitid),('uid'::text,t.uid)) v(identifier_kind,identifier_value) WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom) AND NULLIF(BTRIM(v.identifier_value),'') IS NOT NULL
    UNION ALL SELECT DISTINCT 'ps_pump', v.identifier_kind, UPPER(BTRIM(v.identifier_value)) FROM layer.st_ps_pump t CROSS JOIN bounds b CROSS JOIN LATERAL (VALUES ('unitid'::text,t.unitid),('uid'::text,t.uid)) v(identifier_kind,identifier_value) WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom) AND NULLIF(BTRIM(v.identifier_value),'') IS NOT NULL
    UNION ALL SELECT DISTINCT 'pumpingstationstructure', v.identifier_kind, UPPER(BTRIM(v.identifier_value)) FROM layer.st_sw_pumpingstationstructure t CROSS JOIN bounds b CROSS JOIN LATERAL (VALUES ('unitid'::text,t.unitid),('uid'::text,t.uid)) v(identifier_kind,identifier_value) WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom) AND NULLIF(BTRIM(v.identifier_value),'') IS NOT NULL
    UNION ALL SELECT DISTINCT 'reservoirstructure', v.identifier_kind, UPPER(BTRIM(v.identifier_value)) FROM layer.st_sw_reservoirstructure t CROSS JOIN bounds b CROSS JOIN LATERAL (VALUES ('unitid'::text,t.unitid),('uid'::text,t.uid)) v(identifier_kind,identifier_value) WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom) AND NULLIF(BTRIM(v.identifier_value),'') IS NOT NULL
    UNION ALL SELECT DISTINCT 'soakaway', v.identifier_kind, UPPER(BTRIM(v.identifier_value)) FROM layer.st_soakaway t CROSS JOIN bounds b CROSS JOIN LATERAL (VALUES ('unitid'::text,t.unitid),('uid'::text,t.uid)) v(identifier_kind,identifier_value) WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom) AND NULLIF(BTRIM(v.identifier_value),'') IS NOT NULL
    UNION ALL SELECT DISTINCT 'chamber', v.identifier_kind, UPPER(BTRIM(v.identifier_value)) FROM layer.st_chamber t CROSS JOIN bounds b CROSS JOIN LATERAL (VALUES ('unitid'::text,t.unitid),('uid'::text,t.uid)) v(identifier_kind,identifier_value) WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom) AND NULLIF(BTRIM(v.identifier_value),'') IS NOT NULL
    UNION ALL SELECT DISTINCT 'collectivetank', v.identifier_kind, UPPER(BTRIM(v.identifier_value)) FROM layer.st_collectivetank t CROSS JOIN bounds b CROSS JOIN LATERAL (VALUES ('unitid'::text,t.unitid),('uid'::text,t.uid)) v(identifier_kind,identifier_value) WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom) AND NULLIF(BTRIM(v.identifier_value),'') IS NOT NULL
    UNION ALL SELECT DISTINCT 'dischargechamber', v.identifier_kind, UPPER(BTRIM(v.identifier_value)) FROM layer.st_dischargechamber t CROSS JOIN bounds b CROSS JOIN LATERAL (VALUES ('unitid'::text,t.unitid),('uid'::text,t.uid)) v(identifier_kind,identifier_value) WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom) AND NULLIF(BTRIM(v.identifier_value),'') IS NOT NULL
    UNION ALL SELECT DISTINCT 'gratedchanneldrainage', v.identifier_kind, UPPER(BTRIM(v.identifier_value)) FROM layer.st_gratedchanneldrainage t CROSS JOIN bounds b CROSS JOIN LATERAL (VALUES ('unitid'::text,t.unitid),('uid'::text,t.uid)) v(identifier_kind,identifier_value) WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom) AND NULLIF(BTRIM(v.identifier_value),'') IS NOT NULL
    UNION ALL SELECT DISTINCT 'petrolinterceptor', v.identifier_kind, UPPER(BTRIM(v.identifier_value)) FROM layer.st_petrolinterceptor t CROSS JOIN bounds b CROSS JOIN LATERAL (VALUES ('unitid'::text,t.unitid),('uid'::text,t.uid)) v(identifier_kind,identifier_value) WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom) AND NULLIF(BTRIM(v.identifier_value),'') IS NOT NULL
    UNION ALL SELECT DISTINCT 'pond', v.identifier_kind, UPPER(BTRIM(v.identifier_value)) FROM layer.st_pond t CROSS JOIN bounds b CROSS JOIN LATERAL (VALUES ('unitid'::text,t.unitid),('uid'::text,t.uid)) v(identifier_kind,identifier_value) WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom) AND NULLIF(BTRIM(v.identifier_value),'') IS NOT NULL
    UNION ALL SELECT DISTINCT 'ps_wet_well_area', v.identifier_kind, UPPER(BTRIM(v.identifier_value)) FROM layer.st_ps_wet_well_area t CROSS JOIN bounds b CROSS JOIN LATERAL (VALUES ('unitid'::text,t.unitid),('uid'::text,t.uid)) v(identifier_kind,identifier_value) WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom) AND NULLIF(BTRIM(v.identifier_value),'') IS NOT NULL
    UNION ALL SELECT DISTINCT 'sw_cappedend', v.identifier_kind, UPPER(BTRIM(v.identifier_value)) FROM layer.st_sw_cappedend t CROSS JOIN bounds b CROSS JOIN LATERAL (VALUES ('unitid'::text,t.unitid),('uid'::text,t.uid)) v(identifier_kind,identifier_value) WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom) AND NULLIF(BTRIM(v.identifier_value),'') IS NOT NULL
    UNION ALL SELECT DISTINCT 'sw_valve', v.identifier_kind, UPPER(BTRIM(v.identifier_value)) FROM layer.st_sw_valve t CROSS JOIN bounds b CROSS JOIN LATERAL (VALUES ('unitid'::text,t.unitid),('uid'::text,t.uid)) v(identifier_kind,identifier_value) WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom) AND NULLIF(BTRIM(v.identifier_value),'') IS NOT NULL
), dimensions AS (
    SELECT e.endpoint_role, f.facility_role, k.identifier_kind
    FROM (VALUES ('asset_before'::text),('asset_after'::text)) e(endpoint_role)
    CROSS JOIN (VALUES ('inlet'::text),('catchbasin'::text),('sw_node'::text),('sw_junction'::text),('outfall'::text),('ps_pump'::text),('pumpingstationstructure'::text),('reservoirstructure'::text),('soakaway'::text),('chamber'::text),('collectivetank'::text),('dischargechamber'::text),('gratedchanneldrainage'::text),('petrolinterceptor'::text),('pond'::text),('ps_wet_well_area'::text),('sw_cappedend'::text),('sw_valve'::text)) f(facility_role)
    CROSS JOIN (VALUES ('unitid'::text),('uid'::text)) k(identifier_kind)
), totals AS (
    SELECT endpoint_role, COUNT(*)::bigint valid_reference_count FROM pipeline_references GROUP BY endpoint_role
), role_matches AS (
    SELECT r.endpoint_role, f.facility_role, f.identifier_kind, COUNT(*)::bigint matched_reference_count
    FROM pipeline_references r JOIN facility_identifiers f ON f.identifier_norm = r.reference_norm
    GROUP BY r.endpoint_role,f.facility_role,f.identifier_kind
), any_ids AS (
    SELECT DISTINCT identifier_norm FROM facility_identifiers
), any_matches AS (
    SELECT r.endpoint_role, COUNT(*)::bigint matched_any_identifier_count
    FROM pipeline_references r JOIN any_ids a ON a.identifier_norm = r.reference_norm
    GROUP BY r.endpoint_role
)
SELECT d.endpoint_role,d.facility_role,d.identifier_kind,t.valid_reference_count,
       COALESCE(m.matched_reference_count,0)::bigint AS matched_reference_count,
       ROUND(100.0*COALESCE(m.matched_reference_count,0)/NULLIF(t.valid_reference_count,0),6)::double precision AS matched_percent,
       COALESCE(a.matched_any_identifier_count,0)::bigint AS matched_any_identifier_count,
       ROUND(100.0*COALESCE(a.matched_any_identifier_count,0)/NULLIF(t.valid_reference_count,0),6)::double precision AS matched_any_identifier_percent
FROM dimensions d JOIN totals t USING(endpoint_role) LEFT JOIN role_matches m USING(endpoint_role,facility_role,identifier_kind) LEFT JOIN any_matches a USING(endpoint_role)
ORDER BY d.endpoint_role,d.facility_role,d.identifier_kind;
