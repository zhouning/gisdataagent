SELECT municipalityname,
       SUM(ST_Area(shape::geography)) / 1000000.0 AS total_area_sqkm
FROM public.udm_district
WHERE shape IS NOT NULL
GROUP BY municipalityname
ORDER BY municipalityname
LIMIT 1000;
