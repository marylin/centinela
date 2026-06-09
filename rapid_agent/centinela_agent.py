"""
rapid_agent/centinela_agent.py

A dedicated ADK LlmAgent narration turn for Centinela.

This module provides `run_narration_turn(basin, risk_data)` which:
  1. Constructs an ADK InMemorySessionService + Runner
  2. Sends one turn to the narration_agent (an LlmAgent on Gemini 2.5 Pro / Vertex)
  3. Parses the final text response as JSON {"summary": ..., "broadcast": ...}
  4. Enforces a hard 30-second asyncio timeout

The call is wrapped in asyncio.run() in main.py so it works safely from FastAPI's
sync thread-pool executor (sync endpoints).

Call path:
  GET /alert
    └─ get_alert(basin)
         └─ run_narration_turn(basin, risk_data)   ← here
              ├─ InMemorySessionService + Runner    ← ADK runtime
              ├─ Runner.run_async(narration_agent, new_message=Content(...))
              │    └─ LlmAgent turn → Gemini 2.5 Pro on Vertex
              └─ parse JSON from final Event.content.parts[0].text
"""

import asyncio
import json
import os
import uuid
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

# Tell ADK to use Vertex AI (ADC) rather than the Gemini API key.
# These are safe to set here; they are project-config, not secrets.
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "1")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "centinela-498622")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")

# ---------------------------------------------------------------------------
# Narration agent -- no MCP tools, stays fast and bounded
# ---------------------------------------------------------------------------
narration_agent = LlmAgent(
    model="gemini-2.5-pro",
    name="centinela_narration_agent",
    instruction=(
        "You are a disaster response AI analyst for the Centinela early-warning system. "
        "When given structured compound multi-hazard risk data for a river basin, you "
        "produce a JSON object with exactly two fields: "
        "'summary' (a concise technical summary for the agency incident report, 2-4 sentences) "
        "and 'broadcast' (a plain-language urgent warning for local residents that names "
        "the affected municipalities, dominant hazards, and the key numerical drivers such "
        "as precipitation in mm, river level vs threshold in metres, soil saturation index, "
        "slope angle in degrees, susceptibility index, and earthquake magnitude where relevant). "
        "Never invent or change numbers. Use only the data provided. "
        "Output ONLY the JSON object, no markdown fences, no extra text."
    ),
    tools=[],  # no tools -- pure reasoning turn
)


# ---------------------------------------------------------------------------
# Session APP_NAME constant
# ---------------------------------------------------------------------------
_APP_NAME = "centinela_narration"


async def _run_agent_turn(basin: str, risk_data: list[dict[str, Any]]) -> dict[str, str]:
    """Run one agent turn synchronously within an async context.

    Returns dict with 'summary' and 'broadcast' keys.
    Raises on timeout or parse failure.
    """
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name=_APP_NAME,
        user_id="centinela_api",
        session_id=str(uuid.uuid4()),
    )

    runner = Runner(
        agent=narration_agent,
        app_name=_APP_NAME,
        session_service=session_service,
    )

    prompt_text = (
        f"Basin: {basin}\n\n"
        f"Risk data (JSON):\n{json.dumps(risk_data, indent=2)}\n\n"
        "Generate the incident summary and resident broadcast as a JSON object."
    )

    user_message = Content(role="user", parts=[Part(text=prompt_text)])

    print(f"DEBUG: narration via ADK Runner (basin={basin}, municipalities={[r['municipality'] for r in risk_data]})", flush=True)

    final_text = ""
    async for event in runner.run_async(
        user_id="centinela_api",
        session_id=session.id,
        new_message=user_message,
    ):
        if event.is_final_response() and event.content and event.content.parts:
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    final_text += part.text

    if not final_text:
        raise ValueError("ADK narration agent returned no text in final response")

    # Strip accidental markdown fences if the model adds them despite the instruction
    text = final_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Remove first and last fence lines
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    parsed = json.loads(text)
    return {
        "summary": parsed.get("summary", ""),
        "broadcast": parsed.get("broadcast", ""),
    }


def run_narration_turn(basin: str, risk_data: list[dict[str, Any]]) -> dict[str, str]:
    """Synchronous wrapper for `_run_agent_turn`.

    Safe to call from FastAPI sync endpoints (runs a new event loop in the
    current thread). Enforces a 30-second hard timeout.

    Returns dict with 'summary' and 'broadcast'.
    Falls back to empty strings on error rather than crashing the endpoint.
    """
    try:
        return asyncio.run(
            asyncio.wait_for(_run_agent_turn(basin, risk_data), timeout=30.0)
        )
    except asyncio.TimeoutError:
        print("ERROR: ADK narration agent timed out after 30s -- returning empty narrative", flush=True)
        return {"summary": "", "broadcast": ""}
    except Exception as e:
        print(f"ERROR: ADK narration agent failed: {e}", flush=True)
        return {"summary": "", "broadcast": ""}
