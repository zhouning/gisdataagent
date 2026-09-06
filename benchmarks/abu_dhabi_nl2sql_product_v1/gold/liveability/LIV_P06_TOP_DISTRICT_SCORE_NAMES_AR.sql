SELECT d.name_en, AVG(s.overall_score) AS average_overall_score
FROM public.fact_district_scores AS s
JOIN public.dim_districts AS d ON d.district_id = s.district_id
GROUP BY d.name_en
ORDER BY average_overall_score DESC NULLS LAST, d.name_en
LIMIT 10;
