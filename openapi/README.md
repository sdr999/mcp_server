OpenAPI for MCP Server
======================

This directory contains the OpenAPI 3.0 specification (`openapi.yaml`) for the MCP server project.

Interactive Swagger UI
----------------------
The server hosts an interactive Swagger UI page built-in:
- **Swagger UI**: `http://localhost:8000/docs` (or `/swagger`)
- **OpenAPI JSON Spec**: `http://localhost:8000/openapi.json`
- **OpenAPI YAML Spec**: `http://localhost:8000/openapi.yaml`

Files
- `openapi.yaml`: Primary OpenAPI document covering system probes, tool discovery, direct tool execution, tool onboarding, administration, and federation.

Offline / Alternative Viewers
- View locally with `redoc-cli`:
  ```bash
  pip install redoc-cli
  redoc-cli serve openapi.yaml
  ```
- Or use `swagger-ui` via Docker:
  ```bash
  docker run --rm -p 8080:8080 -e SWAGGER_JSON=/spec/openapi.yaml -v "$PWD":/spec swaggerapi/swagger-ui
  ```

