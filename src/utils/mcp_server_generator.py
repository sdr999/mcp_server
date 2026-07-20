import os
from pathlib import Path
from typing import List
import subprocess

TEMPLATE = '''
import asyncio
from mcp.server import FastMCP
from mcp.types import TextContent, Tool
import os
import sys
sys.path.append(os.path.abspath(os.path.join(__file__, "..", "..")))

# Tool imports
{tool_imports}

mcp = FastMCP(name="{server_name}", host="{host}", port={port})

def register_tools():
{tool_registrations}

def main():
    register_tools()
    asyncio.run(mcp.run(transport="{transport}"))

if __name__ == "__main__":
    main()
'''

def generate_server_file(
    output_filename: str,
    server_name: str,
    host: str,
    port: int,
    transport: str,
    tool_names: List[str],
    tools_dir: str = "tools"
):
    """
    Generate a new MCP server file with only the specified tools imported and registered.
    """
    # Prepare import statements and registration lines
    tool_imports = []
    tool_registrations = []
    for tool in tool_names:
        tool_imports.append(f"from {tools_dir}.{tool} import {tool}")
        tool_registrations.append(f"    mcp.add_tool({tool})")
    
    content = TEMPLATE.format(
        tool_imports="\n".join(tool_imports),
        server_name=server_name,
        host=host,
        port=port,
        transport=transport,
        tool_registrations="\n".join(tool_registrations)
    )
    
    # Write to file
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write(content)

#Runs the generated server and returns url of the server
def run_server(server_file_name) -> str:
    try:
        process = subprocess.Popen(
            ["cmd", "/c", "start", "cmd", "/k", "python", server_file_name]
        )
        return f"http://localhost:8004/sse"
    
    except Exception as e:
        print(f"Error running server: {e}")

#Returns only tools that exist in the tools directory
def validate_tools(tool_names: List[str]) -> List[str]:
    validated_tools = []
    existing_tools = [x.strip(".py") for x in os.listdir("tools")]
    for tool_name in tool_names:
        if tool_name in existing_tools:
            validated_tools.append(tool_name)
    return validated_tools

# Example usage (uncomment and modify as needed):
# generate_server_file(
#     output_filename="my_server3.py",
#     server_name="My Tool Server3",
#     host="localhost",
#     port=8004,
#     transport="sse",
#     tool_names=["read_file", "write_file"]
# )   