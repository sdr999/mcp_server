# Action Log - Multi-Tenancy & RBAC Implementation

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
   - Verified **163/163 tests passing** (100% pass rate).

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
   - Added Admin REST CRUD endpoints:
     - `POST /admin/orgs` (Create Organization)
     - `GET /admin/orgs` (List Organizations)
     - `DELETE /admin/orgs/{org}` (Delete Organization)
     - `POST /admin/orgs/{org}/workspaces` (Create Workspace)
     - `GET /admin/orgs/{org}/workspaces` (List Workspaces)
     - `POST /admin/orgs/{org}/members` (Bind User/Service to Role)
     - `GET /admin/orgs/{org}/members` (List Members)

---

## [2026-08-05] Phase 0 Implementation Complete

### Summary of Completed Changes
1. **Config & Environment (`src/config/.env` & `src/plugins/config.py`)**:
   - Added Supabase URL (`https://bplpycqmizyztxqwglgb.supabase.co`), publishable key, Key ID (`f0b20cc1-ad6a-4435-ae6d-0fd78195a950`), JWKS URL, and SuperAdmin Email (`oooosomu9@gmail.com`).
   - Exposed `supabase_url`, `supabase_key`, `supabase_jwt_kid`, `superadmin_email`, `rbac_enabled`, `tenant_header`, `workspace_header` on `AppContext`.

2. **Core Identity Module (`src/plugins/identity.py`)**:
   - Implemented `Principal` dataclass (`principal_id`, `issuer`, `subject`, `kind`, `org_id`, `workspace_id`, `roles`, `permissions`, `metadata`).
   - Implemented `derive_principal_id(issuer, subject)` using canonical `sha256(json.dumps([issuer, subject]))`.
   - Implemented `ContextVar[Optional[Principal]]` (`current_principal_var`) for request-scoped access across async tasks.
   - Implemented thread-safe `TokenCache` LRU cache with `sha256(token)` keying and dynamic `min(300, exp - now)` TTL.
   - Implemented `IdentityMiddleware(BaseHTTPMiddleware)` with `try...finally` context leakage prevention and header sanitization.

3. **Supabase Auth REST Service (`src/plugins/auth_service.py`)**:
   - Implemented `SupabaseAuthService` with non-blocking `httpx.AsyncClient` methods.

4. **Security & Protocol Integration (`src/plugins/security.py` & `src/plugins/app.py`)**:
   - Enhanced `_jwt_ok` to integrate `TokenCache` and extract Supabase claims into `Principal`.
   - Mounted `IdentityMiddleware` into Starlette pipeline in `build_app`.
   - Attached `supabase_auth` instance to `app.state`.

5. **REST API Endpoints (`src/plugins/routes.py`)**:
   - Added `GET /whoami` to return the caller's resolved `Principal`.
   - Added `POST /auth/signup`, `POST /auth/signin`, `POST /auth/refresh`, `POST /auth/forgot-password`.
