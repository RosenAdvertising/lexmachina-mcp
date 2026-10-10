"""Configuration and startup behavior tests."""

from __future__ import annotations

import pytest

from lexmachina_mcp.config import Config, ConfigurationError


def test_missing_credentials_name_every_required_environment_variable() -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        Config.from_env({})

    message = str(exc_info.value)
    assert "LEX_MACHINA_CLIENT_ID" in message
    assert "LEX_MACHINA_CLIENT_SECRET" in message


def test_startup_without_credentials_runs_stdio(monkeypatch, capsys) -> None:
    from lexmachina_mcp import server
    from lexmachina_mcp.runtime import MCPServer

    seen = []
    monkeypatch.setattr(MCPServer, "run", lambda self, **kwargs: seen.append(kwargs))
    server.main()
    assert seen == [{"transport": "stdio"}]
    assert "Traceback" not in capsys.readouterr().err


def test_config_rejects_undocumented_base_url() -> None:
    with pytest.raises(ConfigurationError, match="LEX_MACHINA_BASE_URL"):
        Config.from_env(
            {
                "LEX_MACHINA_CLIENT_ID": "id",
                "LEX_MACHINA_CLIENT_SECRET": "secret",
                "LEX_MACHINA_BASE_URL": "https://example.test",
            }
        )
