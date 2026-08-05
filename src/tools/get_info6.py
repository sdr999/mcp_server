from tools_sdk import tool

def get_name() -> str:
    return "somu6"

# Main MCP Tool (Exposed to clients)
@tool(description="MCP tool function get_info6")
def get_info6(user_id: int) -> dict:
    name = get_name()
    return {"user_id": user_id, "user_name": name, "status": "active"}
