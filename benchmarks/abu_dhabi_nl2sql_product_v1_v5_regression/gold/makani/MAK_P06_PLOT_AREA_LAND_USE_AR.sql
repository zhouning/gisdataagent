SELECT primaryuseengdesc,
       SUM(plannedareametric) AS total_planned_area_sqm
FROM public.udm_plot
GROUP BY primaryuseengdesc
ORDER BY primaryuseengdesc
LIMIT 1000;
