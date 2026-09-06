SELECT d.nameenglish AS district_name,
       COUNT(*) AS bus_shelter_count
FROM public.udm_district AS d
JOIN public.udm_busstopshelter AS s ON ST_Intersects(d.shape, s.shape)
GROUP BY d.nameenglish
ORDER BY d.nameenglish
LIMIT 1000;
