# Enterprise Multi-Tenancy & RBAC Architecture Guide

This document provides a complete developer reference, architectural guide, code walkthrough, and sample API payloads for the Multi-Tenancy & Role-Based / Attribute-Based Access Control (RBAC/ABAC) system in the MCP Tool Server.

---

## 1. Architectural Overview

```
                      +---------------------------------------+
                      |         Supabase Auth (JWT)          |
                      +---------------------------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |  Identity Middleware (Principal)     |
                      |   - JWKS Key Rotation (ES256/RS256)   |
                      |   - SuperAdmin: oooosomu9@gmail.com   |
                      +---------------------------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |     5-Tier RBAC & ABAC Evaluator      |
                      |   1. ALLOW_SUPERADMIN                 |
                      |   2. DENY_EXPLICIT                    |
                      |   3. ALLOW_GRANT                      |
                      |   4. DENY_NO_PERMISSION               |
                      |   5. DENY_TENANT_BOUNDARY / ABAC      |
                      +---------------------------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |     L1 Decision Cache (TTL 300s)      |
                      +---------------------------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |   Pluggable Tenancy Store Backend     |
                      | (SQLite | Mongo | Memory | JSON)      |
                      +---------------------------------------+
                                          |
                                          v
                      +---------------------------------------+
                      | Non-Blocking Async Audit Logger (JSONL)|
                      +---------------------------------------+
```

---

## 2. Component Structure & Code References

| Module / Path | Description | Key Classes / Functions |
| :--- | :--- | :--- |
| [`src/plugins/tenancy/models.py`](file:///d:/python/mcp_server/src/plugins/tenancy/models.py) | Domain Data Models | `Organization`, `Workspace`, `Membership`, `Role`, `ToolOwnership`, `ToolGrant`, `AuditEntry` |
| [`src/plugins/tenancy/base.py`](file:///d:/python/mcp_server/src/plugins/tenancy/base.py) | Abstract Backend ABC | `TenancyStore` interface defining async CRUD operations |
| [`src/plugins/tenancy/sqlite_store.py`](file:///d:/python/mcp_server/src/plugins/tenancy/sqlite_store.py) | SQLite Storage Engine | `SqliteTenancyStore` with `schema_meta` and auto-closing connection context managers |
| [`src/plugins/tenancy/mongo_store.py`](file:///d:/python/mcp_server/src/plugins/tenancy/mongo_store.py) | MongoDB Motor Engine | `MongoTenancyStore` async connection pool (`maxPoolSize=200`, `minPoolSize=10`) modeled after *hire-pilot* |
| [`src/plugins/tenancy/seeder.py`](file:///d:/python/mcp_server/src/plugins/tenancy/seeder.py) | First-Start Seeder | `seed_tenancy_store_if_empty` seeding built-in roles and `oooosomu9@gmail.com` SuperAdmin binding |
| [`src/plugins/tenancy/scoping.py`](file:///d:/python/mcp_server/src/plugins/tenancy/scoping.py) | Catalog Scoping | `filter_tools_for_principal` filtering local and upstream tool catalogs |
| [`src/plugins/tenancy/audit.py`](file:///d:/python/mcp_server/src/plugins/tenancy/audit.py) | Async Audit Logger | `AsyncAuditLogger` non-blocking queue worker writing to `logs/audit.log` & DB |
| [`src/plugins/rbac/evaluator.py`](file:///d:/python/mcp_server/src/plugins/rbac/evaluator.py) | Policy Evaluator | `PolicyEvaluator` executing 5-tier evaluation order of precedence |
| [`src/plugins/rbac/abac.py`](file:///d:/python/mcp_server/src/plugins/rbac/abac.py) | ABAC Engine | `ABACEvaluator` evaluating exact/prefix/glob matchers, `trusted_tags`, and workspace restrictions |
| [`src/plugins/rbac/cache.py`](file:///d:/python/mcp_server/src/plugins/rbac/cache.py) | Decision Cache | `DecisionCache` thread-safe L1 LRU decision cache with TTL invalidation |

---

## 3. Sample API Request & Response Payloads

### A. Authentication & Sign In (`POST /auth/signin`)

**Request:**
```http
POST /auth/signin HTTP/1.1
Host: localhost:8000
Content-Type: application/json

{
  "username": "oooosomu9@gmail.com",
  "email": "oooosomu9@gmail.com",
  "password": "secretpass123"
}
```

**Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJFUzI1NiIsImtpZCI6ImYwYjIwY2Mx...",
  "token_type": "bearer",
  "expires_in": 3600,
  "user": {
    "id": "2061e3fc-95db-4866-b553-22cb52a22a05",
    "email": "oooosomu9@gmail.com"
  }
}
```

---

### B. WhoAmI Identity Inspection (`GET /whoami`)

**Request:**
```http
GET /whoami HTTP/1.1
Host: localhost:8000
Authorization: Bearer eyJhbGciOiJFUzI1NiIsImtpZCI6ImYwYjIwY2Mx...
X-Tenant-Id: acme
X-Workspace-Id: dev
```

**Response (200 OK):**
```json
{
  "principal_id": "2061e3fc-95db-4866-b553-22cb52a22a05",
  "issuer": "https://bplpycqmizyztxqwglgb.supabase.co/auth/v1",
  "subject": "2061e3fc-95db-4866-b553-22cb52a22a05",
  "email": "oooosomu9@gmail.com",
  "org_id": "acme",
  "workspace_id": "dev",
  "roles": [
    "platform_superadmin",
    "developer"
  ],
  "permissions": [
    "tool:list",
    "tool:call",
    "tool:onboard",
    "upstream:call",
    "admin:all"
  ]
}
```

---

### C. Admin Create Organization (`POST /admin/orgs`)

**Request:**
```http
POST /admin/orgs HTTP/1.1
Host: localhost:8000
Authorization: Bearer mysecretadmin
Content-Type: application/json

{
  "org_id": "finance_corp",
  "name": "Finance Corporation"
}
```

**Response (201 Created):**
```json
{
  "org_id": "finance_corp",
  "name": "Finance Corporation",
  "status": "active",
  "created_at": 1785949200.0
}
```

---

### D. Admin Create Workspace (`POST /admin/orgs/{org}/workspaces`)

**Request:**
```http
POST /admin/orgs/finance_corp/workspaces HTTP/1.1
Host: localhost:8000
Authorization: Bearer mysecretadmin
Content-Type: application/json

{
  "workspace_id": "prod",
  "name": "Production Workspace"
}
```

**Response (201 Created):**
```json
{
  "workspace_id": "prod",
  "org_id": "finance_corp",
  "name": "Production Workspace",
  "status": "active",
  "created_at": 1785949210.0
}
```

---

### E. Admin Bind Member Role (`POST /admin/orgs/{org}/members`)

**Request:**
```http
POST /admin/orgs/finance_corp/members HTTP/1.1
Host: localhost:8000
Authorization: Bearer mysecretadmin
Content-Type: application/json

{
  "principal_id": "user_12345",
  "role": "org_admin",
  "workspace_id": "prod"
}
```

**Response (201 Created):**
```json
{
  "principal_id": "user_12345",
  "org_id": "finance_corp",
  "role": "org_admin",
  "workspace_id": "prod"
}
```

---

### F. Admin Add Dynamic Tool Grant (`POST /admin/orgs/{org}/tool-grants`)

**Request:**
```http
POST /admin/orgs/finance_corp/tool-grants HTTP/1.1
Host: localhost:8000
Authorization: Bearer mysecretadmin
Content-Type: application/json

{
  "scope_type": "org",
  "scope_id": "finance_corp",
  "effect": "allow",
  "match_type": "glob",
  "match_value": "db_*_query"
}
```

**Response (201 Created):**
```json
{
  "id": "grant_8f1a2b",
  "scope_type": "org",
  "scope_id": "finance_corp",
  "effect": "allow",
  "match_type": "glob",
  "match_value": "db_*_query",
  "created_at": 1785949220.0
}
```

---

### G. Scoped Tool Listing (`GET /tools`)

**Request:**
```http
GET /tools HTTP/1.1
Host: localhost:8000
Authorization: Bearer eyJhbGciOiJFUzI1NiIsImtpZCI6ImYwYjIwY2Mx...
X-Tenant-Id: finance_corp
```

**Response (200 OK):**
```json
[
  {
    "name": "greet",
    "description": "Returns a personalized greeting",
    "input_schema": {
      "type": "object",
      "properties": {
        "name": { "type": "string" }
      }
    }
  },
  {
    "name": "db_users_query",
    "description": "Execute database query for users",
    "input_schema": {
      "type": "object",
      "properties": {
        "query": { "type": "string" }
      }
    }
  }
]
```

---

## 4. Code Walkthrough & Key Code Snippets

### A. 5-Tier Policy Evaluator Precedence ([`src/plugins/rbac/evaluator.py`](file:///d:/python/mcp_server/src/plugins/rbac/evaluator.py))

```python
async def evaluate(self, principal: Principal, action: str, resource: str, context: Optional[dict] = None) -> EvaluationResult:
    # 1. SuperAdmin Override
    if "platform_superadmin" in principal.roles:
        return EvaluationResult(allowed=True, decision="ALLOW_SUPERADMIN", reason="SuperAdmin access")

    # 2. Explicit Grants Check (Deny / Allow)
    grants = await self.store.get_tool_grants(principal.org_id, principal.workspace_id, principal.principal_id)
    for grant in grants:
        if self._match_grant(grant.match_type, grant.match_value, resource):
            if grant.effect == "deny":
                return EvaluationResult(allowed=False, decision="DENY_EXPLICIT", reason=f"Explicit deny grant")
            elif grant.effect == "allow":
                return EvaluationResult(allowed=True, decision="ALLOW_GRANT", reason=f"Explicit allow grant")

    # 3. Role Permission Check
    if action not in principal.permissions:
        return EvaluationResult(allowed=False, decision="DENY_NO_PERMISSION", reason=f"Missing permission {action!r}")

    # 4. Tenant Boundary Check & ABAC Attribute Evaluation
    ownership = await self.store.get_tool_ownership(resource)
    if ownership:
        if ownership.visibility != "public" and ownership.owner_org != principal.org_id:
            return EvaluationResult(allowed=False, decision="DENY_TENANT_BOUNDARY", reason="Cross-tenant access blocked")
        
        abac_res = ABACEvaluator.evaluate_tool_attributes(principal, resource, ownership, context)
        if not abac_res.allowed:
            return EvaluationResult(allowed=False, decision="DENY_ABAC_ATTRIBUTE", reason=abac_res.reason)

    # 5. Default Allow for Role-permitted Action
    return EvaluationResult(allowed=True, decision="ALLOW_ROLE", reason="Allowed by role permissions")
```

---

### B. MongoDB Async Connection Pooling ([`src/plugins/tenancy/mongo_store.py`](file:///d:/python/mcp_server/src/plugins/tenancy/mongo_store.py))

Modeled directly after *hire-pilot*:
```python
from motor.motor_asyncio import AsyncIOMotorClient

class MongoTenancyStore(TenancyStore):
    def __init__(self, dsn: str = "mongodb://localhost:27017", db_name: str = "mcp_tenancy"):
        self.client = AsyncIOMotorClient(
            dsn,
            maxPoolSize=200,
            minPoolSize=10,
            retryReads=True,
            retryWrites=True,
        )
        self.db = self.client[db_name]

    async def init_db(self) -> None:
        # Pre-create unique compound indexes idempotently
        await self.db.organizations.create_index("org_id", unique=True)
        await self.db.memberships.create_index([("principal_id", 1), ("org_id", 1)], unique=True)
        await self.db.tool_grants.create_index("id", unique=True)
```
