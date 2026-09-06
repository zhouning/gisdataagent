SELECT municipalityname,
       AVG(buildingnumberoffloors) AS average_floor_count
FROM public.udm_building
GROUP BY municipalityname
ORDER BY municipalityname
LIMIT 1000;
