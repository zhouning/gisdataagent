SELECT district_name_en, SUM(total_population) AS total_population
FROM public.fact_population
GROUP BY district_name_en
ORDER BY total_population DESC NULLS LAST, district_name_en
LIMIT 10;
