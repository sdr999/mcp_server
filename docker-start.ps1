Write-Host "Building and starting MCP Server Docker container..." -ForegroundColor Green
docker compose up -d --build
Write-Host "MCP Server started successfully!" -ForegroundColor Green
Write-Host "Access OpenAPI Docs at: http://localhost:8000/docs" -ForegroundColor Cyan
