"""Shared pytest configuration for the plugin test suite.

The admin/tenancy REST endpoints self-disable (503 "admin API disabled") unless
``MCP_ADMIN_TOKEN`` is set, and the admin tests authenticate with a fixed
``Bearer mysecretadmin``. Set that token at collection time (before any test
builds an AppContext) so the admin suite runs without a hand-set env var.

``setdefault`` means a value already present in the environment always wins.
"""
import os

os.environ.setdefault("MCP_ADMIN_TOKEN", "mysecretadmin")
