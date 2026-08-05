from tools_sdk import tool

# Helper function (NOT exposed to clients)
def get_name() -> str:
    return "somu"

# Main MCP Tool (Exposed to clients)
@tool(description="Returns user info including full name")
def get_info(user_id: int) -> dict:
    name = get_name()
    return {"user_id": user_id, "user_name": name, "status": "active"}
