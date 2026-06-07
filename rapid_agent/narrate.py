import sys
import json
import subprocess

def run_query():
    # Read query
    with open("sql/risk_score.sql", "r", encoding="utf-8") as f:
        query = f.read()
    
    # Run bq query with json format
    cmd = 'bq query --project_id=centinela-498622 --use_legacy_sql=false --quiet --format=json'
    res = subprocess.run(cmd, shell=True, input=query.encode('utf-8'), capture_output=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.decode('utf-8', errors='replace'))
        
    # Clean output to ensure valid JSON (remove possible gcloud warnings or headers)
    for enc in ['cp1252', 'utf-8', 'latin-1']:
        try:
            output = res.stdout.decode(enc).strip()
            json_start = output.find("[")
            if json_start != -1:
                parsed = json.loads(output[json_start:])
                return parsed
        except Exception:
            continue
            
    # Fallback if all failed
    output = res.stdout.decode('utf-8', errors='replace').strip()
    json_start = output.find("[")
    if json_start != -1:
        output = output[json_start:]
    return json.loads(output)

def narrate_results():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    data = run_query()
    
    print("=================================================================================")
    print("                                  SQL OUTPUT                                     ")
    print("=================================================================================")
    print(f"{'Municipality':<15} | {'Rain (mm)':<10} | {'Soil Sat':<8} | {'River (m)':<9} | {'Threshold':<9} | {'Score':<5} | {'Risk Grade':<25}")
    print("-" * 95)
    
    narratives = []
    
    for row in data:
        # Correct encoding artifact for Jamundí if present
        muni = row['municipality']
        if muni.startswith('Jamund'):
            muni = 'Jamundí'
        rain = float(row['precipitation_mm'])
        soil = float(row['saturation_index'])
        river = float(row['river_level_m'])
        thresh = float(row['alert_threshold_m'])
        score = float(row['compound_score'])
        grade = row['risk_grade']
        
        print(f"{muni:<15} | {rain:<10.1f} | {soil:<8.2f} | {river:<9.1f} | {thresh:<9.1f} | {score:<5.2f} | {grade:<25}")
        
        # Build individual narrative
        muni_narrative = (
            f"- {muni} is on {grade} with a compound score of {score:.2f}. "
            f"Its risk is driven by a river level of {river:.1f} m (threshold: {thresh:.1f} m, score: {row['river_level_score']}), "
            f"soil saturation index of {soil:.2f}, and active rainfall of {rain:.1f} mm."
        )
        narratives.append(muni_narrative)
        
    print("\n" + "=" * 81)
    print("                                AGENT NARRATION                                  ")
    print("=" * 81)
    print("Rio Cauca basin compound flood-risk narration:")
    print("\n".join(narratives))
    print("=================================================================================")

if __name__ == "__main__":
    narrate_results()
