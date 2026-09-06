SELECT sportfacilitytype, sportstype,
       COUNT(*) AS sport_facility_count
FROM public.udm_sportfacilities
GROUP BY sportfacilitytype, sportstype
ORDER BY sportfacilitytype, sportstype
LIMIT 1000;
