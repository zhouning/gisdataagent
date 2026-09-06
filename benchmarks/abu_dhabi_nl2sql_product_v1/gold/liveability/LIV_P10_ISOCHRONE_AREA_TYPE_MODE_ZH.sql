SELECT facility_type, mode,
       AVG(ST_Area(geom::geography)) / 1000000.0 AS average_area_sqkm
FROM public.fact_isochrones
WHERE geom IS NOT NULL
GROUP BY facility_type, mode
ORDER BY facility_type, mode
LIMIT 1000;
