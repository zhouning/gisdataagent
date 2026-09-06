SELECT construction_status, COUNT(*) AS plot_count
FROM public.udm_plot
GROUP BY construction_status
ORDER BY construction_status
LIMIT 1000;
