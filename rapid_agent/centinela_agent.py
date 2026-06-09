"""
rapid_agent/centinela_agent.py

A dedicated ADK LlmAgent narration turn for Centinela.

This module provides `run_narration_turn(basin, risk_data)` which:
  1. Constructs an ADK InMemorySessionService + Runner
  2. Sends one turn to the narration_agent (an LlmAgent on Gemini 2.5 Flash / Vertex)
  3. Extracts the structured output via event.output (ADK output_schema path)
  4. Enforces a hard 30-second asyncio timeout

Using output_schema is the ADK-native structured-output mechanism.  It avoids the
"model output must contain either output text or tool calls" error that arises when
generate_content_config(response_mime_type=application/json) is used with tools=[],
because ADK validates content parts differently from structured output events.

Call path:
  GET /alert
    └─ get_alert(basin)
         └─ run_narration_turn(basin, risk_data)   ← here
              ├─ InMemorySessionService + Runner    ← ADK runtime
              ├─ Runner.run_async(narration_agent, new_message=Content(...))
              │    └─ LlmAgent turn (output_schema=AlertNarrative)
              │         └─ Gemini 2.5 Flash on Vertex AI (ADC)
              └─ event.output → {"summary": ..., "broadcast": ...}
"""

import asyncio
import json
import os
import uuid
from typing import Any

from pydantic import BaseModel

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

# Tell ADK to use Vertex AI (ADC) rather than the Gemini API key.
# These are project-config values, not secrets.
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "1")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "centinela-498622")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")


# ---------------------------------------------------------------------------
# Structured output schema (Pydantic) -- ADK output_schema mechanism
# ---------------------------------------------------------------------------
class AlertNarrative(BaseModel):
    summary: str
    broadcast: str


# ---------------------------------------------------------------------------
# Narration agent -- no MCP tools, fast and bounded.
# output_schema is the ADK-native way to enforce JSON output; it puts the
# result in event.output rather than event.content, bypassing the content
# validation that raises "model output must contain either output text or
# tool calls" when the model emits structured JSON without conversational text.
# ---------------------------------------------------------------------------
narration_agent = LlmAgent(
    model="gemini-3.5-flash",
    name="centinela_narration_agent",
    instruction=(
        "You are a disaster response AI analyst for the Centinela early-warning system. "
        "When given structured compound multi-hazard risk data for a river basin, produce "
        "a JSON object with exactly two fields:\n"
        "- 'summary': a concise technical summary (2-4 sentences) for the agency incident "
        "report describing the overall basin situation and affected municipalities.\n"
        "- 'broadcast': a plain-language urgent warning for local residents naming each "
        "affected municipality, its dominant hazard, and the key numerical drivers "
        "(precipitation mm, river level vs threshold in metres, soil saturation index, "
        "slope angle degrees, susceptibility index, earthquake magnitude where applicable).\n"
        "Never invent or change any numbers. Use only the data provided."
    ),
    tools=[],
    output_schema=AlertNarrative,
)


# ---------------------------------------------------------------------------
# Session APP_NAME constant
# ---------------------------------------------------------------------------
_APP_NAME = "centinela_narration"


async def _run_agent_turn(basin: str, risk_data: list[dict[str, Any]]) -> dict[str, str]:
    """Run one agent turn and return the structured output.

    Returns dict with 'summary' and 'broadcast' keys.
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
        f"Risk data:\n{json.dumps(risk_data, indent=2)}\n\n"
        "Generate the incident summary and resident broadcast."
    )

    user_message = Content(role="user", parts=[Part(text=prompt_text)])

    print(
        f"DEBUG: narration via ADK Runner (basin={basin}, "
        f"municipalities={[r['municipality'] for r in risk_data]})",
        flush=True,
    )

    result_output: dict | None = None
    result_text: str = ""

    async for event in runner.run_async(
        user_id="centinela_api",
        session_id=session.id,
        new_message=user_message,
    ):
        # Primary path: output_schema puts structured data in event.output
        if event.is_final_response():
            if event.output:
                result_output = event.output if isinstance(event.output, dict) else dict(event.output)
                break
            # Fallback: collect text parts in case output_schema routing varies
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        result_text += part.text

    if result_output:
        return {
            "summary": str(result_output.get("summary", "")),
            "broadcast": str(result_output.get("broadcast", "")),
        }

    if result_text:
        # Strip markdown fences if present
        text = result_text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            lines = lines[1:] if lines else lines
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        parsed = json.loads(text)
        return {
            "summary": str(parsed.get("summary", "")),
            "broadcast": str(parsed.get("broadcast", "")),
        }

    raise ValueError("ADK narration agent returned no usable output")


def run_narration_turn(basin: str, risk_data: list[dict[str, Any]]) -> dict[str, str]:
    """Synchronous wrapper for `_run_agent_turn`.

    Safe to call from FastAPI sync endpoints (runs a new event loop in the
    current thread). Enforces a 30-second hard timeout.

    Returns dict with 'summary' and 'broadcast'.
    Logs and returns empty strings on failure rather than crashing the endpoint.
    """
    try:
        return asyncio.run(
            asyncio.wait_for(_run_agent_turn(basin, risk_data), timeout=30.0)
        )
    except asyncio.TimeoutError:
        print(
            "ERROR: ADK narration agent timed out after 30s -- returning empty narrative",
            flush=True,
        )
        return {"summary": "", "broadcast": ""}
    except Exception as e:
        print(f"ERROR: ADK narration agent failed: {e}", flush=True)
        return {"summary": "", "broadcast": ""}
