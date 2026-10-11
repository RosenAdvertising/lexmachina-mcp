# Lex Machina MCP server

[![CI](https://github.com/RosenAdvertising/lexmachina-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/RosenAdvertising/lexmachina-mcp/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-2026--07--28-7C3AED.svg)](https://modelcontextprotocol.io)

Give Claude and other MCP clients read-only access to Lex Machina litigation data and analytics.

Lex Machina MCP server is a [Model Context Protocol](https://modelcontextprotocol.io) server for Lex Machina, a litigation analytics platform. It registers 14 tools, all read-only, for case search and retrieval, analytics, attorney and judge lookup, and alert results. It runs over stdio by default, for desktop clients such as Claude Desktop, and offers an opt-in stateless Streamable HTTP mode that implements MCP specification 2026-07-28. Lex Machina credentials stay on the machine that runs the server: they come from environment variables, never from the client.

## Features

- Search and analyze federal district, state, and federal appeals cases.
- Retrieve complete case records, optionally including docket entries.
- Resolve law firms, parties, attorneys, judges, and known federal case numbers.
- List application alerts and retrieve results for a dated alert run.
- Paginate within a caller-selected result limit (1–100); case and entity searches cap page size at 100.
- Authenticate with OAuth client credentials, cache bearer tokens, and retry transient transport, rate-limit, and server errors with bounded backoff.

All tools are read-only. Query and analysis endpoints may use HTTP POST, but they retrieve or analyze data; the server does not expose business-data write operations.

## Tools

The server registers 14 tools, all read-only.

| Tool | What it does |
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

Every result-listing tool has a bounded `limit` (1 to 100, default 25). The server preserves API result fields and reports pagination metadata where it paginates. API access and available data depend on the Lex Machina account and activated services.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Lex Machina API application credentials with the Lex Machina API service activated
- An MCP client such as Claude Desktop

## Installation

Install [uv](https://docs.astral.sh/uv/), then clone the repository and install its locked dependencies:

```bash
git clone https://github.com/RosenAdvertising/lexmachina-mcp.git
cd lexmachina-mcp
uv sync --locked
```

## Configuration

Lex Machina credentials come from environment variables. Set them in the environment that launches the server, such as the `env` object in your MCP client configuration.

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `LEX_MACHINA_CLIENT_ID` | Yes | None | OAuth application client ID. |
| `LEX_MACHINA_CLIENT_SECRET` | Yes | None | OAuth application client secret. |
| `LEX_MACHINA_BASE_URL` | No | `https://api.lexmachina.com` | API base URL. Only the production URL and the sandbox URL (`https://api.sandbox.lexmachina.com`) are accepted. |
| `LEX_MACHINA_TOKEN_AUTH_METHOD` | No | `form` | How the OAuth client credentials are sent: `form` (form body) or `basic` (HTTP Basic). Query-string client secrets are rejected. |

See [.env.example](.env.example) for placeholder values and the sandbox URL. Activate the sandbox service separately if using it. Keep real credentials outside source control. The server does not load `.env` files. Lex Machina's [developer documentation](https://developer.lexmachina.com/) shows a POST with form-encoded fields, which is the default here.

The server starts and answers MCP initialization and tool listing without credentials. Tools report a configuration error until the required environment is provided. Two commands help with setup:

```bash
uv run lexmachina-mcp-setup
uv run lexmachina-mcp-verify
```

`lexmachina-mcp-setup` prints environment-variable instructions. `lexmachina-mcp-verify` validates the local configuration and exits with code 2 if it is missing or invalid; it does not contact Lex Machina or prove authentication. Neither command saves or prints secret values.

## Usage with Claude Desktop

Add the server to Claude Desktop's configuration file (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, `%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "lexmachina": {
      "command": "uv",
      "args": ["run", "--locked", "--directory", "/absolute/path/to/lexmachina-mcp", "lexmachina-mcp"],
      "env": {
        "LEX_MACHINA_CLIENT_ID": "your-client-id",
        "LEX_MACHINA_CLIENT_SECRET": "your-client-secret"
      }
    }
  }
}
```

Replace `/absolute/path/to/lexmachina-mcp` with the path of your clone and the placeholders with your credentials. Keep real credentials in your client's protected environment or secret store. Restart Claude Desktop after saving. Any other stdio MCP client uses the same command and arguments.

## HTTP mode

Stdio is the default. Set `LEXMACHINA_MCP_TRANSPORT=streamable-http` to serve the stateless Streamable HTTP transport from MCP specification 2026-07-28 at `/mcp`. Each request stands alone: no initialization handshake and no `Mcp-Session-Id`. Clients on earlier protocol versions are served on the same endpoint.

> **Security: this endpoint has no authentication and no TLS.** Anyone who can reach the port can run every tool with this server's vendor credentials. Keep the default loopback bind (`127.0.0.1`), or put the server behind an authenticating TLS proxy on a private network. `LEXMACHINA_MCP_ALLOWED_HOSTS` and `LEXMACHINA_MCP_ALLOWED_ORIGINS` protect against browser DNS rebinding, not against direct callers. A proxy in front of it needs connection and idle timeouts: a legacy-style `GET /mcp` with `Accept: text/event-stream` holds a stream open until the client disconnects.

| Variable | Default | Purpose |
| --- | --- | --- |
| `LEXMACHINA_MCP_TRANSPORT` | `stdio` | `stdio` or `streamable-http`; whitespace and case are normalized, and an empty value selects stdio. |
| `LEXMACHINA_MCP_HOST` | `127.0.0.1` | Bind address. `127.0.0.1`, `localhost` and `::1` use the SDK's built-in Host and Origin checks; any other value requires `LEXMACHINA_MCP_ALLOWED_HOSTS`. |
| `PORT` | `8080` | Port; must be an integer. |
| `LEXMACHINA_MCP_ALLOWED_HOSTS` | unset | Comma-separated `Host` header values accepted on a non-loopback bind, such as `mcp.example.com:8080` or `mcp.example.com:*`. |
| `LEXMACHINA_MCP_ALLOWED_ORIGINS` | unset | Comma-separated `Origin` values accepted on a non-loopback bind, such as `https://client.example.com`. Requests without an `Origin` header are accepted; any other `Origin` is refused, including when this is unset. |

Lex Machina credentials come from the same configuration as stdio (see [Configuration](#configuration)), never from the request.

With the Lex Machina variables from Configuration exported in the process environment, run:

```bash
LEXMACHINA_MCP_TRANSPORT=streamable-http PORT=8080 uv run --locked lexmachina-mcp
```

Point the MCP client at `http://127.0.0.1:8080/mcp`.

## Error handling

A failed tool call returns an MCP error result (`isError`) with a fixed message. Lex Machina's response text is never returned to the client and is not written to the log.

| Situation | The message begins |
| --- | --- |
| Missing or invalid configuration, including a base URL other than the production or sandbox URL | `lexmachina is not configured or its configuration is invalid.` It names the two credential variables and the `lexmachina-mcp-setup` command. |
| HTTP 401 | `Authentication failed.` |
| HTTP 403 | `Access denied.` |
| HTTP 404 | `Resource not found.` |
| HTTP 429 | `Rate limit reached.` |
| HTTP 5xx | `Service unavailable.` |
| Any other HTTP error, or a response that is not the expected JSON | `Request rejected or response invalid.` |
| Network failure or timeout | `Connection failed; the operation outcome may be unknown.` |

HTTP errors from the OAuth token request map the same way. A record ID that is not a plain identifier is rejected before any request is sent.

Requests that fail with a network error, HTTP 429 or any HTTP 5xx are retried up to 3 times, including OAuth token requests. The wait before a retry is the `Retry-After` value when it is a number, and otherwise 0.25, 0.5 and 1 seconds. Requests time out after 30 seconds. These retry and timeout settings are fixed; they are not environment variables.

At startup the server exits with a message and status 1 on an unsupported `LEXMACHINA_MCP_TRANSPORT`, a `PORT` that is not an integer, or a non-loopback `LEXMACHINA_MCP_HOST` without `LEXMACHINA_MCP_ALLOWED_HOSTS`. Missing credentials do not stop the server from starting; tool calls report the configuration error instead.

## Testing

The test suite runs offline and needs no Lex Machina account: every Lex Machina API call is intercepted at the HTTP layer with `respx`. It covers each tool's requests and responses, input validation, error handling, credential loading, pagination and retries, the stdio server, and the Streamable HTTP transport including the 2026-07-28 wire format, Host and Origin checks and stateless requests.

```bash
uv sync --locked
uv run --locked pytest -q
uv run --locked ruff check .
```

CI runs the suite on every push and pull request to `main`.

## License

MIT. See [LICENSE](LICENSE).
