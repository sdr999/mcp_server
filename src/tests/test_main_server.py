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


def _make_ctx(tools_dir, auth_type="none", jwks_url="", admin_token="secret", **onboard_overrides):
    onboard = dict(
        onboard_enabled=True, onboard_autoinstall=True, onboard_network_check=False,
        onboard_network_timeout=3.0, onboard_install_timeout=30.0,
        onboard_allowlist_path=None, onboard_denylist_path=None,
    )
    onboard.update(onboard_overrides)
    return AppContext(
        base_dir=Path(SRC), tools_dir=tools_dir, env={},
        auth_type=auth_type, api_key_header="authorization", api_key_value="", jwks_url=jwks_url,
        jwt_issuer=None, jwt_audience=None, jwt_required_scopes=None, host="127.0.0.1", port=0,
        import_timeout=30, metrics_enabled=True, sandbox=False,
        sandbox_timeout=30, sandbox_mem_mb=0, sandbox_cpu_sec=0, admin_token=admin_token,
        require_signed=False, manifest_name="tools.manifest.json", signing_key=None,
        **onboard,
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


def _wait_ready(client):
    for _ in range(50):
        if client.get("/readyz").status_code == 200:
            return
        time.sleep(0.1)


ADMIN = {"Authorization": "Bearer secret"}


def test_onboard_low_risk_tool_loads_immediately(tmp_path):
    ctx = _make_ctx(_tools_dir(tmp_path))
    app, _mcp = build_app(ctx)
    with TestClient(app) as client:
        _wait_ready(client)
        body = {"name": "greeter", "source": "from tools_sdk import tool\n@tool()\ndef greeter(name: str) -> str:\n    return f'hi {name}'\n"}
        r = client.post("/admin/tools/onboard", json=body, headers=ADMIN)
        assert r.status_code == 201
        assert r.json()["status"] == "onboarded"
        assert "greeter" in [t["name"] for t in client.get("/tools").json()["tools"]]
        assert client.get("/admin/tools/pending", headers=ADMIN).json()["pending"] == []


def test_onboard_requires_admin_token(tmp_path):
    app, _mcp = build_app(_make_ctx(_tools_dir(tmp_path)))
    with TestClient(app) as client:
        _wait_ready(client)
        r = client.post("/admin/tools/onboard", json={"name": "x", "source": "def x(): pass"})
        assert r.status_code == 401


def test_onboard_rejects_bad_name_and_syntax_error(tmp_path):
    app, _mcp = build_app(_make_ctx(_tools_dir(tmp_path)))
    with TestClient(app) as client:
        _wait_ready(client)
        r = client.post("/admin/tools/onboard", json={"name": "../evil", "source": "x = 1"}, headers=ADMIN)
        assert r.status_code == 400
        r = client.post("/admin/tools/onboard", json={"name": "bad", "source": "def bad(:\n"}, headers=ADMIN)
        assert r.status_code == 400


def test_onboard_high_risk_dependency_is_held_pending_then_can_be_approved(tmp_path):
    ctx = _make_ctx(_tools_dir(tmp_path), onboard_denylist_path=None)
    app, mcp = build_app(ctx)
    # Force a denylist hit deterministically via the app's own onboarding manager.
    with TestClient(app) as client:
        _wait_ready(client)
        client.app.state.onboarding.denylist.add("evilpkg")

        body = {"name": "risky", "source": "def risky():\n    return 'ok'\n", "requirements": ["evilpkg==1.0"]}
        r = client.post("/admin/tools/onboard", json=body, headers=ADMIN)
        assert r.status_code == 202
        assert r.json()["status"] == "pending"
        assert "risky" not in [t["name"] for t in client.get("/tools").json()["tools"]]

        pending = client.get("/admin/tools/pending", headers=ADMIN).json()["pending"]
        assert [p["name"] for p in pending] == ["risky"]

        r = client.post("/admin/tools/pending/risky/reject", headers=ADMIN)
        assert r.status_code == 200
        assert client.get("/admin/tools/pending", headers=ADMIN).json()["pending"] == []


def test_onboard_pending_approve_unknown_is_404(tmp_path):
    app, _mcp = build_app(_make_ctx(_tools_dir(tmp_path)))
    with TestClient(app) as client:
        _wait_ready(client)
        assert client.post("/admin/tools/pending/nope/approve", headers=ADMIN).status_code == 404
        assert client.post("/admin/tools/pending/nope/reject", headers=ADMIN).status_code == 404


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


# ---- Batch 3/4 HTTP surface -----------------------------------------------
def test_onboard_disabled_returns_503(tmp_path):
    ctx = _make_ctx(_tools_dir(tmp_path), onboard_enabled=False)
    app, _mcp = build_app(ctx)
    with TestClient(app) as client:
        _wait_ready(client)
        r = client.post("/admin/tools/onboard", json={"name": "x", "source": "def x(): pass"}, headers=ADMIN)
        assert r.status_code == 503


def test_onboard_oversized_source_rejected(tmp_path):
    app, _mcp = build_app(_make_ctx(_tools_dir(tmp_path)))
    with TestClient(app) as client:
        _wait_ready(client)
        big = "x = '" + ("a" * (1024 * 1024 + 10)) + "'\n"
        r = client.post("/admin/tools/onboard", json={"name": "big", "source": big}, headers=ADMIN)
        assert r.status_code == 413


def test_onboard_too_many_requirements_rejected(tmp_path):
    app, _mcp = build_app(_make_ctx(_tools_dir(tmp_path)))
    with TestClient(app) as client:
        _wait_ready(client)
        reqs = [f"pkg{i}==1.0" for i in range(51)]
        r = client.post("/admin/tools/onboard",
                        json={"name": "many", "source": "def many(): pass", "requirements": reqs},
                        headers=ADMIN)
        assert r.status_code == 400


def test_onboard_duplicate_conflict_then_overwrite(tmp_path):
    app, _mcp = build_app(_make_ctx(_tools_dir(tmp_path)))
    with TestClient(app) as client:
        _wait_ready(client)
        body = {"name": "dup", "source": "from tools_sdk import tool\n@tool()\ndef dup():\n    return 1\n"}
        assert client.post("/admin/tools/onboard", json=body, headers=ADMIN).status_code == 201
        assert client.post("/admin/tools/onboard", json=body, headers=ADMIN).status_code == 409
        body2 = {"name": "dup", "source": "from tools_sdk import tool\n@tool()\ndef dup():\n    return 2\n", "overwrite": True}
        assert client.post("/admin/tools/onboard", json=body2, headers=ADMIN).status_code == 201


def test_pending_detail_endpoint(tmp_path):
    ctx = _make_ctx(_tools_dir(tmp_path))
    app, _mcp = build_app(ctx)
    with TestClient(app) as client:
        _wait_ready(client)
        client.app.state.onboarding.denylist.add("evilpkg")
        body = {"name": "risky", "source": "# secret marker\ndef risky():\n    return 1\n",
                "requirements": ["evilpkg==1.0"]}
        assert client.post("/admin/tools/onboard", json=body, headers=ADMIN).status_code == 202
        r = client.get("/admin/tools/pending/risky", headers=ADMIN)
        assert r.status_code == 200
        assert "# secret marker" in r.json()["source"]
        assert client.get("/admin/tools/pending/nope", headers=ADMIN).status_code == 404


def test_onboarding_metrics_exposed(tmp_path):
    app, _mcp = build_app(_make_ctx(_tools_dir(tmp_path)))
    with TestClient(app) as client:
        _wait_ready(client)
        client.post("/admin/tools/onboard",
                    json={"name": "metric_tool", "source": "def metric_tool():\n    return 1\n"},
                    headers=ADMIN)
        body = client.get("/metrics").text
        assert "mcp_tool_onboards_total" in body
        assert "mcp_tools_pending" in body


def test_api_key_mode_admin_reachable_with_admin_token(tmp_path):
    # Regression for #12: in api_key mode the admin routes must be reachable
    # with just the admin Bearer token (no api key), not blocked by the
    # api-key middleware colliding on the Authorization header.
    ctx = _make_ctx(_tools_dir(tmp_path))
    ctx.auth_type = "api_key"
    ctx.api_key_header = "authorization"
    ctx.api_key_value = "apikey-secret"
    app, _mcp = build_app(ctx)
    with TestClient(app) as client:
        _wait_ready(client)
        # non-admin route still requires the api key
        assert client.get("/status").status_code == 401
        # admin route reachable with the admin token alone
        r = client.post("/admin/resync", headers={"Authorization": "Bearer secret"})
        assert r.status_code == 409           # reached the handler (local mode)
        # wrong admin token still rejected by admin_denied
        assert client.post("/admin/resync", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_onboard_response_includes_tool_manifest(tmp_path):
    app, _mcp = build_app(_make_ctx(_tools_dir(tmp_path)))
    with TestClient(app) as client:
        _wait_ready(client)
        src = ("from tools_sdk import tool\n\n"
               "def _helper(x):\n    return x\n\n"
               "@tool()\ndef w(city: str) -> str:\n    return _helper(city)\n")
        r = client.post("/admin/tools/onboard", json={"name": "wtool", "source": src}, headers=ADMIN)
        assert r.status_code == 201
        m = r.json()["tool_manifest"]
        assert [t["name"] for t in m["tools"]] == ["w"]
        assert [e["function"] for e in m["not_exposed"]] == ["_helper"]


def test_onboard_legacy_source_held_under_strict_default(tmp_path):
    app, _mcp = build_app(_make_ctx(_tools_dir(tmp_path)))
    with TestClient(app) as client:
        _wait_ready(client)
        r = client.post("/admin/tools/onboard",
                        json={"name": "legacyhttp", "source": "def legacyhttp():\n    return 1\n"},
                        headers=ADMIN)
        assert r.status_code == 202
        assert "legacy filename-match" in r.json()["hold_reason"]


# ---- direct tool execution: POST /tools/{name}/call ------------------------
def test_tool_call_executes_and_returns_result(tmp_path):
    app, _mcp = build_app(_make_ctx(_tools_dir(tmp_path)))
    with TestClient(app) as client:
        _wait_ready(client)
        r = client.post("/tools/echo/call", json={"arguments": {"msg": "hello"}})
        assert r.status_code == 200
        body = r.json()
        assert body["tool"] == "echo"
        assert body["is_error"] is False
        assert body["structured_content"] == {"result": "hello"}


def test_tool_call_unknown_tool_is_404(tmp_path):
    app, _mcp = build_app(_make_ctx(_tools_dir(tmp_path)))
    with TestClient(app) as client:
        _wait_ready(client)
        assert client.post("/tools/nope/call", json={"arguments": {}}).status_code == 404


def test_tool_call_bad_arguments_is_400(tmp_path):
    app, _mcp = build_app(_make_ctx(_tools_dir(tmp_path)))
    with TestClient(app) as client:
        _wait_ready(client)
        # echo requires msg: str; wrong type fails schema validation
        r = client.post("/tools/echo/call", json={"arguments": {"msg": {"not": "a string"}}})
        assert r.status_code == 400


def test_tool_call_tool_raises_is_reported_in_band(tmp_path):
    d = _tools_dir(tmp_path)
    (d / "boom.py").write_text("def boom(x: int) -> int:\n    raise RuntimeError('kaboom')\n")
    app, _mcp = build_app(_make_ctx(d))
    with TestClient(app) as client:
        _wait_ready(client)
        r = client.post("/tools/boom/call", json={"arguments": {"x": 1}})
        assert r.status_code == 200
        body = r.json()
        assert body["is_error"] is True
        assert "kaboom" in body["error"]


def test_tool_call_requires_mcp_credential_in_api_key_mode(tmp_path):
    ctx = _make_ctx(_tools_dir(tmp_path))
    ctx.auth_type = "api_key"
    ctx.api_key_header = "x-api-key"
    ctx.api_key_value = "secret123"
    app, _mcp = build_app(ctx)
    with TestClient(app) as client:
        _wait_ready(client)
        assert client.post("/tools/echo/call", json={"arguments": {"msg": "hi"}}).status_code == 401
        r = client.post("/tools/echo/call", json={"arguments": {"msg": "hi"}},
                        headers={"x-api-key": "secret123"})
        assert r.status_code == 200
