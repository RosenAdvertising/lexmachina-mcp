"""Shared offline test fixtures."""

from __future__ import annotations

import pytest

from lexmachina_mcp.config import Config


@pytest.fixture
def config() -> Config:
    """Return non-secret test configuration for the sandbox hostname."""

    return Config(
        client_id="test-client-id",
        client_secret="test-client-secret",
        base_url="https://api.sandbox.lexmachina.com",
        backoff_base_seconds=0.001,
    )
