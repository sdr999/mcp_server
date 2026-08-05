# OpenAPI MCP Native Plugin Guide

The OpenAPI MCP Native Plugin ([`src/plugins/openapi_plugin.py`](../src/plugins/openapi_plugin.py)) dynamically converts any **OpenAPI 3.0 / 3.1 REST API specification** into live, executable Model Context Protocol (MCP) tools inside the main MCP tool server.

---

## 1. Key Features

- **Universal Spec Loading**: Load OpenAPI specifications from a **Remote HTTP/HTTPS URL**, **Local File Path**, or **Raw JSON/YAML String**.
- **Dynamic Tool Generation**: Automatically creates a live MCP tool for every REST API operation (`GET`, `POST`, `PUT`, `DELETE`, `PATCH`).
- **Explicit Parameter Signatures**: Compiles explicit Python function parameters matching target OpenAPI schemas, avoiding `**kwargs` schema inference issues in FastMCP.
- **Full Catalog Integration**: Registered OpenAPI tools automatically synchronize with **`GET /tools`** (tool catalog) and **`POST /tools/{name}/call`** (HTTP execution).
- **Multi-Scheme Auth Support**: Pass `auth_type` (`none`, `api_key`, `bearer`, `custom`) to authenticate downstream REST API requests.

---

## 2. API Endpoints

### 1. Register OpenAPI Specification
**`POST /admin/openapi/register`** (Requires Admin Token)

#### Request Payload:
```json
{
  "collection_id": "mycalculatorstore",
  "spec": "http://localhost:9998/v1/openapi.json",
  "base_url": null,
  "auth_type": "none",
  "api_key": null,
  "header_name": null,
  "token": null,
  "headers": {}
}
```

#### Field-by-Field Reference:

| Field Name | Type | Description |
| :--- | :--- | :--- |
| `collection_id` | `str` | **REQUIRED**: Unique identifier for this spec collection. Tools will be named `<operationId>_<collection_id>`. |
| `spec` | `str` | **REQUIRED**: Spec HTTP URL, local file path, or raw JSON/YAML text. |
| `base_url` | `str` | **OPTIONAL**: Override base REST URL. If omitted/null, automatically reads from spec `servers` block. |
| `auth_type` | `str` | **OPTIONAL**: Auth mode (`none`, `api_key`, `bearer`, `custom`). |
| `api_key` | `str` | **OPTIONAL**: API Key value (used when `auth_type="api_key"`). |
| `header_name` | `str` | **OPTIONAL**: Custom header name for API Key (defaults to `X-API-Key`). |
| `token` | `str` | **OPTIONAL**: Bearer JWT token (used when `auth_type="bearer"`). |
| `headers` | `dict` | **OPTIONAL**: Custom headers dictionary (used when `auth_type="custom"`). |

#### Response (`201 Created`):
```json
{
  "collection_id": "mycalculatorstore",
  "base_url": "http://localhost:9998/v1",
  "tools_count": 3,
  "tool_names": [
    "add_mycalculatorstore",
    "subtract_mycalculatorstore",
    "multiply_mycalculatorstore"
  ]
}
```

---

### 2. List Registered OpenAPI Spec Collections
**`GET /admin/openapi/specs`** (Requires Admin Token)

#### Response (`200 OK`):
```json
{
  "collections": [
    {
      "collection_id": "mycalculatorstore",
      "base_url": "http://localhost:9998/v1",
      "tools_count": 3,
      "tool_names": [
        "add_mycalculatorstore",
        "subtract_mycalculatorstore",
        "multiply_mycalculatorstore"
      ]
    }
  ]
}
```

---

### 3. Remove an OpenAPI Spec Collection
**`POST /admin/openapi/{collection_id}/remove`** (Requires Admin Token)

#### Response (`200 OK`):
```json
{
  "status": "removed",
  "collection_id": "mycalculatorstore"
}
```

---

## 3. Tool Execution

All generated OpenAPI tools are executable via the unified tool call endpoint **`POST /tools/{name}/call`**:

```bash
curl -X POST "http://localhost:8000/tools/add_mycalculatorstore/call" \
  -H "Authorization: Bearer mysecretadmin" \
  -H "Content-Type: application/json" \
  -d '{
    "arguments": {
      "a": 10,
      "b": 20
    }
  }'
```

---

## 4. Quick-Start Self-Testing with Mock Calculator Server

Run the standalone Mock Calculator REST API server:

```bash
python mock_calculator_server.py
```

- Interactive Mock Swagger UI: `http://localhost:9998/docs`
- Raw OpenAPI Spec: `http://localhost:9998/v1/openapi.json`
- Main MCP Server Interactive Swagger UI: `http://localhost:8000/docs`
