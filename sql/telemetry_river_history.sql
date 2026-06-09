-- River-level readings for one basin over the last 7 days, oldest first.
-- Source: the Fivetran-synced river-gauge sheet. The values for the demo
-- basins are seeded; the pipeline (sheet -> Fivetran -> BigQuery) is real.
SELECT
  reading_time,
  river_level_m,
  alert_threshold_m
FROM google_sheets.rapidagent
WHERE basin = 'Rio Cauca'
  AND reading_time >= DATETIME_SUB(CURRENT_DATETIME(), INTERVAL 168 HOUR)
ORDER BY reading_time
LIMIT 200
