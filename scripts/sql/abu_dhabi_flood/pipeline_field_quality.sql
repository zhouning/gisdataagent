WITH bounds AS (
    SELECT ST_Transform(ST_MakeEnvelope(54.2971553,24.2810331,54.7659108,24.601854,4326),32640) AS geom
), target AS MATERIALIZED (
    SELECT
        NULLIF(BTRIM(t.unitid),'') AS unitid,
        NULLIF(BTRIM(t.unitid2),'') AS unitid2,
        NULLIF(BTRIM(t.asset_before),'') AS asset_before,
        NULLIF(BTRIM(t.asset_after),'') AS asset_after,
        NULLIF(BTRIM(t.outfallid),'') AS outfallid,
        t.pipe_diameter,
        t.invert_level_upstream,
        t.invert_level_downstream
    FROM layer.st_pipeline t CROSS JOIN bounds b
    WHERE t.geom && b.geom AND ST_Intersects(t.geom,b.geom)
), normalized AS (
    SELECT *,
        UPPER(asset_before) NOT IN ('NC','N/C','N.A','N/A','NA','NONE','NULL','UNKNOWN','NOT CONNECTED','NOT APPLICABLE','0','-','NIL') AS asset_before_valid,
        UPPER(asset_after) NOT IN ('NC','N/C','N.A','N/A','NA','NONE','NULL','UNKNOWN','NOT CONNECTED','NOT APPLICABLE','0','-','NIL') AS asset_after_valid,
        UPPER(outfallid) NOT IN ('NC','N/C','N.A','N/A','NA','NONE','NULL','UNKNOWN','NOT CONNECTED','NOT APPLICABLE','0','-','NIL') AS outfallid_valid
    FROM target
)
SELECT
    COUNT(*)::bigint AS target_pipeline_count,
    COUNT(unitid)::bigint AS unitid_present_count,
    COUNT(DISTINCT unitid)::bigint AS unitid_distinct_count,
    COUNT(unitid2)::bigint AS unitid2_present_count,
    COUNT(DISTINCT unitid2)::bigint AS unitid2_distinct_count,
    COUNT(asset_before)::bigint AS asset_before_present_count,
    COUNT(*) FILTER (WHERE asset_before IS NOT NULL AND asset_before_valid)::bigint AS asset_before_valid_reference_count,
    COUNT(*) FILTER (WHERE asset_before IS NOT NULL AND NOT asset_before_valid)::bigint AS asset_before_sentinel_count,
    COUNT(asset_after)::bigint AS asset_after_present_count,
    COUNT(*) FILTER (WHERE asset_after IS NOT NULL AND asset_after_valid)::bigint AS asset_after_valid_reference_count,
    COUNT(*) FILTER (WHERE asset_after IS NOT NULL AND NOT asset_after_valid)::bigint AS asset_after_sentinel_count,
    COUNT(*) FILTER (WHERE outfallid IS NOT NULL AND outfallid_valid)::bigint AS outfallid_valid_reference_count,
    COUNT(*) FILTER (WHERE pipe_diameter > 0)::bigint AS positive_diameter_count,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY pipe_diameter) FILTER (WHERE pipe_diameter > 0)::double precision AS diameter_median_source_value,
    COUNT(*) FILTER (WHERE invert_level_upstream IS NOT NULL AND invert_level_downstream IS NOT NULL)::bigint AS both_inverts_present_count,
    COUNT(*) FILTER (WHERE invert_level_upstream BETWEEN -100 AND 200 AND invert_level_downstream BETWEEN -100 AND 200)::bigint AS both_inverts_candidate_plausible_count
FROM normalized;
