SELECT municipalityname, COUNT(*) AS district_count
FROM public.udm_district
GROUP BY municipalityname
ORDER BY municipalityname
LIMIT 1000;
