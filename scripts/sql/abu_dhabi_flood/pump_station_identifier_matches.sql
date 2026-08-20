WITH bounds AS (
    SELECT ST_Transform(ST_MakeEnvelope(54.2971553,24.2810331,54.7659108,24.601854,4326),32640) AS geom
), asset_references AS MATERIALIZED (
    SELECT UPPER(BTRIM(t.pump_station_id)) reference_norm
    FROM layer.st_ps_pump t CROSS JOIN bounds b
    WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom)
      AND NULLIF(BTRIM(t.pump_station_id),'') IS NOT NULL
      AND UPPER(BTRIM(t.pump_station_id)) NOT IN ('NC','N/C','N.A','N/A','NA','NONE','NULL','UNKNOWN','NOT CONNECTED','NOT APPLICABLE','0','-','NIL')
), identifiers AS MATERIALIZED (
    SELECT DISTINCT v.identifier_kind,UPPER(BTRIM(v.identifier_value)) identifier_norm
    FROM layer.st_sw_pumpingstationstructure t CROSS JOIN bounds b
    CROSS JOIN LATERAL (VALUES ('unitid'::text,t.unitid),('uid'::text,t.uid),('pumpingstation_name'::text,t.pumpingstation_name),('pumpstation_name'::text,t.pumpstation_name),('mainassetname'::text,t.mainassetname)) v(identifier_kind,identifier_value)
    WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom) AND NULLIF(BTRIM(v.identifier_value),'') IS NOT NULL
), dimensions AS (SELECT identifier_kind FROM (VALUES ('unitid'::text),('uid'::text),('pumpingstation_name'::text),('pumpstation_name'::text),('mainassetname'::text)) k(identifier_kind)),
total AS (SELECT COUNT(*)::bigint valid_reference_count FROM asset_references),
matches AS (SELECT i.identifier_kind,COUNT(*)::bigint matched_reference_count FROM asset_references r JOIN identifiers i ON i.identifier_norm=r.reference_norm GROUP BY i.identifier_kind),
any_ids AS (SELECT DISTINCT identifier_norm FROM identifiers),
any_match AS (SELECT COUNT(*)::bigint matched_any_identifier_count FROM asset_references r JOIN any_ids i ON i.identifier_norm=r.reference_norm)
SELECT d.identifier_kind,t.valid_reference_count,COALESCE(m.matched_reference_count,0)::bigint AS matched_reference_count,
       CASE WHEN t.valid_reference_count=0 THEN 0.0 ELSE ROUND(100.0*COALESCE(m.matched_reference_count,0)/t.valid_reference_count,6)::double precision END AS matched_percent,
       a.matched_any_identifier_count,
       CASE WHEN t.valid_reference_count=0 THEN 0.0 ELSE ROUND(100.0*a.matched_any_identifier_count/t.valid_reference_count,6)::double precision END AS matched_any_identifier_percent
FROM dimensions d CROSS JOIN total t CROSS JOIN any_match a LEFT JOIN matches m USING(identifier_kind)
ORDER BY d.identifier_kind;
