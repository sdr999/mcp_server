from tools_sdk import tool

# Helper function (NOT exposed to clients)
def get_name() -> str:
    return "somu3"

# Main MCP Tool (Exposed to clients)
def get_info3(user_id: int) -> dict:
    name = get_name()
    return {"user_id": user_id, "user_name": name, "status": "active"}
