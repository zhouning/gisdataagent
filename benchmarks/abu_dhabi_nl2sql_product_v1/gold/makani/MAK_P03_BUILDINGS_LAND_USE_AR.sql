SELECT primaryuseengdesc, COUNT(*) AS building_count
FROM public.udm_building
GROUP BY primaryuseengdesc
ORDER BY primaryuseengdesc
LIMIT 1000;
