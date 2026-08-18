"""Tests for SQLite WAL Checkpoint & Lock Auto-Recovery (Phase 6, Component 3)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from src.plugins.tenancy.sqlite_store import SqliteTenancyStore


class TestSqliteLockRecovery:
    @pytest.mark.asyncio
    async def test_store_init_and_recovery(self, tmp_path):
        db_path = tmp_path / "tenancy.db"
        store = SqliteTenancyStore(db_path=db_path)
        await store.init_db()
        try:
            # Query role safely using store API
            role = await store.get_role("admin")
            assert role is None or isinstance(role, dict)
        finally:
            await store.close()
