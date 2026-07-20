"""In-process ASGI integration test.

Boots the real ASGI app (from build_app) via Starlette's TestClient — which fires
the composed lifespan (FastMCP session manager + our bootstrap/reload tasks) — and
exercises the HTTP surface end-to-end. No uvicorn, no port binding, no Azure.

This guards the trickiest part of the server (lifespan composition + readiness +
routing), so a future FastMCP change that breaks it fails CI instead of prod.

Run: pytest src/tests/test_asgi_integration.py
Requires: fastmcp, starlette (TestClient) — both already dependencies.
"""
import itertools
import sys
import time
from pathlib import Path

from starlette.testclient import TestClient

import multiple_mcp_main as m

_uid = itertools.count()
SRC = str(Path(m.__file__).resolve().parent)


def _make_ctx(tools_dir, auth_type="none", jwks_url=""):
    return m.AppContext(
        base_dir=Path(SRC), local_tools_dir=tools_dir, remote_prefix="x", env={},
        auth_type=auth_type, api_key_header="authorization", api_key_value="", jwks_url=jwks_url,
        jwt_issuer=None, jwt_audience=None, jwt_required_scopes=None, host="127.0.0.1", port=0,
        poll_interval=60, import_timeout=30, metrics_enabled=True, sandbox=False,
        sandbox_timeout=30, sandbox_mem_mb=0, sandbox_cpu_sec=0, admin_token="secret",
        tool_source="local", require_signed=False, manifest_name="tools.manifest.json",
        signing_key=None, azure_enabled=False,
    )


def _tools_dir(tmp_path):
    pkg = f"asgi_pkg_{next(_uid)}"
    d = tmp_path / pkg
    d.mkdir()
    (d / "__init__.py").write_text("")
    (d / "echo.py").write_text("def echo(msg: str) -> str:\n    return msg\n")
    sys.path.insert(0, SRC)          # tools_sdk importable
    sys.path.insert(0, str(tmp_path))  # package importable
    return d


def test_app_boots_lifespan_and_serves(tmp_path):
    app, _mcp = m.build_app(_make_ctx(_tools_dir(tmp_path)))
    with TestClient(app) as client:                 # runs the composed lifespan startup
        # liveness immediately
        assert client.get("/healthz").status_code == 200
        # readiness flips to 200 once the background initial-load task completes
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
    # clean shutdown (no CancelledError escaping the lifespan) is asserted by the
    # context manager exiting without raising.


def test_admin_auth_and_local_resync(tmp_path):
    app, _mcp = m.build_app(_make_ctx(_tools_dir(tmp_path)))
    with TestClient(app) as client:
        assert client.post("/admin/resync").status_code == 401              # no token
        r = client.post("/admin/resync", headers={"Authorization": "Bearer secret"})
        assert r.status_code == 409                                          # local mode: nothing to sync


def test_bearer_jwt_protects_read_routes(tmp_path):
    ctx = _make_ctx(_tools_dir(tmp_path), auth_type="bearer_jwt",
                    jwks_url="https://example.com/.well-known/jwks.json")
    app, _mcp = m.build_app(ctx)
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200        # liveness stays open
        assert client.get("/readyz").status_code in (200, 503)  # readiness stays open
        assert client.get("/status").status_code == 401         # gap closed
        assert client.get("/tools").status_code == 401
        assert client.get("/metrics").status_code == 401
        # a malformed bearer token is still rejected
        assert client.get("/status", headers={"Authorization": "Bearer bad"}).status_code == 401
