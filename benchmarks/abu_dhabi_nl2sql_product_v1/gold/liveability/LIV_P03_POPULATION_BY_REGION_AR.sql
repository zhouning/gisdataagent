SELECT region, SUM(total_population) AS total_population
FROM public.fact_population
GROUP BY region
ORDER BY region
LIMIT 1000;
