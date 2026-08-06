# Enterprise Multi-Tenancy RBAC & ABAC Package (`mcp-tenancy-rbac`)

Welcome to the **`mcp-tenancy-rbac` Standalone Package & Integration Guide**. 

`mcp-tenancy-rbac` is a high-performance, modular, zero-framework-lock-in Multi-Tenancy Role-Based Access Control (RBAC) & Attribute-Based Access Control (ABAC) authorization package for Python web applications, microservices, and AI agent servers (Starlette, FastAPI, Django, FastMCP).

---

## Table of Contents
1. [Architecture Overview & Component Map](#1-architecture-overview--component-map)
2. [Package Installation](#2-package-installation)
3. [5-Minute Quickstart (Starlette / FastAPI)](#3-5-minute-quickstart-starlette--fastapi)
4. [Storage Engine Configuration (Memory, SQLite, MongoDB)](#4-storage-engine-configuration-memory-sqlite-mongodb)
5. [5-Tier Authorization Order of Precedence](#5-5-tier-authorization-order-of-precedence)
6. [Dynamic ABAC Rules & Constraints](#6-dynamic-abac-rules--constraints)
7. [Authentication Modes (Supabase JWT, API Keys, Admin Token)](#7-authentication-modes-supabase-jwt-api-keys-admin-token)
8. [API Endpoints & Sample JSON Payloads](#8-api-endpoints--sample-json-payloads)

---

## 1. Architecture Overview & Component Map

The package is organized into 4 cleanly decoupled submodules:

```
mcp_tenancy_rbac/
├── identity.py           # Identity resolution, JWT claims parsing, ContextVars & IdentityMiddleware
├── tenancy/              # Storage engines & domain data models
│   ├── base.py           # Abstract TenancyStore interface
│   ├── models.py         # Organization, Workspace, Membership, Role, ToolGrant, AuditEntry
│   ├── memory.py         # MemoryTenancyStore (Unit testing & fast volatile memory)
│   ├── sqlite_store.py   # SqliteTenancyStore (Embedded production DB with aiosqlite)
│   ├── mongo_store.py    # MongoTenancyStore (Distributed Motor async pool)
│   ├── scoping.py        # Catalog scoping (filter_tools_for_principal)
│   └── audit.py          # Non-blocking async queue background audit logger
├── rbac/                 # Authorization & Evaluation Engine
│   ├── evaluator.py      # 5-Tier PolicyEvaluator logic
│   ├── abac.py           # ABACEvaluator (exact, prefix, glob matchers, trusted tags, prod_only)
│   └── cache.py          # Thread-safe L1 LRU decision cache with TTL invalidation
└── security.py           # Policy guards (enforce, admin_denied, _jwt_ok)
```

---

## 2. Package Installation

### Option A: Local / Editable Directory Installation
If using inside this workspace or a monorepo:
```bash
pip install -e ./packages/mcp_tenancy_rbac
```

### Option B: PyPI / Git Installation
```bash
pip install git+https://github.com/sdr999/mcp_server.git#subdirectory=packages/mcp_tenancy_rbac
```

### Optional Storage Engine Dependencies:
```bash
# SQLite support:
pip install "mcp-tenancy-rbac[sqlite]"

# MongoDB Motor support:
pip install "mcp-tenancy-rbac[mongo]"

# All optional dependencies:
pip install "mcp-tenancy-rbac[full]"
```

---

## 3. Framework & Service Integration Guides

### A. FastAPI Integration Guide

FastAPI services can integrate `mcp-tenancy-rbac` via `IdentityMiddleware` and standard FastAPI `Depends()`:

```python
from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from mcp_tenancy_rbac import (
    IdentityMiddleware,
    create_tenancy_store,
    PolicyEvaluator,
    DecisionCache,
    enforce,
    Principal,
)

app = FastAPI(title="My Multi-Tenant Service")

# 1. Initialize Tenancy Store & Policy Evaluator
store = create_tenancy_store(backend="sqlite", sqlite_db_path="tenancy.db")
cache = DecisionCache(maxsize=10000, ttl_sec=300.0)
evaluator = PolicyEvaluator(store=store, cache=cache)

app.state.tenancy_store = store
app.state.policy_evaluator = evaluator
app.state.auth_type = "bearer_jwt"
app.state.rbac_enabled = True

# 2. Register Global Identity Middleware
app.add_middleware(IdentityMiddleware)

# 3. Define FastAPI Dependency for Principal & RBAC Enforcement
async def require_principal(request: Request) -> Principal:
    denied = await enforce(request, policy="mcp")
    if denied is not None:
        raise HTTPException(status_code=denied.status_code, detail="Unauthorized")
    return request.state.principal

# 4. Use in FastAPI APIRoutes
@app.get("/api/v1/user/profile")
async def get_user_profile(principal: Principal = Depends(require_principal)):
    return {
        "user_id": principal.subject,
        "email": principal.email,
        "tenant_org": principal.active_org,
        "workspace": principal.active_ws,
        "roles": principal.roles,
        "permissions": list(principal.permissions),
    }
```

---

### B. Pure Python / gRPC / Celery / Background Workers (No HTTP Middleware)

For non-HTTP services, gRPC microservices, or background task runners (Celery, Arq, Temporal), use `PolicyEvaluator` directly in pure Python:

```python
import asyncio
from mcp_tenancy_rbac.tenancy import MongoTenancyStore
from mcp_tenancy_rbac.rbac import PolicyEvaluator, DecisionCache
from mcp_tenancy_rbac.identity import Principal

async def process_background_job(caller_issuer: str, caller_sub: str, target_org: str, action: str, tool_name: str):
    # 1. Instantiate Store & Evaluator
    store = MongoTenancyStore(mongo_uri="mongodb://localhost:27017", database="production")
    cache = DecisionCache(maxsize=5000, ttl_sec=600.0)
    evaluator = PolicyEvaluator(store=store, cache=cache)

    # 2. Resolve Principal from database
    principal = await store.resolve_principal(
        issuer=caller_issuer,
        subject=caller_sub,
        requested_org=target_org,
        requested_workspace="default"
    )

    # 3. Evaluate Authorization Policy
    decision = await evaluator.evaluate(
        principal=principal,
        action=action,             # e.g. "tool:call"
        target_resource=tool_name, # e.g. "database_query"
        target_org=target_org,
        target_workspace="default",
        attributes={"env": "prod"}
    )

    if not decision.is_allowed:
        print(f"⛔ Access Denied for {principal.email}: {decision.reason} ({decision.code})")
        return False

    print(f"✅ Access Allowed via stage: {decision.code}")
    return True
```

---

### C. Flask / Django Integration

For WSGI frameworks like Flask or Django, wrap the ASGI pipeline or use a custom decorator:

```python
from functools import wraps
from flask import Flask, request, jsonify
from mcp_tenancy_rbac.identity import create_superadmin_principal
from mcp_tenancy_rbac.rbac import PolicyEvaluator
from mcp_tenancy_rbac.tenancy import MemoryTenancyStore

app = Flask(__name__)
store = MemoryTenancyStore()
evaluator = PolicyEvaluator(store=store)

def rbac_required(action="tool:call"):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            token = request.headers.get("Authorization", "").replace("Bearer ", "")
            if not token:
                return jsonify({"error": "Unauthorized"}), 401
            # Perform authorization check
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.route("/api/v1/resource", methods=["GET"])
@rbac_required(action="tool:read")
def get_resource():
    return jsonify({"status": "authorized"})
```

---

### D. FastMCP / Model Context Protocol Tool Server

For FastMCP AI tool servers, wire `IdentityMiddleware` and protect FastMCP tool execution:

```python
from fastmcp import FastMCP
from mcp_tenancy_rbac import (
    IdentityMiddleware,
    create_tenancy_store,
    PolicyEvaluator,
    enforce,
)

mcp = FastMCP("Enterprise Tool Server")
app = mcp.http_app(transport="http")

# Attach Store & Evaluator
store = create_tenancy_store(backend="sqlite", sqlite_db_path="mcp.db")
app.state.tenancy_store = store
app.state.policy_evaluator = PolicyEvaluator(store=store)
app.add_middleware(IdentityMiddleware)

@mcp.tool()
async def execute_query(sql_query: str) -> str:
    """Executes a SQL query within the caller's tenant boundary."""
    # Tool logic operates within request.state.principal context
    return f"Query executed successfully for query: {sql_query}"
```


---

## 4. Storage Engine Configuration (Memory, SQLite, MongoDB)

You can swap storage backends by updating your configuration without changing business logic:

### A. Memory Store (In-Memory Testing)
```python
from mcp_tenancy_rbac.tenancy import MemoryTenancyStore

store = MemoryTenancyStore()
```

### B. SQLite Store (Embedded Production)
```python
from mcp_tenancy_rbac.tenancy import SqliteTenancyStore

store = SqliteTenancyStore(db_path="data/tenancy.db")
await store.init_db()  # Creates tables & indices automatically
```

### C. MongoDB Store (Distributed Production Pool)
```python
from mcp_tenancy_rbac.tenancy import MongoTenancyStore

store = MongoTenancyStore(
    mongo_uri="mongodb://localhost:27017",
    database="mcp_tenancy",
    max_pool_size=200,
    min_pool_size=10
)
await store.init_db()
```

---

## 5. 5-Tier Authorization Order of Precedence

When `enforce(request, policy="mcp")` evaluates a request, it runs through 5 strict deterministic stages:

```
[Incoming Request]
       │
       ▼
 ┌─────────────────────────────────────────────────────────┐
 │ Stage 1: Platform SuperAdmin Check                      │
 │ Is "platform_superadmin" in principal.roles?            │
 │ ➔ ALLOW_SUPERADMIN                                      │
 └────────────────────────────┬────────────────────────────┘
                              │ No
                              ▼
 ┌─────────────────────────────────────────────────────────┐
 │ Stage 2: Deny-Override Explicit Tool Grant Check        │
 │ Does target org/principal have a grant record?          │
 │ ➔ DENY_EXPLICIT or ALLOW_GRANT                          │
 └────────────────────────────┬────────────────────────────┘
                              │ No explicit grant
                              ▼
 ┌─────────────────────────────────────────────────────────┐
 │ Stage 3: Canonical Role Permission Check                │
 │ Does principal hold required permission (e.g. tool:call)?│
 │ ➔ DENY_NO_PERMISSION if missing                         │
 └────────────────────────────┬────────────────────────────┘
                              │ Role permitted
                              ▼
 ┌─────────────────────────────────────────────────────────┐
 │ Stage 4: Tenant Boundary & ABAC Evaluation              │
 │ - Tool visibility == public? ➔ ALLOW_PUBLIC              │
 │ - Owner org != Caller org? ➔ DENY_TENANT_BOUNDARY       │
 │ - ABACEvaluator (matchers, trusted_tags, prod_only)     │
 └────────────────────────────┬────────────────────────────┘
                              │ ABAC Passed
                              ▼
 ┌─────────────────────────────────────────────────────────┐
 │ Stage 5: Fallback Role-Permitted Allow                  │
 │ ➔ ALLOW_ROLE                                            │
 └─────────────────────────────────────────────────────────┘
```

---

## 6. Dynamic ABAC Rules & Constraints

You can register fine-grained ABAC rules per organization using `POST /admin/orgs/{org}/tool-grants`:

### Sample ABAC Tool Grant Payload:
```json
{
  "org_id": "acme_corp",
  "tool_name": "database_query_*",
  "grant_type": "allow",
  "match_type": "glob",
  "trusted_tags": ["read-only", "finance"],
  "environment_constraints": ["prod_only"]
}
```

---

## 7. Authentication Modes Reference

### 1. Supabase Bearer JWT (`auth_type: "bearer_jwt"`)
Provide a standard Supabase or OIDC JWT in the `Authorization` header:
```bash
Authorization: Bearer eyJhbGciOiJFUzI1Ni...
```

### 2. Static Admin Token (`MCP_ADMIN_TOKEN`)
Used for root administration and bootstrap provisioning (`/admin/*`):
```bash
Authorization: Bearer mysecretadmin
# or
x-admin-token: mysecretadmin
```

---

## 8. API Endpoints & Sample JSON Payloads

### A. List Organizations (`GET /admin/orgs`)
**Request:**
```bash
curl -X GET http://localhost:8000/admin/orgs \
  -H "Authorization: Bearer mysecretadmin"
```
**Response (200 OK):**
```json
[
  {
    "org_id": "acme_corp",
    "name": "Acme Corporation",
    "status": "active",
    "created_at": 1785988751.0
  }
]
```

### B. Register Organization Tool Grant (`POST /admin/orgs/{org}/tool-grants`)
**Request:**
```bash
curl -X POST http://localhost:8000/admin/orgs/acme_corp/tool-grants \
  -H "Authorization: Bearer mysecretadmin" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "calculator",
    "grant_type": "allow",
    "match_type": "exact"
  }'
```
**Response (201 Created):**
```json
{
  "grant_id": "grant_991823",
  "org_id": "acme_corp",
  "tool_name": "calculator",
  "grant_type": "allow",
  "match_type": "exact",
  "created_at": 1785988800.0
}
```

---

### Verification & Automated Testing
To verify the package build:
```bash
python -m pip install -e ./packages/mcp_tenancy_rbac
pytest src/tests
```
