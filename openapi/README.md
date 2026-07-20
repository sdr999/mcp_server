OpenAPI for MCP Server
======================

This directory contains an OpenAPI 3.0 specification for the MCP server project.

Files
- `openapi.yaml`: Primary OpenAPI document (expand with your endpoints).

Quick usage
- View locally with `redoc-cli`:

```bash
pip install redoc-cli
redoc-cli serve openapi.yaml
```

- Or use `swagger-ui` via Docker:

```bash
docker run --rm -p 8080:8080 -e SWAGGER_JSON=/spec/openapi.yaml -v "$PWD":/spec swaggerapi/swagger-ui
```

Next steps
- Review and extend the `paths` and `components` to match your implementation.
- Add security schemes and examples as needed.
