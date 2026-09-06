SELECT municipalityname, COUNT(*) AS park_count
FROM public.udm_park
GROUP BY municipalityname
ORDER BY municipalityname
LIMIT 1000;
