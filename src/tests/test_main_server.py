"""In-process ASGI integration test for the plugin-based main.py server.

Boots the real ASGI app (from plugins.app.build_app) via Starlette's
TestClient -- which fires the composed lifespan -- and exercises the HTTP
surface end-to-end. No uvicorn, no port binding, no remote tool source.
"""
import itertools
import sys
import time
from pathlib import Path

from starlette.testclient import TestClient

from plugins.app import build_app
from plugins.config import AppContext

_uid = itertools.count()
SRC = str(Path(__file__).resolve().parent.parent)


def _make_ctx(tools_dir, auth_type="none", jwks_url="", admin_token="secret"):
    return AppContext(
        base_dir=Path(SRC), tools_dir=tools_dir, env={},
        auth_type=auth_type, api_key_header="authorization", api_key_value="", jwks_url=jwks_url,
        jwt_issuer=None, jwt_audience=None, jwt_required_scopes=None, host="127.0.0.1", port=0,
        import_timeout=30, metrics_enabled=True, sandbox=False,
        sandbox_timeout=30, sandbox_mem_mb=0, sandbox_cpu_sec=0, admin_token=admin_token,
        require_signed=False, manifest_name="tools.manifest.json", signing_key=None,
    )


def _tools_dir(tmp_path):
    pkg = f"main_pkg_{next(_uid)}"
    d = tmp_path / pkg
    d.mkdir()
    (d / "__init__.py").write_text("")
    (d / "echo.py").write_text("def echo(msg: str) -> str:\n    return msg\n")
    sys.path.insert(0, SRC)             # tools_sdk / metrics importable
    sys.path.insert(0, str(tmp_path))   # package importable
    return d


def test_app_boots_lifespan_and_serves(tmp_path):
    app, _mcp = build_app(_make_ctx(_tools_dir(tmp_path)))
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        for _ in range(50):
            if client.get("/readyz").status_code == 200:
                break
            time.sleep(0.1)
        assert client.get("/readyz").status_code == 200

        status = client.get("/status").json()
        assert status["ready"] is True
        assert status["source"] == "local"
        assert status["stats"]["total_tools"] >= 1

        assert "echo" in [t["name"] for t in client.get("/tools").json()["tools"]]
        assert client.get("/metrics").status_code == 200


def test_admin_requires_token_and_resync_is_noop(tmp_path):
    app, _mcp = build_app(_make_ctx(_tools_dir(tmp_path)))
    with TestClient(app) as client:
        for _ in range(50):
            if client.get("/readyz").status_code == 200:
                break
            time.sleep(0.1)

        assert client.post("/admin/resync").status_code == 401              # no token
        r = client.post("/admin/resync", headers={"Authorization": "Bearer secret"})
        assert r.status_code == 409                                          # no remote source

        assert client.post("/admin/tool/echo/disable").status_code == 401
        r = client.post("/admin/tool/echo/disable", headers={"Authorization": "Bearer secret"})
        assert r.status_code == 200
        assert "echo" not in [t["name"] for t in client.get("/tools").json()["tools"]]

        r = client.post("/admin/tool/echo/enable", headers={"Authorization": "Bearer secret"})
        assert r.status_code == 200


def test_admin_disabled_when_token_unset(tmp_path):
    app, _mcp = build_app(_make_ctx(_tools_dir(tmp_path), admin_token=""))
    with TestClient(app) as client:
        assert client.post("/admin/resync").status_code == 503


def test_api_key_protects_everything_but_health(tmp_path):
    ctx = _make_ctx(_tools_dir(tmp_path))
    ctx.auth_type = "api_key"
    ctx.api_key_header = "x-api-key"
    ctx.api_key_value = "secret123"
    app, _mcp = build_app(ctx)
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/status").status_code == 401
        assert client.get("/status", headers={"x-api-key": "secret123"}).status_code == 200


def test_bearer_jwt_protects_read_routes(tmp_path):
    ctx = _make_ctx(_tools_dir(tmp_path), auth_type="bearer_jwt",
                    jwks_url="https://example.com/.well-known/jwks.json")
    app, _mcp = build_app(ctx)
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code in (200, 503)
        assert client.get("/status").status_code == 401
        assert client.get("/tools").status_code == 401
        assert client.get("/metrics").status_code == 401
        assert client.get("/status", headers={"Authorization": "Bearer bad"}).status_code == 401
