SELECT category_name,
       SUM(demand_current) AS current_demand,
       SUM(existing_count) AS existing_count,
       SUM(pipeline_count) AS pipeline_count,
       SUM(needed_current) AS current_gap
FROM public.fact_facility_provision
GROUP BY category_name
ORDER BY category_name
LIMIT 1000;
