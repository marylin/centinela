"""Smoke test: run_narration_turn via the ADK Runner (real Vertex call)."""
import json
from rapid_agent.centinela_agent import run_narration_turn

# Minimal risk data mimicking what /alert sends
sample_risk = [
    {
        "municipality": "Jamundí",
        "risk_score": 0.76,
        "rainfall_mm": 5.0,
        "river_level_m": 4.34,
        "soil_saturation": 0.95,
        "threshold": 4.0,
        "slope_angle_deg": 38.0,
        "susceptibility_index": 0.88,
        "earthquake_magnitude": 4.5,
        "flood_score": 0.73,
        "landslide_score": 0.9,
        "seismic_score": 0.64,
        "dominant_hazard": "LANDSLIDE"
    },
    {
        "municipality": "Yumbo",
        "risk_score": 0.58,
        "rainfall_mm": 3.0,
        "river_level_m": 4.34,
        "soil_saturation": 0.85,
        "threshold": 3.5,
        "slope_angle_deg": 28.0,
        "susceptibility_index": 0.65,
        "earthquake_magnitude": 2.1,
        "flood_score": 0.68,
        "landslide_score": 0.71,
        "seismic_score": 0.3,
        "dominant_hazard": "LANDSLIDE"
    },
]

print("Calling run_narration_turn via ADK Runner...")
result = run_narration_turn("rio_cauca", sample_risk)
print("\n=== RESULT ===")
print(json.dumps(result, indent=2, ensure_ascii=False))

assert "summary" in result and result["summary"], "summary is empty"
assert "broadcast" in result and result["broadcast"], "broadcast is empty"
print("\nSMOKE TEST PASSED: ADK Runner narration returned valid summary and broadcast.")
