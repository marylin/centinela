-- Daily GloFAS river discharge for one basin over the last 31 days, oldest
-- first, averaged across the basin's monitored places. MODEL data (GloFAS v4
-- via Open-Meteo through the global_hydro Fivetran connector) — label it.
-- NOTE: Fivetran's naming strategy renders the connector's discharge_m3s
-- column as discharge_m_3_s in BigQuery.
SELECT
  date,
  ROUND(AVG(discharge_m_3_s), 1) AS discharge_m3s
FROM global_hydro.river_discharge
WHERE basin_id = 'rio_cauca'
  AND date >= DATE_SUB(CURRENT_DATE(), INTERVAL 31 DAY)
GROUP BY date
ORDER BY date
LIMIT 60
