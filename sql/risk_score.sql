-- Compound Flood-Risk Score Calculation for Rio Cauca Basin
--
-- Scoring Weights:
-- 1. River Level Score Weight: 0.50 (Most critical indicator for riverine flooding)
-- 2. Soil Saturation Score Weight: 0.25 (Indicates land vulnerability/pre-saturation)
-- 3. Rainfall Score Weight: 0.25 (Active storm input)
--
-- Thresholds & Mappings:
-- - Rainfall Score: Clamped ratio of precipitation to 25.0 mm (representing extreme hourly rainfall).
-- - Soil Saturation Score: The raw saturation index (clamped to [0.0, 1.0]).
-- - River Level Score: Clamped ratio of current level to alert threshold level.
-- - Risk Grade:
--   * Score >= 0.8: RED ALERT (EXTREME RISK)
--   * Score >= 0.6: ORANGE ALERT (HIGH RISK)
--   * Score >= 0.4: YELLOW ALERT (MODERATE RISK)
--   * ELSE: GREEN (LOW RISK)

WITH latest_rain AS (
  SELECT 
    municipality,
    timestamp,
    precipitation_mm,
    ROW_NUMBER() OVER(PARTITION BY municipality ORDER BY timestamp DESC) as rn
  FROM unified_feeds.rainfall
  WHERE basin = 'Rio Cauca'
),
latest_soil AS (
  SELECT 
    municipality,
    timestamp,
    saturation_index,
    ROW_NUMBER() OVER(PARTITION BY municipality ORDER BY timestamp DESC) as rn
  FROM unified_feeds.soil_saturation
  WHERE basin = 'Rio Cauca'
),
latest_gauge AS (
  SELECT 
    basin,
    SAFE_CAST(reading_time AS TIMESTAMP) as reading_time,
    river_level_m,
    alert_threshold_m,
    ROW_NUMBER() OVER(PARTITION BY basin ORDER BY SAFE_CAST(reading_time AS TIMESTAMP) DESC) as rn
  FROM google_sheets.rapidagent
  WHERE basin = 'Rio Cauca'
),
joined_metrics AS (
  SELECT
    p.municipality,
    p.population,
    r.precipitation_mm,
    s.saturation_index,
    g.river_level_m,
    g.alert_threshold_m
  FROM unified_feeds.municipality_population p
  LEFT JOIN latest_rain r ON p.municipality = r.municipality AND r.rn = 1
  LEFT JOIN latest_soil s ON p.municipality = s.municipality AND s.rn = 1
  LEFT JOIN latest_gauge g ON p.basin = g.basin AND g.rn = 1
  WHERE p.basin = 'Rio Cauca'
),
scored_metrics AS (
  SELECT
    municipality,
    population,
    precipitation_mm,
    saturation_index,
    river_level_m,
    alert_threshold_m,
    -- Calculate individual scores clamped between 0.0 and 1.0
    LEAST(1.0, GREATEST(0.0, SAFE_DIVIDE(precipitation_mm, 25.0))) as rainfall_score,
    LEAST(1.0, GREATEST(0.0, COALESCE(saturation_index, 0.0))) as soil_saturation_score,
    LEAST(1.0, GREATEST(0.0, SAFE_DIVIDE(river_level_m, alert_threshold_m))) as river_level_score
  FROM joined_metrics
)
SELECT
  municipality,
  population,
  precipitation_mm,
  saturation_index,
  river_level_m,
  alert_threshold_m,
  ROUND(rainfall_score, 2) as rainfall_score,
  ROUND(soil_saturation_score, 2) as soil_saturation_score,
  ROUND(river_level_score, 2) as river_level_score,
  ROUND((0.25 * rainfall_score) + (0.25 * soil_saturation_score) + (0.50 * river_level_score), 2) as compound_score,
  CASE
    WHEN ((0.25 * rainfall_score) + (0.25 * soil_saturation_score) + (0.50 * river_level_score)) >= 0.8 THEN 'RED ALERT (EXTREME RISK)'
    WHEN ((0.25 * rainfall_score) + (0.25 * soil_saturation_score) + (0.50 * river_level_score)) >= 0.6 THEN 'ORANGE ALERT (HIGH RISK)'
    WHEN ((0.25 * rainfall_score) + (0.25 * soil_saturation_score) + (0.50 * river_level_score)) >= 0.4 THEN 'YELLOW ALERT (MODERATE RISK)'
    ELSE 'GREEN (LOW RISK)'
  END as risk_grade
FROM scored_metrics
ORDER BY compound_score DESC;
