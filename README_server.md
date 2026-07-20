# Running the MCP Server (development)

Install deps:

```powershell
python -m pip install -r requirements.txt
```

Run locally:

```powershell
python -m src.mcp_server.main
```

The app will be available at `http://127.0.0.1:8000` and the OpenAPI docs at `http://127.0.0.1:8000/docs`.

This is a minimal example; adapt persistence and command handling as needed.
