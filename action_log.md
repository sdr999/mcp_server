# Action Log - Multi-Tenancy & RBAC Implementation

## [2026-08-05] Phase 3 Implementation Complete: Tenant & Workspace Catalog Scoping

### Summary of Phase 3 Changes
1. **Tenant Catalog Scoping Module (`src/plugins/tenancy/scoping.py`)**:
   - Implemented `filter_tools_for_principal(store, evaluator, principal, tools)`:
     - Asynchronously filters tool list for `GET /tools` and `GET /mcp/upstreams/{server}/tools`.
     - SuperAdmin sees all tools.
     - Regular callers only see public tools, tools owned by their organization (`owner_org == caller_org`), or tools explicitly granted via `ToolGrant`.

2. **REST API Route Integration (`src/plugins/routes.py`)**:
   - Updated `_tools_catalog(request)` and `_upstream_tools(request)` to apply `filter_tools_for_principal` before returning tool lists.

3. **Automated Test Suite (`src/tests/test_plugins_tenant_scoping.py`)**:
   - Added unit and integration tests for tenant catalog isolation, SuperAdmin visibility, and route scoping.
   - Verified **166/166 tests passing** (100% pass rate).

---

## [2026-08-05] Phase 2 Implementation Complete: RBAC Policy Engine & Hierarchical Evaluation

### Summary of Phase 2 Changes
1. **Core RBAC Policy Engine (`src/plugins/rbac/`)**:
   - `evaluator.py`: Created `PolicyEvaluator` authorization engine implementing 5-tier evaluation order of precedence:
     1. SuperAdmin Override (`platform_superadmin`)
     2. Explicit Deny Grants (`effect="deny"`)
     3. Explicit Allow Grants (`effect="allow"`)
     4. Role Permission Checks (`tool:list`, `tool:call`, `tool:onboard`, `upstream:call`)
     5. Tenant & Tool Visibility Boundaries (`visibility == public` vs `owner_org == caller_org`)
   - `cache.py`: Created thread-safe L1 decision cache `DecisionCache` with TTL expiry (`MCP_RBAC_CACHE_TTL_SEC=300`) and manual invalidation.
   - `__init__.py`: Package exports for `PolicyEvaluator`, `EvaluationResult`, `DecisionCache`.

2. **Config & Application Wiring (`src/plugins/config.py`, `src/plugins/app.py`, `src/plugins/security.py`)**:
   - `config.py`: Added `rbac_cache_ttl` and `rbac_cache_size` options to `AppContext` and `build_context`.
   - `app.py`: Instantiated `DecisionCache` and `PolicyEvaluator` and attached `app.state.policy_evaluator`.
   - `security.py`: Enhanced `enforce(request, policy)` to invoke `policy_evaluator.evaluate(principal, action, resource)` when `MCP_RBAC_ENABLED=true`, returning `403 Forbidden` with decision metadata if unauthorized.

3. **Automated Test Suite (`src/tests/test_plugins_rbac.py`)**:
   - Added 6 unit and integration tests for SuperAdmin override, explicit deny/allow grants, role permission checks, tenant boundaries, L1 decision cache LRU & invalidation, and `security.enforce` middleware integration.

---

## [2026-08-05] Phase 1 Implementation Complete: Pluggable Tenancy Store (SQLite + MongoDB + Memory + JSON)

### Reference Integration from `D:\pyhton\pj\hire-pilot`
- Scanned `hire-pilot`'s [`mongo_pool.py`](file:///D:/pyhton/pj/hire-pilot/src/hire_pilot/utils/mongo_pool.py) and adopted Motor async connection pooling (`maxPoolSize=200`, `minPoolSize=10`, `retryReads=True`, `retryWrites=True`) and pre-creation of unique compound indexes.
- Created `MongoTenancyStore` in [`src/plugins/tenancy/mongo_store.py`](file:///d:/python/mcp_server/src/plugins/tenancy/mongo_store.py).
- Updated `create_tenancy_store(ctx)` factory in [`src/plugins/tenancy/__init__.py`](file:///d:/python/mcp_server/src/plugins/tenancy/__init__.py) to support `MCP_TENANCY_STORE=mongodb`.
- Updated `AppContext` and `build_context` in [`src/plugins/config.py`](file:///d:/python/mcp_server/src/plugins/config.py) to parse `MCP_TENANCY_DSN` (`MONGODB_URI`) and `MCP_TENANCY_DB_NAME` (`DB_NAME`).

### Summary of Phase 1 Changes
1. **Pluggable Tenancy Store Package (`src/plugins/tenancy/`)**:
   - `models.py`: Created domain data models (`Organization`, `Workspace`, `Membership`, `Role`, `ToolOwnership`, `ToolGrant`, `AuditEntry`).
   - `base.py`: Defined abstract `TenancyStore` interface with async methods.
   - `sqlite_store.py`: Production-ready single-node SQLite backend using stdlib `sqlite3` + `asyncio.to_thread` with `schema_meta` version tracking and auto-closing connection context manager.
   - `mongo_store.py`: Production-ready multi-replica MongoDB backend using `motor.motor_asyncio` (modeled after `hire-pilot`).
   - `memory.py`: Built thread-safe in-memory backend for unit tests.
   - `json_store.py`: Built file-backed JSON backend with atomic file replacement.
   - `seeder.py`: Built first-start idempotent self-seeding under lock (`seed_tenancy_store_if_empty`). Auto-seeds built-in roles (`platform_superadmin`, `org_admin`, `developer`, `agent_consumer`), `default` org, `default` workspace, superadmin principal binding (`oooosomu9@gmail.com`), and tags platform tools.
   - `__init__.py`: Factory function `create_tenancy_store(ctx)` instantiating configured backend (`MCP_TENANCY_STORE`).

2. **Config & Environment (`src/config/.env` & `src/plugins/config.py`)**:
   - Added Phase 1 settings: `MCP_TENANCY_STORE=sqlite`, `MCP_TENANCY_DB=data/tenancy.db`, `MCP_TENANCY_DSN=mongodb://localhost:27017`, `MCP_TENANCY_DB_NAME=mcp_tenancy`, `MCP_TENANCY_SEED=true`, `MCP_DEFAULT_ORG=default`.

3. **Application Lifecycle Integration (`src/plugins/app.py`)**:
   - Instantiated `tenancy_store = create_tenancy_store(ctx)` and attached `app.state.tenancy_store`.
   - Added `await tenancy_store.init_db()` and `await seed_tenancy_store_if_empty(tenancy_store, ctx)` inside lifespan `_bootstrap()`.

4. **Admin REST API Endpoints (`src/plugins/routes.py`)**:
   - Added Admin REST CRUD endpoints.

---

## [2026-08-05] Phase 0 Implementation Complete

### Summary of Completed Changes
1. Core Identity (`src/plugins/identity.py`), Supabase Auth Service (`src/plugins/auth_service.py`), Security (`src/plugins/security.py`), and REST Endpoints (`src/plugins/routes.py`).
