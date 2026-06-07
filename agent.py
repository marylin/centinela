import os
import time
from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams, StdioServerParameters

def sleep(seconds: int) -> str:
    """Sleeps for the specified number of seconds. Use this for backoff between retries."""
    time.sleep(seconds)
    return f"Slept for {seconds} seconds."

# Initialize the root agent
root_agent = LlmAgent(
    model="gemini-2.5-pro",
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
