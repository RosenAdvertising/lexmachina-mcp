"""MCP tool registration and transport entry points for Lex Machina."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date as Date
from typing import Annotated, Any, Literal

from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field
from starlette.applications import Starlette

from lexmachina_mcp import __version__
from lexmachina_mcp.paths import path_id
from lexmachina_mcp.runtime import LazyClient
from lexmachina_mcp.runtime import SafeMCPServer as MCPServer

from .client import JSONObject, LexMachinaAPIError, LexMachinaClient

DEFAULT_LIMIT = 25
MAX_LIMIT = 100
STREAMABLE_HTTP_TRANSPORT = "streamable-http"

Limit = Annotated[
    int,
    Field(
        description="Maximum number of results to return across all fetched pages.",
        ge=1,
        le=MAX_LIMIT,
    ),
]
DistrictCaseQuery = Annotated[
    dict[str, Any],
    Field(
        description=(
            "Federal district filters using documented camelCase fields: caseStatus, caseTypes, "
            "caseTags, dates, judges, magistrates, events, lawFirms, attorneys, parties, courts, "
            "resolutions, findings, remedies, damages, patents, mdl, appellateDecisions, and "
            "ordering. The limit parameter controls page and pageSize."
        )
    ),
]
StateCaseQuery = Annotated[
    dict[str, Any],
    Field(
        description=(
            "Enhanced state filters using documented camelCase fields. courts is required and "
            "must contain one state plus optional include/exclude; other fields are caseStatus, "
            "caseTypes, caseTags, dates, judges, events, lawFirms, attorneys, parties, "
            "resolutions, damages, rulings, and ordering."
        )
    ),
]
AppealsCaseQuery = Annotated[
    dict[str, Any],
    Field(
        description=(
            "Federal appeals filters using documented camelCase fields: courts, caseStatus, "
            "caseTags, dates, judges, lawFirms, attorneys, parties, originatingVenues, "
            "originatingCases, resolutions, supremeCourtDecisions, and ordering. The limit "
            "parameter controls page and pageSize."
        )
    ),
]

_client: LexMachinaClient | LazyClient | None = None


@asynccontextmanager
async def _lifespan(_: MCPServer[Any]) -> AsyncIterator[None]:
    """Create and close the HTTP client inside the server's event loop."""

    global _client
    created_client: LexMachinaClient | LazyClient | None = None
    if _client is None:
        created_client = LazyClient()
        _client = created_client
    try:
        yield
    finally:
        if created_client is not None:
            await created_client.aclose()
            _client = None


mcp = MCPServer(
    "lex-machina",
    title="Lex Machina",
    description="Read-only access to Lex Machina litigation data.",
    instructions=(
        "Use search tools to resolve entity IDs, query tools to discover case IDs, and detail "
        "tools to retrieve complete matters. Query POSTs are read-only."
    ),
    version=__version__,
    lifespan=_lifespan,
)


def configure_client(client: LexMachinaClient | LazyClient | None) -> None:
    """Set the process-scoped API client used by tool handlers."""

    global _client
    _client = client


def _get_client() -> LexMachinaClient | LazyClient:
    global _client
    if _client is None:
        _client = LazyClient()
    return _client


def _as_object(payload: Any, *, list_key: str) -> JSONObject:
    if isinstance(payload, dict):
        return dict(payload)
    if isinstance(payload, list):
        return {list_key: payload}
    raise LexMachinaAPIError(
        200, "Lex Machina returned JSON that was not an object or list.", payload
    )


def _limit_lists(payload: JSONObject, keys: tuple[str, ...], limit: int) -> JSONObject:
    """Apply a client-side total limit to endpoints without documented pagination."""

    remaining = limit
    found_list = False
    result = dict(payload)
    for key in keys:
        value = result.get(key)
        if not isinstance(value, list):
            continue
        found_list = True
        selected = value[:remaining]
        result[key] = selected
        remaining -= len(selected)
    if found_list:
        result["returnedCount"] = limit - remaining
    return result


@mcp.tool()
async def query_district_cases(
    query: DistrictCaseQuery,
    limit: Limit = DEFAULT_LIMIT,
) -> JSONObject:
    """Find federal district matters that match your courts, participants, outcomes, or dates."""

    return await _get_client().paginate_case_query(
        "/query-district-cases", query, limit=limit, page_size_cap=100
    )


@mcp.tool()
async def get_district_case(
    district_case_id: Annotated[
        int, Field(description="Lex Machina federal district case ID.", ge=1)
    ],
    include_docket: Annotated[
        bool, Field(description="Retrieve all docket entries when true.")
    ] = False,
) -> JSONObject:
    """Retrieve the full record for a federal district case."""

    params = {"docket_retrieval": "all"} if include_docket else None
    payload = await _get_client().request_json(
        "GET", f"/district-cases/{path_id(district_case_id, 'district_case_id')}", params=params
    )
    return _as_object(payload, list_key="cases")


@mcp.tool()
async def analyze_district_cases(
    analytic_type: Annotated[
        Literal["CaseCountByType", "PartyCountByRole", "LawFirmCountByRole"],
        Field(description="Aggregation to calculate for the matching district cases."),
    ],
    district_case_query: Annotated[
        dict[str, Any],
        Field(description="District case filters using documented camelCase query fields."),
    ],
) -> JSONObject:
    """Summarize a federal district case cohort by case type, party role, or law-firm role."""

    payload = await _get_client().request_json(
        "POST",
        "/analyze-district-cases/from-query",
        json={"analyticType": analytic_type, "districtCaseQuery": district_case_query},
    )
    return _as_object(payload, list_key="aggregation")


@mcp.tool()
async def search_law_firms(
    q: Annotated[str, Field(description="All or part of a law-firm name.", min_length=1)],
    limit: Limit = DEFAULT_LIMIT,
) -> JSONObject:
    """Find Lex Machina law-firm IDs from all or part of a firm name."""

    return await _get_client().paginate_search(
        "/search-law-firms", query=q, result_key="lawFirms", limit=limit
    )


@mcp.tool()
async def search_parties(
    q: Annotated[
        str,
        Field(description="All or part of a company or litigant name.", min_length=1),
    ],
    limit: Limit = DEFAULT_LIMIT,
) -> JSONObject:
    """Find Lex Machina party IDs from all or part of a company or litigant name."""

    return await _get_client().paginate_search(
        "/search-parties", query=q, result_key="parties", limit=limit
    )


@mcp.tool()
async def find_district_cases(
    case_numbers: Annotated[
        list[str],
        Field(description="One or more known federal docket or case numbers.", min_length=1),
    ],
    court: Annotated[
        str | None,
        Field(description="Optional court filter used to narrow inclusive case-number matches."),
    ] = None,
    limit: Limit = DEFAULT_LIMIT,
) -> JSONObject:
    """Resolve known federal docket or case numbers to Lex Machina case IDs."""

    params: dict[str, Any] = {"caseNumbers": case_numbers}
    if court is not None:
        params["court"] = court
    payload = await _get_client().request_json("GET", "/find-district-cases", params=params)
    result = _as_object(payload, list_key="matches")
    return _limit_lists(result, ("districtCases", "cases", "matches"), limit)


@mcp.tool()
async def query_state_cases(
    query: StateCaseQuery,
    limit: Limit = DEFAULT_LIMIT,
) -> JSONObject:
    """Find enhanced state matters matching courts, participants, outcomes, or dates."""

    courts = query.get("courts")
    if not isinstance(courts, dict) or not isinstance(courts.get("state"), str):
        raise ValueError("query.courts must be an object containing exactly one non-empty state")
    if not courts["state"].strip():
        raise ValueError("query.courts.state must be non-empty")
    return await _get_client().paginate_case_query(
        "/query-state-cases", query, limit=limit, page_size_cap=100
    )


@mcp.tool()
async def get_state_case(
    state_case_id: Annotated[int, Field(description="Lex Machina enhanced state case ID.", ge=1)],
    include_docket: Annotated[
        bool, Field(description="Retrieve all docket entries when true.")
    ] = False,
) -> JSONObject:
    """Retrieve the full record for an enhanced state case."""

    params = {"docket_retrieval": "all"} if include_docket else None
    payload = await _get_client().request_json(
        "GET", f"/state-cases/{path_id(state_case_id, 'state_case_id')}", params=params
    )
    return _as_object(payload, list_key="cases")


@mcp.tool()
async def query_appeals_cases(
    query: AppealsCaseQuery,
    limit: Limit = DEFAULT_LIMIT,
) -> JSONObject:
    """Find federal appeals matters and their originating-case relationships."""

    return await _get_client().paginate_case_query(
        "/query-appeals-cases", query, limit=limit, page_size_cap=100
    )


@mcp.tool()
async def get_appeals_case(
    appeals_case_id: Annotated[
        int, Field(description="Lex Machina federal appeals case ID.", ge=1)
    ],
    include_docket: Annotated[
        bool, Field(description="Retrieve all docket entries when true.")
    ] = False,
) -> JSONObject:
    """Retrieve the full record for a federal appeals case."""

    params = {"docket_retrieval": "all"} if include_docket else None
    payload = await _get_client().request_json(
        "GET", f"/appeals-cases/{path_id(appeals_case_id, 'appeals_case_id')}", params=params
    )
    return _as_object(payload, list_key="cases")


@mcp.tool()
async def search_attorneys(
    q: Annotated[str, Field(description="All or part of an attorney name.", min_length=1)],
    limit: Limit = DEFAULT_LIMIT,
) -> JSONObject:
    """Find Lex Machina attorney IDs from all or part of an attorney name."""

    return await _get_client().paginate_search(
        "/search-attorneys", query=q, result_key="attorneys", limit=limit
    )


@mcp.tool()
async def search_judges(
    q: Annotated[
        str,
        Field(description="Beginning of a judge's last name.", min_length=1),
    ],
    limit: Limit = DEFAULT_LIMIT,
) -> JSONObject:
    """Find judge IDs across federal, magistrate, state, and bankruptcy judges."""

    payload = await _get_client().request_json("GET", "/search-judges", params={"q": q})
    result = _as_object(payload, list_key="judges")
    return _limit_lists(
        result,
        (
            "federalJudges",
            "magistrateJudges",
            "stateJudges",
            "bankruptcyJudges",
            "judges",
        ),
        limit,
    )


@mcp.tool()
async def list_alerts(limit: Limit = DEFAULT_LIMIT) -> JSONObject:
    """List alerts available to this Lex Machina application."""

    payload = await _get_client().request_json("GET", "/alerts")
    result = _as_object(payload, list_key="alerts")
    return _limit_lists(result, ("alerts",), limit)


@mcp.tool()
async def get_alert_run_results(
    alert_id: Annotated[int, Field(description="Lex Machina alert ID.", ge=1)],
    date: Annotated[Date, Field(description="Alert run date in ISO YYYY-MM-DD format.")],
    limit: Limit = DEFAULT_LIMIT,
) -> JSONObject:
    """Retrieve newly discovered items from a dated Lex Machina alert run."""

    payload = await _get_client().request_json(
        "GET", f"/alerts/runs/{path_id(alert_id, 'alert_id')}/{date.isoformat()}"
    )
    result = _as_object(payload, list_key="items")
    return _limit_lists(result, ("items",), limit)


def _requested_transport() -> str:
    return os.environ.get("LEXMACHINA_MCP_TRANSPORT", "stdio").strip().lower() or "stdio"


def _host() -> str:
    return os.environ.get("LEXMACHINA_MCP_HOST", "127.0.0.1").strip() or "127.0.0.1"


def _port() -> int:
    raw = os.environ.get("PORT", "8080").strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"PORT must be an integer, got {raw!r}") from exc


def _transport_security() -> TransportSecuritySettings | None:
    # These are the hosts for which the SDK enables loopback protection itself.
    if _host() in ("127.0.0.1", "localhost", "::1"):
        return None
    allowed_hosts = [
        value.strip()
        for value in os.environ.get("LEXMACHINA_MCP_ALLOWED_HOSTS", "").split(",")
        if value.strip()
    ]
    if not allowed_hosts:
        raise SystemExit(
            "LEXMACHINA_MCP_ALLOWED_HOSTS is required when LEXMACHINA_MCP_HOST "
            "is not a loopback host. Set a comma-separated list of allowed Host headers."
        )
    allowed_origins = [
        value.strip()
        for value in os.environ.get("LEXMACHINA_MCP_ALLOWED_ORIGINS", "").split(",")
        if value.strip()
    ]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


def create_serve_app() -> Starlette:
    """Build the stateless MCP HTTP app with the SDK's default SSE responses."""
    return mcp.streamable_http_app(
        streamable_http_path="/mcp",
        host=_host(),
        stateless_http=True,
        transport_security=_transport_security(),
    )


async def _serve_streamable_http() -> None:
    import uvicorn

    config = uvicorn.Config(
        create_serve_app(),
        host=_host(),
        port=_port(),
        log_level=mcp.settings.log_level.lower(),
        access_log=False,
    )
    await uvicorn.Server(config).serve()


def main() -> int:
    """Run the selected transport with deferred client configuration."""
    transport = _requested_transport()
    if transport == "stdio":
        mcp.run(transport="stdio")
        return 0
    if transport == STREAMABLE_HTTP_TRANSPORT:
        asyncio.run(_serve_streamable_http())
        return 0
    raise SystemExit(
        "Unsupported LEXMACHINA_MCP_TRANSPORT "
        f"{transport!r}; expected 'stdio' or '{STREAMABLE_HTTP_TRANSPORT}'."
    )


def run() -> None:
    """Console-script wrapper."""
    raise SystemExit(main())


if __name__ == "__main__":
    run()
