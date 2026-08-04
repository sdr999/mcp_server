"""Plugin components for the MCP tool server (``main.py``).

Each module owns one feature so the server can be reasoned about, tested, and
changed a piece at a time:

* ``config``        -- environment/CLI parsing into an ``AppContext``.
* ``signing``        -- supply-chain hardening (signed tool manifest).
* ``tool_loader``    -- fault-isolated tool discovery/registration.
* ``watcher``        -- local filesystem hot-reload.
* ``notifications``  -- best-effort ``tools/list_changed`` push to clients.
* ``security``       -- API-key / JWT auth plumbing.
* ``routes``         -- health, readiness, status, catalog, metrics, admin HTTP routes.
* ``cli``            -- ``--validate`` / ``--sign`` CLI utilities.
* ``app``            -- wires the above into a single ASGI app.

This server has no Azure (or other remote file-share) dependency: tools are
always served from a local directory, with a filesystem watcher providing
hot-reload.
"""
