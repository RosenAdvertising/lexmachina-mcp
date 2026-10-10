# Lex Machina MCP server

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/RosenAdvertising/lexmachina-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/RosenAdvertising/lexmachina-mcp/actions/workflows/ci.yml)

A Python stdio [Model Context Protocol](https://modelcontextprotocol.io/) server that provides read-only access to Lex Machina litigation data. It currently exposes 14 tools for case search and retrieval, analytics, attorney and judge lookup, and alert results.

## Features

- Search and analyze federal district, state, and federal appeals cases.
- Retrieve complete case records, optionally including docket entries.
- Resolve law firms, parties, attorneys, judges, and known federal case numbers.
- List application alerts and retrieve results for a dated alert run.
- Paginate within a caller-selected result limit (1–100); case and entity searches cap page size at 100.
- Authenticate with OAuth client credentials, cache bearer tokens, and retry transient transport, rate-limit, and server errors with bounded backoff.

All tools are read-only. Query and analysis endpoints may use HTTP POST, but they retrieve or analyze data; the server does not expose business-data write operations.

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Lex Machina API application credentials with the Lex Machina API service activated
- An MCP-compatible client

## Install from source

```bash
git clone https://github.com/RosenAdvertising/lexmachina-mcp.git
cd lexmachina-mcp
uv sync --locked
```

## Configure credentials

Set these environment variables in the environment used to launch the server:

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `LEX_MACHINA_CLIENT_ID` | Yes | — | OAuth application client ID. |
| `LEX_MACHINA_CLIENT_SECRET` | Yes | — | OAuth application client secret. |
| `LEX_MACHINA_BASE_URL` | No | `https://api.lexmachina.com` | API base URL. The documented production and sandbox URLs are accepted. |
| `LEX_MACHINA_TOKEN_AUTH_METHOD` | No | `form` | OAuth client credential transport: `form` or `basic`. Query-string client secrets are rejected; use form-body or HTTP Basic authentication. |

See [.env.example](.env.example) for placeholder values and the sandbox URL. Activate the sandbox service separately if using it. Keep real credentials outside source control.

## MCP client configuration

Configure your MCP client to start the server from the cloned repository directory. For example, Claude Desktop accepts:

```json
{
  "mcpServers": {
    "lexmachina": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/lexmachina-mcp", "run", "lexmachina-mcp"],
      "env": {
        "LEX_MACHINA_CLIENT_ID": "your-client-id",
        "LEX_MACHINA_CLIENT_SECRET": "your-client-secret"
      }
    }
  }
}
```

Replace the directory and credential placeholders with values for your machine. Use the `env` object or your client's supported secret store to provide credentials.

## HTTP mode

Stdio is the default. Set `LEXMACHINA_MCP_TRANSPORT=streamable-http` to serve
stateless Streamable HTTP at `/mcp`. The SDK supports MCP 2026-07-28 and earlier
protocol clients on the same endpoint. Its default SSE response mode lets a
client disconnect cancel the request.

> **Security: this endpoint has no authentication and no TLS.** Anyone who can reach the port can run every tool, including write and delete tools, with this server's vendor credentials. Keep the default loopback bind (`127.0.0.1`), or put the server behind an authenticating TLS proxy on a private network. `LEXMACHINA_MCP_ALLOWED_HOSTS` and `LEXMACHINA_MCP_ALLOWED_ORIGINS` protect against browser DNS rebinding, not against direct callers. A proxy in front of it needs connection and idle timeouts: a legacy-style `GET /mcp` with `Accept: text/event-stream` holds a stream open until the client disconnects.

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `LEXMACHINA_MCP_TRANSPORT` | No | `stdio` | `stdio` or `streamable-http`; whitespace and case are normalized. |
| `LEXMACHINA_MCP_HOST` | No | `127.0.0.1` | Address on which to listen. |
| `PORT` | No | `8080` | Integer HTTP listening port. |
| `LEXMACHINA_MCP_ALLOWED_HOSTS` | On non-loopback hosts | — | Comma-separated allowed Host headers, including ports where needed; `host:*` allows any port. |
| `LEXMACHINA_MCP_ALLOWED_ORIGINS` | No | — | Comma-separated allowed browser origins. On non-loopback hosts, an omitted list rejects requests with an Origin header. |
| `LEX_MACHINA_CLIENT_ID` | For tool calls | — | Existing OAuth application client ID, supplied through the server environment. |
| `LEX_MACHINA_CLIENT_SECRET` | For tool calls | — | Existing OAuth application client secret, supplied through the server environment. |
| `LEX_MACHINA_BASE_URL` | No | `https://api.lexmachina.com` | Existing production or sandbox API URL. |
| `LEX_MACHINA_TOKEN_AUTH_METHOD` | No | `form` | Existing OAuth credential transport: `form` or `basic`. |

With your vendor credentials already exported:

```bash
LEXMACHINA_MCP_TRANSPORT=streamable-http PORT=8080 uv run lexmachina-mcp
```

Connect your HTTP MCP client to `http://127.0.0.1:8080/mcp`. Loopback hosts
(`127.0.0.1`, `localhost`, `::1`) use the SDK's Host and Origin validation.
For another bind address, provide `LEXMACHINA_MCP_ALLOWED_HOSTS` and any browser
origins you intend to allow. Vendor credentials always come from the server's
environment, including in HTTP mode.

## Tools

The server registers 14 tools:

| Tool | Purpose |
| --- | --- |
| `query_district_cases` | Find federal district cases using documented filters. |
| `get_district_case` | Retrieve a district case record, optionally with its docket. |
| `analyze_district_cases` | Aggregate a district case query. |
| `search_law_firms` | Find law firm IDs by name. |
| `search_parties` | Find company or litigant IDs by name. |
| `find_district_cases` | Resolve known federal case numbers to case IDs. |
| `query_state_cases` | Find enhanced state cases; a state court filter is required. |
| `get_state_case` | Retrieve an enhanced state case record, optionally with its docket. |
| `query_appeals_cases` | Find federal appeals cases. |
| `get_appeals_case` | Retrieve an appeals case record, optionally with its docket. |
| `search_attorneys` | Find attorney IDs by name. |
| `search_judges` | Find judges across supported judge types. |
| `list_alerts` | List alerts available to the application. |
| `get_alert_run_results` | Retrieve items from a dated alert run. |

Every result-listing tool has a bounded `limit`. The server preserves API result fields and reports pagination metadata where it paginates. API access and available data depend on the Lex Machina account and activated services. `LEX_MACHINA_TOKEN_AUTH_METHOD` accepts only form-body or HTTP Basic credentials; query-string transport fails closed.

## Development

```bash
uv sync --locked
uv run --locked pytest -q
uv run --locked ruff check .
```

Tests mock HTTP traffic and run offline.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).

## Local setup and verification

The server starts and answers MCP initialization and tool listing without credentials.
Tools report a configuration error until the required environment is provided.
Run `lexmachina-mcp-setup` for environment-variable instructions, then restart your MCP
launcher with those variables exported. Run `lexmachina-mcp-verify` to validate local
configuration (exit 2 if missing or invalid). This command does not contact the
vendor or prove authentication. Neither command saves or prints secret values.

The [public authentication guide](https://developer.lexmachina.com/authentication/bearer-tokens/)
shows a POST with `--data-urlencode` form fields. Its prose is ambiguous about the
message body, but it does not require query-string credentials.
