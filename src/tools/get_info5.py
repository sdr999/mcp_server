from tools_sdk import tool

# Helper function (NOT exposed to clients)
def get_name() -> str:
    return "somu4"

# Main MCP Tool (Exposed to clients)
@tool(description="MCP tool function get_info5")
def get_info5(user_id: int) -> dict:
    name = get_name()
    return {"user_id": user_id, "user_name": name, "status": "active"}
