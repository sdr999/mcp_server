"""Unit tests for OpenAPI Spec Native Plugin (src/plugins/openapi_plugin.py).

Run: pytest src/tests/test_openapi_plugin.py
"""
import sys
from pathlib import Path

# Ensure src directory is in sys.path
SRC_DIR = Path(__file__).resolve().parent.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from starlette.testclient import TestClient
from plugins.config import build_context
from plugins.app import build_app
from plugins.openapi_plugin import OpenAPIToolManager, sanitize_tool_name


MOCK_OPENAPI_YAML = """
openapi: 3.0.0
info:
  title: Mock Petstore API
  version: 1.0.0
servers:
  - url: http://localhost:9999/v1
paths:
  /pets:
    get:
      operationId: listPets
      summary: List all pets
      parameters:
        - name: limit
          in: query
          required: false
          schema:
            type: integer
      responses:
        '200':
          description: A list of pets
    post:
      operationId: createPet
      summary: Create a pet
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - name
              properties:
                name:
                  type: string
      responses:
        '201':
          description: Pet created
  /pets/{petId}:
    get:
      operationId: getPetById
      summary: Info for a specific pet
      parameters:
        - name: petId
          in: path
          required: true
          schema:
            type: integer
      responses:
        '200':
          description: Expected response to a valid request
"""


def test_tool_name_sanitization():
    assert sanitize_tool_name("get-pet.by_id-v1!") == "get-pet_by_id-v1"
    assert sanitize_tool_name("___") == "openapi_tool"
    assert len(sanitize_tool_name("a" * 100)) == 64



def test_openapi_plugin_spec_parsing_and_tool_generation():
    mgr = OpenAPIToolManager(mcp_server=None)
    spec = mgr.load_spec_content(MOCK_OPENAPI_YAML)
    ops = mgr.extract_operations(spec)
    assert len(ops) == 3

    op_ids = [op["operationId"] for op in ops]
    assert "listPets" in op_ids
    assert "createPet" in op_ids
    assert "getPetById" in op_ids

    # Check input schema for getPetById
    op_get = next(o for o in ops if o["operationId"] == "getPetById")
    schema = mgr.build_input_schema(spec, op_get)
    assert "petId" in schema["properties"]
    assert "petId" in schema["required"]


def test_openapi_admin_routes_and_tool_call_integration(tmp_path):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text("")
    pkg_parent = str(tmp_path.resolve())
    sys.modules.pop("tools", None)
    if pkg_parent not in sys.path:
        sys.path.insert(0, pkg_parent)

    ctx = build_context([], base_dir=tmp_path)
    ctx.tools_dir = tools_dir
    ctx.admin_token = "admintoken"
    app, _mcp = build_app(ctx)
    client = TestClient(app)

    headers = {"Authorization": "Bearer admintoken"}

    # 1. Register OpenAPI Spec via Admin API
    payload = {
        "collection_id": "mock_pets",
        "spec": MOCK_OPENAPI_YAML,
        "base_url": "http://localhost:9999/v1"
    }
    resp_reg = client.post("/admin/openapi/register", json=payload, headers=headers)
    assert resp_reg.status_code == 201
    res = resp_reg.json()
    assert res["collection_id"] == "mock_pets"
    assert res["tools_count"] == 3
    assert "listPets_mock_pets" in res["tool_names"]

    # 2. List OpenAPI specs via Admin API
    resp_list = client.get("/admin/openapi/specs", headers=headers)
    assert resp_list.status_code == 200
    cols = resp_list.json()["collections"]
    assert len(cols) == 1
    assert cols[0]["collection_id"] == "mock_pets"

    # 3. Verify OpenAPI tool appears in GET /tools catalog
    resp_tools = client.get("/tools", headers=headers)
    assert resp_tools.status_code == 200
    tool_names_in_catalog = [t["name"] for t in resp_tools.json()["tools"]]
    assert "listPets_mock_pets" in tool_names_in_catalog
    assert "createPet_mock_pets" in tool_names_in_catalog
    assert "getPetById_mock_pets" in tool_names_in_catalog

    # 4. Remove OpenAPI spec via Admin API
    resp_rem = client.post("/admin/openapi/mock_pets/remove", headers=headers)
    assert resp_rem.status_code == 200
    assert resp_rem.json()["status"] == "removed"

    # 5. Verify catalog no longer contains removed tools
    resp_tools_after = client.get("/tools", headers=headers)
    catalog_after = [t["name"] for t in resp_tools_after.json()["tools"]]
    assert "listPets_mock_pets" not in catalog_after

