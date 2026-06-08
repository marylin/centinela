-- Cross-Hazard Compound Risk Score Calculation for Rio Cauca Basin
--
-- Hazard Weightings:
-- 1. Flood Hazard Score (Weight: 0.40)
--    - River Level Ratio: 0.50
--    - Soil Saturation: 0.25
--    - Rainfall Ratio: 0.25
-- 2. Landslide Hazard Score (Weight: 0.30)
--    - Slope/Susceptibility Index: 0.70
--    - Soil Saturation: 0.30 (wet slopes increase landslide risk)
-- 3. Seismic Hazard Score (Weight: 0.30)
--    - Peak magnitude ratio to 7.0: 1.00
--
-- Thresholds & Mappings:
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
latest_landslide AS (
  SELECT 
    municipality,
    slope_angle_deg,
    susceptibility_index,
    ROW_NUMBER() OVER(PARTITION BY municipality ORDER BY timestamp DESC) as rn
  FROM unified_feeds.landslide
),
latest_seismic AS (
  SELECT 
    municipality,
    magnitude,
    place,
    ROW_NUMBER() OVER(PARTITION BY municipality ORDER BY time DESC) as rn
  FROM seismic_feed.seismic
  WHERE time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
    AND latitude BETWEEN 2.0 AND 5.0
    AND longitude BETWEEN -78.0 AND -75.0
),
joined_metrics AS (
  SELECT
    p.municipality,
    p.population,
    r.precipitation_mm,
    s.saturation_index,
    g.river_level_m,
    g.alert_threshold_m,
    l.slope_angle_deg,
    l.susceptibility_index,
    seis.magnitude as earthquake_magnitude
  FROM unified_feeds.municipality_population p
  LEFT JOIN latest_rain r ON p.municipality = r.municipality AND r.rn = 1
  LEFT JOIN latest_soil s ON p.municipality = s.municipality AND s.rn = 1
  LEFT JOIN latest_gauge g ON p.basin = g.basin AND g.rn = 1
  LEFT JOIN latest_landslide l ON p.municipality = l.municipality AND l.rn = 1
  LEFT JOIN latest_seismic seis ON p.municipality = seis.municipality AND seis.rn = 1
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
    slope_angle_deg,
    susceptibility_index,
    earthquake_magnitude,
    -- Calculate individual hazard input scores clamped between 0.0 and 1.0
    LEAST(1.0, GREATEST(0.0, SAFE_DIVIDE(COALESCE(precipitation_mm, 0.0), 25.0))) as rainfall_score,
    LEAST(1.0, GREATEST(0.0, COALESCE(saturation_index, 0.0))) as soil_saturation_score,
    LEAST(1.0, GREATEST(0.0, SAFE_DIVIDE(COALESCE(river_level_m, 0.0), COALESCE(alert_threshold_m, 1.0)))) as river_level_score,
    LEAST(1.0, GREATEST(0.0, COALESCE(susceptibility_index, 0.0))) as landslide_susceptibility_score,
    LEAST(1.0, GREATEST(0.0, SAFE_DIVIDE(COALESCE(earthquake_magnitude, 0.0), 7.0))) as seismic_intensity_score
  FROM joined_metrics
),
hazard_scores AS (
  SELECT
    municipality,
    population,
    precipitation_mm,
    saturation_index,
    river_level_m,
    alert_threshold_m,
    slope_angle_deg,
    susceptibility_index,
    earthquake_magnitude,
    -- Compute sub-hazard scores
    (0.25 * rainfall_score) + (0.25 * soil_saturation_score) + (0.50 * river_level_score) as flood_score,
    (0.70 * landslide_susceptibility_score) + (0.30 * soil_saturation_score) as landslide_score,
    seismic_intensity_score as seismic_score
  FROM scored_metrics
)
SELECT
  municipality,
  population,
  precipitation_mm,
  saturation_index,
  river_level_m,
  alert_threshold_m,
  slope_angle_deg,
  susceptibility_index,
  earthquake_magnitude,
  ROUND(flood_score, 2) as flood_score,
  ROUND(landslide_score, 2) as landslide_score,
  ROUND(seismic_score, 2) as seismic_score,
  ROUND((0.40 * flood_score) + (0.30 * landslide_score) + (0.30 * seismic_score), 2) as compound_score,
  CASE
    WHEN ((0.40 * flood_score) + (0.30 * landslide_score) + (0.30 * seismic_score)) >= 0.8 THEN 'RED ALERT (EXTREME RISK)'
    WHEN ((0.40 * flood_score) + (0.30 * landslide_score) + (0.30 * seismic_score)) >= 0.6 THEN 'ORANGE ALERT (HIGH RISK)'
    WHEN ((0.40 * flood_score) + (0.30 * landslide_score) + (0.30 * seismic_score)) >= 0.4 THEN 'YELLOW ALERT (MODERATE RISK)'
    ELSE 'GREEN (LOW RISK)'
  END as risk_grade,
  CASE
    WHEN flood_score >= landslide_score AND flood_score >= seismic_score THEN 'FLOOD'
    WHEN landslide_score >= flood_score AND landslide_score >= seismic_score THEN 'LANDSLIDE'
    ELSE 'SEISMIC'
  END as dominant_hazard
FROM hazard_scores
ORDER BY compound_score DESC;
