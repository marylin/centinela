-- Hourly-averaged rainfall for one basin over the last 48 hours, oldest
-- first. Source: live Google Weather readings recorded by the API on each
-- production weather refresh (genuinely real, accumulating series).
SELECT
  TIMESTAMP_TRUNC(timestamp, HOUR) AS hour,
  ROUND(AVG(precipitation_mm), 2) AS precipitation_mm
FROM unified_feeds.rainfall
WHERE basin = 'Rio Cauca'
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)
GROUP BY hour
ORDER BY hour
LIMIT 60
