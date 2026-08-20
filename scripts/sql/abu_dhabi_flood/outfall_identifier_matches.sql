WITH bounds AS (
    SELECT ST_Transform(ST_MakeEnvelope(54.2971553,24.2810331,54.7659108,24.601854,4326),32640) AS geom
), asset_references AS MATERIALIZED (
    SELECT 'pipeline'::text asset_role, UPPER(BTRIM(t.outfallid)) reference_norm FROM layer.st_pipeline t CROSS JOIN bounds b WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom) AND NULLIF(BTRIM(t.outfallid),'') IS NOT NULL AND UPPER(BTRIM(t.outfallid)) NOT IN ('NC','N/C','N.A','N/A','NA','NONE','NULL','UNKNOWN','NOT CONNECTED','NOT APPLICABLE','0','-','NIL')
    UNION ALL SELECT 'inlet', UPPER(BTRIM(t.outfallid)) FROM layer.st_inlet t CROSS JOIN bounds b WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom) AND NULLIF(BTRIM(t.outfallid),'') IS NOT NULL AND UPPER(BTRIM(t.outfallid)) NOT IN ('NC','N/C','N.A','N/A','NA','NONE','NULL','UNKNOWN','NOT CONNECTED','NOT APPLICABLE','0','-','NIL')
    UNION ALL SELECT 'catchbasin', UPPER(BTRIM(t.outfallid)) FROM layer.st_catchbasin t CROSS JOIN bounds b WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom) AND NULLIF(BTRIM(t.outfallid),'') IS NOT NULL AND UPPER(BTRIM(t.outfallid)) NOT IN ('NC','N/C','N.A','N/A','NA','NONE','NULL','UNKNOWN','NOT CONNECTED','NOT APPLICABLE','0','-','NIL')
    UNION ALL SELECT 'sw_junction', UPPER(BTRIM(t.outfallid)) FROM layer.st_sw_junction t CROSS JOIN bounds b WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom) AND NULLIF(BTRIM(t.outfallid),'') IS NOT NULL AND UPPER(BTRIM(t.outfallid)) NOT IN ('NC','N/C','N.A','N/A','NA','NONE','NULL','UNKNOWN','NOT CONNECTED','NOT APPLICABLE','0','-','NIL')
), identifiers AS MATERIALIZED (
    SELECT DISTINCT v.identifier_kind,UPPER(BTRIM(v.identifier_value)) identifier_norm
    FROM layer.st_outfall t CROSS JOIN bounds b CROSS JOIN LATERAL (VALUES ('unitid'::text,t.unitid),('uid'::text,t.uid),('outfall_name'::text,t.outfall_name),('mainassetname'::text,t.mainassetname)) v(identifier_kind,identifier_value)
    WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom) AND NULLIF(BTRIM(v.identifier_value),'') IS NOT NULL
), dimensions AS (
    SELECT a.asset_role,k.identifier_kind FROM (VALUES ('pipeline'::text),('inlet'::text),('catchbasin'::text),('sw_junction'::text)) a(asset_role) CROSS JOIN (VALUES ('unitid'::text),('uid'::text),('outfall_name'::text),('mainassetname'::text)) k(identifier_kind)
), totals AS (SELECT asset_role,COUNT(*)::bigint valid_reference_count FROM asset_references GROUP BY asset_role),
matches AS (SELECT r.asset_role,i.identifier_kind,COUNT(*)::bigint matched_reference_count FROM asset_references r JOIN identifiers i ON i.identifier_norm=r.reference_norm GROUP BY r.asset_role,i.identifier_kind),
any_ids AS (SELECT DISTINCT identifier_norm FROM identifiers),
any_matches AS (SELECT r.asset_role,COUNT(*)::bigint matched_any_identifier_count FROM asset_references r JOIN any_ids i ON i.identifier_norm=r.reference_norm GROUP BY r.asset_role)
SELECT d.asset_role,d.identifier_kind,COALESCE(t.valid_reference_count,0)::bigint AS valid_reference_count,COALESCE(m.matched_reference_count,0)::bigint AS matched_reference_count,
       CASE WHEN COALESCE(t.valid_reference_count,0)=0 THEN 0.0 ELSE ROUND(100.0*COALESCE(m.matched_reference_count,0)/t.valid_reference_count,6)::double precision END AS matched_percent,
       COALESCE(a.matched_any_identifier_count,0)::bigint AS matched_any_identifier_count,
       CASE WHEN COALESCE(t.valid_reference_count,0)=0 THEN 0.0 ELSE ROUND(100.0*COALESCE(a.matched_any_identifier_count,0)/t.valid_reference_count,6)::double precision END AS matched_any_identifier_percent
FROM dimensions d LEFT JOIN totals t USING(asset_role) LEFT JOIN matches m USING(asset_role,identifier_kind) LEFT JOIN any_matches a USING(asset_role)
ORDER BY d.asset_role,d.identifier_kind;
