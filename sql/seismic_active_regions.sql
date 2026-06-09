-- Active seismic regions over the last 30 days, ranked by event count.
-- Region is parsed from the USGS "place" string: the text after the last
-- comma (e.g. "120km SSW of Tonga" has no comma so the whole place is used).
SELECT
  TRIM(ARRAY_REVERSE(SPLIT(place, ','))[SAFE_OFFSET(0)]) AS region,
  COUNT(*) AS count,
  MAX(magnitude) AS max_magnitude
FROM usgs_raw_events.events
WHERE time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY region
ORDER BY count DESC, max_magnitude DESC
LIMIT 15
