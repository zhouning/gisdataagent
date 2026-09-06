SELECT adek_sch_municipality_en AS municipality,
       COUNT(*) AS school_count,
       SUM(adek_sch_capacity) AS total_school_capacity
FROM public.poi_adek_schools_locations
GROUP BY adek_sch_municipality_en
ORDER BY adek_sch_municipality_en
LIMIT 1000;
