SELECT municipality,
       SUM(ST_Area(geom::geography)::numeric) AS total_area_sqm
FROM public.dim_parks_calc_plots
WHERE geom IS NOT NULL
GROUP BY municipality
ORDER BY municipality
LIMIT 1000;
