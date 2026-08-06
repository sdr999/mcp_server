"""Unit tests for AlertManager and WebhookChannel with retries."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from src.plugins.alerts import AlertManager, WebhookChannel


@pytest.mark.anyio
async def test_webhook_channel_retry_handling():
    channel = WebhookChannel("http://example.com/webhook", timeout=1.0, max_retries=2)

    mock_resp_500 = AsyncMock()
    mock_resp_500.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError("500 Server Error", request=None, response=None))

    mock_resp_200 = AsyncMock()
    mock_resp_200.raise_for_status = MagicMock(return_value=None)


    with patch.object(httpx.AsyncClient, "post", side_effect=[mock_resp_500, mock_resp_200]) as mock_post:
        await channel.send("Test Alert", "Alert message body", {"failed_modules": 1})
        assert mock_post.call_count == 2


@pytest.mark.anyio
async def test_alert_manager_evaluation():
    manager = AlertManager("http://example.com/webhook")
    assert len(manager.engine.rules) == 1
