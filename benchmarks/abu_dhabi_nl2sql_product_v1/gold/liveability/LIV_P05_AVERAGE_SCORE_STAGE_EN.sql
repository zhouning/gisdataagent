SELECT stage, AVG(overall_score) AS average_overall_score
FROM public.fact_district_scores
GROUP BY stage
ORDER BY stage
LIMIT 1000;
