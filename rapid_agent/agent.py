import os
import time
import json
from datetime import datetime, timezone
from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams, StdioServerParameters

def sleep(seconds: int) -> str:
    """Sleeps for the specified number of seconds. Use this for backoff between retries."""
    time.sleep(seconds)
    return f"Slept for {seconds} seconds."

# Initialize the root agent
root_agent = LlmAgent(
    model="gemini-3.5-flash",
    name="centinela_agent",
    instruction="""You are a DataOps agent. You monitor Fivetran connectors for staleness.
Freshness threshold: A connector is considered stale if its last succeeded sync time is more than 5 minutes ago, or if it has never succeeded and setup is incomplete.
If you detect a stale connector, you MUST use the Fivetran MCP write tools to force a re-sync and raise the sync frequency.
Wrap your write calls in a retry loop: if an MCP write tool fails, use the 'sleep' tool to wait (e.g., 2s, then 4s) before trying again, up to 3 times.
If all retries fail, surface a visible 'pipeline degraded' state to the user and never silence the error.""",
    tools=[
        sleep,
        McpToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command="fivetran-mcp",
                    args=[],
                    env=dict(os.environ)
                )
            )
        )
    ]
)

# Helper function to get Fivetran MCP Toolset with correct parameters
def get_mcp_toolset():
    # In local testing we use uvx, in deployed agent fivetran-mcp is used.
    # We can check if fivetran-mcp is on path or if command/args are configured in env.
    command = os.environ.get("FIVETRAN_MCP_COMMAND", "fivetran-mcp")
    args = []
    if command == "uvx":
        args = ["--from", "git+https://github.com/fivetran/fivetran-mcp", "fivetran-mcp"]
    elif not command:
        command = "fivetran-mcp"
        
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=command,
                args=args,
                env=dict(os.environ)
            ),
            timeout=120.0
        )
    )

async def call_with_retry(toolset, name, arguments, pipeline_state):
    attempts = 2
    for attempt in range(attempts):
        try:
            async def execute(session):
                return await session.call_tool(name=name, arguments=arguments)
            
            result = await toolset._execute_with_session(execute, f"Failed to execute {name}")
            raw_text = result.content[0].text
            if "Error" in raw_text or "Fivetran API error" in raw_text:
                raise Exception(raw_text)
            return raw_text
        except Exception as e:
            if attempt < attempts - 1:
                time.sleep(2)
            else:
                pipeline_state["degraded"] = True
                pipeline_state["error"] = str(e)
                return None

async def check_and_heal_connector(connector_id: str, threshold_minutes: float) -> dict:
    """Checks the freshness of a connector and heals it if stale.

    Args:
        connector_id: Fivetran connector ID
        threshold_minutes: Freshness threshold in minutes

    Returns:
        A dict containing status, freshness, and pipeline state.
    """
    toolset = get_mcp_toolset()
    pipeline_state = {"degraded": False, "error": None}
    
    try:
        async def call_details(session):
            return await session.call_tool(
                name="get_connection_details",
                arguments={
                    "schema_file": "open-api-definitions/connections/connection_details.json",
                    "connection_id": connector_id
                }
            )
            
        result = await toolset._execute_with_session(call_details, "Failed to get connection details")
        raw_text = result.content[0].text
        if "Error" in raw_text or "Fivetran API error" in raw_text:
            raise Exception(raw_text)
            
        data = json.loads(raw_text).get("data", {})
        succeeded_at_str = data.get("succeeded_at")
        paused = data.get("paused", False)
        
        is_stale = False
        if paused:
            is_stale = True
            diff_minutes = float('inf')
        elif not succeeded_at_str:
            is_stale = True
            diff_minutes = float('inf')
        else:
            if succeeded_at_str.endswith("Z"):
                succeeded_at_str = succeeded_at_str[:-1]
            succeeded_at = datetime.fromisoformat(succeeded_at_str).replace(tzinfo=timezone.utc)
            current_time = datetime.now(timezone.utc)
            diff_minutes = (current_time - succeeded_at).total_seconds() / 60.0
            if diff_minutes >= threshold_minutes:
                is_stale = True
                
        freshness = "STALE" if is_stale else "FRESH"
        
        if is_stale:
            # Heal: set sync frequency to 5 minutes
            modify_args = {
                "schema_file": "open-api-definitions/connections/modify_connection.json",
                "connection_id": connector_id,
                "request_body": json.dumps({"sync_frequency": 5, "paused": False})
            }
            await call_with_retry(toolset, "modify_connection", modify_args, pipeline_state)
            
            # Heal: trigger sync
            sync_args = {
                "schema_file": "open-api-definitions/connections/sync_connection.json",
                "connection_id": connector_id,
                "request_body": json.dumps({"force": True})
            }
            await call_with_retry(toolset, "sync_connection", sync_args, pipeline_state)
            
            # Verify and update status
            if not pipeline_state["degraded"]:
                verify_res = await toolset._execute_with_session(call_details, "Failed to verify connection details")
                verify_data = json.loads(verify_res.content[0].text).get("data", {})
                new_sync_freq = verify_data.get("sync_frequency")
                if new_sync_freq == 5:
                    freshness = "FRESH"
        
        return {
            "status": "Success",
            "connector_id": connector_id,
            "freshness": freshness,
            "pipeline_state": "degraded" if pipeline_state["degraded"] else "healthy",
            "error": pipeline_state["error"]
        }
    except Exception as e:
        return {
            "status": "Error",
            "connector_id": connector_id,
            "freshness": "UNKNOWN",
            "pipeline_state": "degraded",
            "error": str(e)
        }
    finally:
        await toolset.close()
