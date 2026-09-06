SELECT d.nameenglish AS district_name,
       COUNT(*) AS building_count
FROM public.udm_district AS d
JOIN public.udm_building AS b ON ST_Intersects(d.shape, b.shape)
GROUP BY d.nameenglish
ORDER BY d.nameenglish
LIMIT 1000;
