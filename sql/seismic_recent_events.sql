-- Recent raw USGS events: M4.5+, last 48 hours, newest first, max 20.
-- Reads the raw-events table synced by the usgs_raw_events Fivetran connector.
SELECT
  id,
  magnitude,
  place,
  time,
  latitude,
  longitude,
  depth_km
FROM usgs_raw_events.events
WHERE magnitude >= 4.5
  AND time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)
ORDER BY time DESC
LIMIT 20
