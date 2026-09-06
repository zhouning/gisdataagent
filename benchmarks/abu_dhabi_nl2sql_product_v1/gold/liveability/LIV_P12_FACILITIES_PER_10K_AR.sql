WITH facility_counts AS (
  SELECT district_id, COUNT(DISTINCT facility_uuid) AS facility_count
  FROM public.dim_facilities
  GROUP BY district_id
), population_totals AS (
  SELECT district_id, SUM(total_population) AS total_population
  FROM public.fact_population
  GROUP BY district_id
)
SELECT d.name_en AS district_name,
       f.facility_count,
       p.total_population,
       f.facility_count * 10000.0 / NULLIF(p.total_population, 0) AS facilities_per_10000
FROM public.dim_districts AS d
JOIN facility_counts AS f ON f.district_id = d.district_id
JOIN population_totals AS p ON p.district_id = d.district_id
ORDER BY district_name
LIMIT 1000;
