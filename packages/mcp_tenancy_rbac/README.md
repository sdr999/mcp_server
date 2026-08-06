# Enterprise Multi-Tenancy RBAC & ABAC Package (`mcp-tenancy-rbac`)

`mcp-tenancy-rbac` is a high-performance, modular, zero-framework-lock-in Multi-Tenancy Role-Based Access Control (RBAC) & Attribute-Based Access Control (ABAC) authorization framework for Python web services (Starlette, FastAPI, Django, and FastMCP servers).

## Features
- 🏢 **Multi-Tenant Isolation**: Tenant (`org_id`) and Workspace (`workspace_id`) boundary enforcement.
- 🛡️ **5-Tier Authorization Precedence**:
  1. Platform SuperAdmin check (`platform_superadmin` role)
  2. Deny-Override explicit tool grants
  3. Canonical Role permission matrix (`member:manage`, `tool:call`, `org:admin`, etc.)
  4. Tenant boundary & ABAC rule checks (exact, prefix, glob matchers, trusted tags, prod environment constraints)
  5. Fallback role-permitted access
- ⚡ **Sub-Millisecond L1 Decision Cache**: Thread-safe LRU cache with TTL invalidation.
- 🗄️ **Pluggable Storage Backends**: In-Memory (testing), SQLite (`aiosqlite`), or MongoDB (`motor` async connection pool).
- 🔐 **Dual Auth Support**: Supabase Bearer JWT tokens, API keys, and static admin bootstrap tokens.
- 📜 **Non-Blocking Audit Logger**: Background queue worker recording security evaluation events to disk and DB.

---

## Quickstart (FastAPI)

```python
from fastapi import FastAPI, Depends, Request, HTTPException
from mcp_tenancy_rbac import (
    IdentityMiddleware,
    create_tenancy_store,
    PolicyEvaluator,
    enforce,
    Principal,
)

app = FastAPI(title="My Multi-Tenant Service")

# 1. Initialize Store & Evaluator
store = create_tenancy_store(backend="sqlite", sqlite_db_path="tenancy.db")
evaluator = PolicyEvaluator(store=store)

app.state.tenancy_store = store
app.state.policy_evaluator = evaluator
app.state.auth_type = "bearer_jwt"

# 2. Register Middleware
app.add_middleware(IdentityMiddleware)

# 3. Define Dependency
async def get_current_principal(request: Request) -> Principal:
    if (denied := await enforce(request, policy="mcp")) is not None:
        raise HTTPException(status_code=denied.status_code, detail="Unauthorized")
    return request.state.principal

# 4. Protect Routes
@app.get("/api/v1/profile")
async def profile(principal: Principal = Depends(get_current_principal)):
    return {"user": principal.email, "tenant_org": principal.active_org}
```

## Quickstart (Pure Python / gRPC / Background Tasks)

```python
from mcp_tenancy_rbac.tenancy import MongoTenancyStore
from mcp_tenancy_rbac.rbac import PolicyEvaluator

async def authorize_background_worker(issuer: str, subject: str, org: str, action: str, resource: str):
    store = MongoTenancyStore(mongo_uri="mongodb://localhost:27017", database="prod")
    evaluator = PolicyEvaluator(store=store)
    
    principal = await store.resolve_principal(issuer, subject, org, "default")
    decision = await evaluator.evaluate(principal, action, resource, org, "default")
    
    return decision.is_allowed
```
