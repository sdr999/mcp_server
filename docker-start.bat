@echo off
echo Building and starting MCP Server Docker container...
docker compose up -d --build
echo MCP Server started! Access docs at http://localhost:8000/docs
