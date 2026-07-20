from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, Optional
import uuid

app = FastAPI(title="MCP Server")


class CommandRequest(BaseModel):
    action: str
    payload: Optional[Dict[str, Any]] = None


class CommandResponse(BaseModel):
    id: str
    status: str
    result: Optional[Dict[str, Any]] = None


class Health(BaseModel):
    status: str
    uptime: float


# Simple in-memory store for example purposes
_commands: Dict[str, Dict[str, Any]] = {}


@app.get("/health", response_model=Health)
def get_health():
    return {"status": "ok", "uptime": 0.0}


@app.post("/commands", response_model=CommandResponse, status_code=201)
def submit_command(req: CommandRequest):
    command_id = str(uuid.uuid4())
    record = {"id": command_id, "status": "queued", "result": None}
    _commands[command_id] = record
    return record


@app.get("/commands/{commandId}", response_model=CommandResponse)
def get_command(commandId: str):
    cmd = _commands.get(commandId)
    if not cmd:
        raise HTTPException(status_code=404, detail={
                            "code": 404, "message": "Command not found"})
    return cmd


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
