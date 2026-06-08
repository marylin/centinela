import os
import json
import subprocess
from datetime import datetime, timezone
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from google.cloud import bigquery
from pydantic import BaseModel

# Load environment variables
load_dotenv()

# Import the existing agent logic
from rapid_agent.agent import check_and_heal_connector, get_mcp_toolset, call_with_retry

app = FastAPI(title="Centinela Backend API")

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AlertNarratives(BaseModel):
    summary: str
    broadcast: str

CONNECTORS = [
    {
        "id": "plausibly_illustrate",
        "name": "River Gauge (Google Sheets)",
        "type": "sheets"
    },
    {
        "id": "garment_dealer",
        "name": "Soil Saturation (GCS)",
        "type": "gcs"
    }
]

CONNECTOR_ID = "plausibly_illustrate"

@app.get("/risk")
def get_risk():
    """Runs the tracked risk-score SQL, returns graded risk per municipality."""
    try:
        # Read the query from the tracked SQL file
        with open("sql/risk_score.sql", "r", encoding="utf-8") as f:
            query = f.read()
            
        client = bigquery.Client(project='centinela-498622')
        query_job = client.query(query)
        rows = query_job.result()
        
        # Map fields to the frontend UI contract
        results = []
        for row in rows:
            row_dict = dict(row)
            muni = row_dict.get("municipality", "")
            if muni.startswith("Jamund"):
                muni = "Jamundí"
            results.append({
                "municipality": muni,
                "risk_score": float(row_dict.get("compound_score", 0.0) or 0.0),
                "rainfall_mm": float(row_dict.get("precipitation_mm", 0.0) or 0.0),
                "river_level_m": float(row_dict.get("river_level_m", 0.0) or 0.0),
                "soil_saturation": float(row_dict.get("saturation_index", 0.0) or 0.0),
                "threshold": float(row_dict.get("alert_threshold_m", 0.0) or 0.0)
            })
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/alert")
def get_alert():
    """Turns the current risk scores into graded alerts, incident report, and resident warning."""
    try:
        # Re-use the risk computation logic
        risk_data = get_risk()
        
        graded_alert = []
        affected_municipalities = []
        
        for muni_risk in risk_data:
            muni = muni_risk["municipality"]
            score = muni_risk["risk_score"]
            
            # Map score to severity
            if score >= 0.8:
                severity = "EXTREME"
            elif score >= 0.6:
                severity = "HIGH"
            elif score >= 0.4:
                severity = "MODERATE"
            else:
                severity = "LOW"
                
            graded_alert.append({
                "municipality": muni,
                "risk_score": score,
                "severity": severity
            })
            
            if severity in ["HIGH", "EXTREME"]:
                affected_municipalities.append(muni)
                
        # Call Gemini to generate the prose summary and resident broadcast warning
        client = genai.Client(vertexai=True, project='centinela-498622', location='us')
        prompt = (
            "You are a disaster response AI assistant. Based strictly on the following structured risk data "
            "for the Rio Cauca basin (do not invent or change any numbers or facts):\n\n"
            f"{json.dumps(risk_data, indent=2)}\n\n"
            "Please generate:\n"
            "1. 'summary': A concise, technical summary of the compound flood risk for the agency incident report. "
            "Describe the overall basin situation and affected municipalities.\n"
            "2. 'broadcast': A plain-language, urgent warning message to be broadcast to local residents. Mention "
            "the specific municipalities, their risk severities, and the driving parameters (precipitation/rainfall, "
            "river levels, soil saturation index) using the exact numbers from the data. Keep it highly grounded."
        )
        
        response = client.models.generate_content(
            model='gemini-3.5-flash',
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                response_mime_type='application/json',
                response_schema=AlertNarratives
            )
        )
        
        narratives = json.loads(response.text)
        
        title = "Rio Cauca Basin Compound Flood Risk Alert"
        
        return {
            "graded_alert": graded_alert,
            "agency_incident": {
                "title": title,
                "summary": narratives.get("summary", ""),
                "affected_municipalities": affected_municipalities
            },
            "resident_broadcast": narratives.get("broadcast", "")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/connector-status")
async def get_connector_status():
    """Reads status of all configured Fivetran connectors, returning the primary at root and full list in 'connectors'."""
    toolset = get_mcp_toolset()
    try:
        connector_results = []
        for conn in CONNECTORS:
            conn_id = conn["id"]
            async def call_details(session):
                return await session.call_tool(
                    name="get_connection_details",
                    arguments={
                        "schema_file": "open-api-definitions/connections/connection_details.json",
                        "connection_id": conn_id
                    }
                )
            result = await toolset._execute_with_session(call_details, f"Failed to get connection details for {conn_id}")
            raw_text = result.content[0].text
            if "Error" in raw_text or "Fivetran API error" in raw_text:
                connector_results.append({
                    "connector_id": conn_id,
                    "name": conn["name"],
                    "status": "error",
                    "last_sync_time": "never",
                    "freshness": "UNKNOWN"
                })
                continue
                
            data = json.loads(raw_text).get("data", {})
            paused = data.get("paused", False)
            succeeded_at_str = data.get("succeeded_at")
            
            status_val = "paused" if paused else "active"
            
            # Calculate freshness
            freshness = "UNKNOWN"
            if succeeded_at_str:
                if succeeded_at_str.endswith("Z"):
                    succeeded_at_str = succeeded_at_str[:-1]
                succeeded_at = datetime.fromisoformat(succeeded_at_str).replace(tzinfo=timezone.utc)
                current_time = datetime.now(timezone.utc)
                diff_minutes = (current_time - succeeded_at).total_seconds() / 60.0
                freshness = "FRESH" if diff_minutes < 60.0 else "STALE"
                
            connector_results.append({
                "connector_id": conn_id,
                "name": conn["name"],
                "status": status_val,
                "last_sync_time": data.get("succeeded_at") or "never",
                "freshness": freshness
            })
            
        primary = connector_results[0]
        return {
            "status": primary["status"],
            "last_sync_time": primary["last_sync_time"],
            "freshness": primary["freshness"],
            "connectors": connector_results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await toolset.close()

@app.post("/heal")
async def heal(connector_id: str = "plausibly_illustrate"):
    """Runs the existing detect-to-heal flow for a specific connector."""
    try:
        # Run heal with 5 minute threshold
        res = await check_and_heal_connector(connector_id, 5.0)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/break")
async def break_conn(connector_id: str = "plausibly_illustrate"):
    """Pauses a specific connector to simulate an outage."""
    toolset = get_mcp_toolset()
    pipeline_state = {"degraded": False, "error": None}
    try:
        modify_args = {
            "schema_file": "open-api-definitions/connections/modify_connection.json",
            "connection_id": connector_id,
            "request_body": json.dumps({"paused": True})
        }
        res_text = await call_with_retry(toolset, "modify_connection", modify_args, pipeline_state)
        if pipeline_state["degraded"]:
            raise HTTPException(status_code=500, detail=pipeline_state["error"])
        return {"status": "Success", "message": f"Connector {connector_id} paused successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await toolset.close()

@app.get("/", response_class=HTMLResponse)
def read_index():
    """Serves the dashboard home page."""
    try:
        with open("web/index.html", "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/app.js")
def read_js():
    """Serves the client-side JavaScript engine."""
    try:
        with open("web/app.js", "r", encoding="utf-8") as f:
            return Response(content=f.read(), media_type="application/javascript")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/style.css")
def read_css():
    """Serves the dashboard stylesheet."""
    try:
        with open("web/style.css", "r", encoding="utf-8") as f:
            return Response(content=f.read(), media_type="text/css")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
