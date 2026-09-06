SELECT physicalstatus, COUNT(*) AS building_count
FROM public.udm_building
GROUP BY physicalstatus
ORDER BY physicalstatus
LIMIT 1000;
