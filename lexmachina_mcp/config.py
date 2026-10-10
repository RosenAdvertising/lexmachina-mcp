"""Environment-only configuration for the Lex Machina MCP server."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

PRODUCTION_BASE_URL = "https://api.lexmachina.com"
SANDBOX_BASE_URL = "https://api.sandbox.lexmachina.com"
ALLOWED_BASE_URLS = frozenset({PRODUCTION_BASE_URL, SANDBOX_BASE_URL})
TOKEN_AUTH_METHODS = frozenset({"form", "basic"})


class ConfigurationError(ValueError):
    """Report an actionable server configuration problem."""


@dataclass(frozen=True, slots=True)
class Config:
    """Validated runtime settings sourced only from environment variables."""

    client_id: str
    client_secret: str
    base_url: str
    token_auth_method: str = "form"
    timeout_seconds: float = 30.0
    max_retries: int = 3
    backoff_base_seconds: float = 0.25

    def __post_init__(self) -> None:
        if self.token_auth_method not in TOKEN_AUTH_METHODS:
            raise ConfigurationError(
                "LEX_MACHINA_TOKEN_AUTH_METHOD must be form or basic; "
                "query-string client secrets are not supported."
            )

    @property
    def token_url(self) -> str:
        """Return the OAuth token URL for the configured environment."""

        return f"{self.base_url}/oauth2/token"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Config:
        """Load settings or raise an error that names every missing credential."""

        values = os.environ if environ is None else environ
        required = ("LEX_MACHINA_CLIENT_ID", "LEX_MACHINA_CLIENT_SECRET")
        missing = [name for name in required if not values.get(name, "").strip()]
        if missing:
            joined = ", ".join(missing)
            raise ConfigurationError(
                f"Missing required environment variable(s): {joined}. "
                "Copy .env.example, set the values, and export them before starting the server."
            )

        base_url = values.get("LEX_MACHINA_BASE_URL", PRODUCTION_BASE_URL).strip().rstrip("/")
        if base_url not in ALLOWED_BASE_URLS:
            allowed = ", ".join(sorted(ALLOWED_BASE_URLS))
            raise ConfigurationError(
                f"LEX_MACHINA_BASE_URL must be one of: {allowed}; got {base_url!r}."
            )

        auth_method = values.get("LEX_MACHINA_TOKEN_AUTH_METHOD", "form").strip().lower()
        if auth_method not in TOKEN_AUTH_METHODS:
            allowed = ", ".join(sorted(TOKEN_AUTH_METHODS))
            raise ConfigurationError(
                f"LEX_MACHINA_TOKEN_AUTH_METHOD must be one of: {allowed}; got {auth_method!r}."
            )

        return cls(
            client_id=values["LEX_MACHINA_CLIENT_ID"].strip(),
            client_secret=values["LEX_MACHINA_CLIENT_SECRET"].strip(),
            base_url=base_url,
            token_auth_method=auth_method,
        )
