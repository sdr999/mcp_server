# mcp_server.py
import asyncio
import importlib
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

# om fastmcp import FastMCP
from mcp.server import FastMCP
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import threading
import time
from dotenv import dotenv_values
from agentic_framework.utils import global_variables
# load_dotenv()
# env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', '.env')
# env = dotenv_values(dotenv_path=env_path)
# global_variables.env=env
env = dict(os.environ) 
global_variables.env=env

mcp = FastMCP(name="Tool Server",host="0.0.0.0",port=8000)

class Server:
    def __init__(self,mcp:FastMCP):
        self.mcp = mcp
        self.load_tools_from_directory()
        # self.mcp = FastMCP("Tool Server")

    def connect(self):
        asyncio.run(self.mcp.run(transport="sse"))

    def reload_tools(self, tools_dir: str = "tools"):

        """
        Reload all tools from the tools directory. This allows dynamic updates
        without restarting the server.

        Args:
            tools_dir (str): The directory containing tool modules.
        """
        tools_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), tools_dir)
        tools_path = Path(tools_path)
        # tools_path = Path(tools_dir)
        actual_tool_files = [f for f in tools_path.glob("*.py") if f.name != "__init__.py"]


        for file_path in actual_tool_files:
            module_name_stem = file_path.stem
            full_module_name = f"{tools_path.name}.{module_name_stem}"

            # Remove module from sys.modules to force reload
            if full_module_name in sys.modules:
                del sys.modules[full_module_name]

            try:
                module = importlib.import_module(full_module_name)
                tool_function_name = module_name_stem

                if hasattr(module, tool_function_name):
                    tool_function = getattr(module, tool_function_name)
                    if callable(tool_function):
                        self.mcp.add_tool(tool_function)
                    
            except Exception as e:
                print(f"Reload tools error: {e}")

    
    def load_tools_from_directory(self, tools_dir: str = "tools"):
        """
        Dynamically load all Python files from the specified tools directory
        and register their MCP tools.

        Args:
            tools_dir (str): The name of the directory containing tool modules.
                             Assumed to be a package (or will be made one).

        It assumes that for a tool file, e.g., 'tools/my_tool.py',
        there is a corresponding function `def my_tool(...):` within that file,
        which is the tool to be registered.
        """

        # Resolve tools_path. Path() resolves relative to the Current Working Directory (CWD).
        # This is standard if your script is run from the project root and 'tools' is a subdir.
        tools_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), tools_dir)
        tools_path = Path(tools_path)
        # tools_path = Path(tools_dir)

        # Ensure the tools directory exists, create if not
        if not tools_path.is_dir():
            try:
                tools_path.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return  # Stop if directory cannot be created

        # Ensure the tools directory is a package by creating __init__.py if it doesn't exist
        init_py_path = tools_path / "__init__.py"
        if not init_py_path.exists():
            try:
                init_py_path.touch(exist_ok=True)
            except OSError as e:
                print(f"Create __init__.py error: {e}")

        # For imports like `from tools_package_name.module import function`, the
        # directory *containing* `tools_package_name` must be in sys.path.
        # `tools_path.resolve().parent` is this containing directory.
        package_root = str(tools_path.resolve().parent)
        if package_root not in sys.path:
            sys.path.insert(0, package_root)

        
        tool_files_found = list(tools_path.glob("*.py"))
        
        # Check if any actual tool files (not __init__.py) are present
        actual_tool_files = [f for f in tool_files_found if f.name != "__init__.py"]

        if not actual_tool_files:
            return

        for file_path in actual_tool_files:
            module_name_stem = file_path.stem  # e.g., "read_file" for "read_file.py"
            
            # Construct the full module path for import, e.g., "tools.read_file"
            # This uses the name of the tools_path directory as the package name.
            full_module_name = f"{tools_path.name}.{module_name_stem}"

            try:
                module = importlib.import_module(full_module_name)
                
                # As per user's request, assume the tool function has the same name as the module stem
                tool_function_name = module_name_stem
                
                if hasattr(module, tool_function_name):
                    tool_function = getattr(module, tool_function_name)
                    if callable(tool_function):
                        self.mcp.add_tool(tool_function)
                    
            except Exception as e:
                print(f"Load tools from directory error: {e}")
        tools=asyncio.run(self.mcp.list_tools())


@mcp.tool()
def text_analyzer(text: str) -> str:
    """
    Analyze text and provide basic statistics.
    
    Args:
        text: The text to analyze
    
    Returns:
        Analysis results including word count, character count, etc.
    """
    try:
        word_count = len(text.split())
        char_count = len(text)
        char_count_no_spaces = len(text.replace(" ", ""))
        sentence_count = text.count(".") + text.count("!") + text.count("?")
        
        analysis = f"""
Text Analysis Results:
- Word count: {word_count}
- Character count: {char_count}
- Character count (no spaces): {char_count_no_spaces}
- Estimated sentence count: {sentence_count}
- Average word length: {char_count_no_spaces / word_count if word_count > 0 else 0:.2f}
        """.strip()
        
        return analysis
    except Exception as e:
        return f"Error analyzing text: {str(e)}"
    


class ToolDirectoryWatcher(FileSystemEventHandler):
    def __init__(self, server: Server, tools_dir: str = "tools"):
        self.server = server
        self.tools_dir = tools_dir
        self._observer = Observer()

    def on_modified(self, event):
        if event.src_path.endswith(".py"):
            self.server.reload_tools()

    def on_created(self, event):
        if event.src_path.endswith(".py"):
            self.server.reload_tools()

    def on_deleted(self, event):
        if event.src_path.endswith(".py"):
            self.server.reload_tools()

    def start(self):
        tools_path = Path(self.tools_dir).resolve()
        self._observer.schedule(self, str(tools_path), recursive=False)
        thread = threading.Thread(target=self._observer.start, daemon=True)
        thread.start()


def main():
    server = Server(mcp)

    # Start tool watcher
    watcher = ToolDirectoryWatcher(server)
    watcher.start()

    server.connect()

main()

if __name__ == "__main__":
    main()
