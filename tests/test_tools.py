"""One mocked HTTP round trip for every MCP tool."""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest
import respx

from lexmachina_mcp import server
from lexmachina_mcp.client import LexMachinaClient
from lexmachina_mcp.config import Config

BASE_URL = "https://api.sandbox.lexmachina.com"

TOOL_CASES: list[tuple[str, dict[str, Any], str, str, Any]] = [
    (
        "query_district_cases",
        {"query": {"caseStatus": {"include": ["Open"]}}, "limit": 2},
        "POST",
        "/query-district-cases",
        {"cases": [{"districtCaseId": 101, "url": "/district-cases/101"}]},
    ),
    (
        "get_district_case",
        {"district_case_id": 101, "include_docket": True},
        "GET",
        "/district-cases/101",
        {"districtCaseId": 101, "title": "Example v. Sample"},
    ),
    (
        "analyze_district_cases",
        {"analytic_type": "CaseCountByType", "district_case_query": {"courts": ["ded"]}},
        "POST",
        "/analyze-district-cases/from-query",
        {"totalCases": 1, "aggregation": [{"caseType": "Patent", "count": 1}]},
    ),
    (
        "search_law_firms",
        {"q": "Example", "limit": 2},
        "GET",
        "/search-law-firms",
        {"totalCount": 1, "page": 1, "nextPage": None, "lawFirms": [{"lawFirmId": 1}]},
    ),
    (
        "search_parties",
        {"q": "Example", "limit": 2},
        "GET",
        "/search-parties",
        {"totalCount": 1, "page": 1, "nextPage": None, "parties": [{"partyId": 2}]},
    ),
    (
        "find_district_cases",
        {"case_numbers": ["1:24-cv-00001"], "court": "D.N.J.", "limit": 2},
        "GET",
        "/find-district-cases",
        {"matches": [{"districtCaseId": 101}]},
    ),
    (
        "query_state_cases",
        {"query": {"courts": {"state": "CA", "include": ["Orange County"]}}, "limit": 2},
        "POST",
        "/query-state-cases",
        {"cases": [{"stateCaseId": 201, "url": "/state-cases/201"}]},
    ),
    (
        "get_state_case",
        {"state_case_id": 201, "include_docket": True},
        "GET",
        "/state-cases/201",
        {"stateCaseId": 201, "title": "Example State Matter"},
    ),
    (
        "query_appeals_cases",
        {"query": {"caseStatus": {"include": ["Open"]}}, "limit": 2},
        "POST",
        "/query-appeals-cases",
        {"cases": [{"appealsCaseId": 301, "url": "/appeals-cases/301"}]},
    ),
    (
        "get_appeals_case",
        {"appeals_case_id": 301, "include_docket": True},
        "GET",
        "/appeals-cases/301",
        {"appealsCaseId": 301, "title": "Example Appeal"},
    ),
    (
        "search_attorneys",
        {"q": "Smith", "limit": 2},
        "GET",
        "/search-attorneys",
        {"totalCount": 1, "page": 1, "nextPage": None, "attorneys": [{"attorneyId": 4}]},
    ),
    (
        "search_judges",
        {"q": "Smi", "limit": 2},
        "GET",
        "/search-judges",
        {"federalJudges": [{"federalJudgeId": 5}], "stateJudges": []},
    ),
    (
        "list_alerts",
        {"limit": 2},
        "GET",
        "/alerts",
        {"alerts": [{"alertId": 6, "customName": "New matters"}]},
    ),
    (
        "get_alert_run_results",
        {"alert_id": 6, "date": date(2026, 8, 1), "limit": 2},
        "GET",
        "/alerts/runs/6/2026-08-01",
        {"alertId": 6, "count": 1, "items": [{"districtCaseId": 101}]},
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "arguments", "method", "path", "response_payload"),
    TOOL_CASES,
    ids=[case[0] for case in TOOL_CASES],
)
async def test_each_tool_makes_its_documented_round_trip(
    respx_mock: respx.MockRouter,
    config: Config,
    tool_name: str,
    arguments: dict[str, Any],
    method: str,
    path: str,
    response_payload: Any,
) -> None:
    token_route = respx_mock.post(f"{BASE_URL}/oauth2/token").mock(
        return_value=httpx.Response(200, json={"access_token": "mock-token", "expires_in": "3600"})
    )
    business_route = respx_mock.request(method, f"{BASE_URL}{path}").mock(
        return_value=httpx.Response(200, json=response_payload)
    )
    client = LexMachinaClient(config)
    server.configure_client(client)

    try:
        result = await getattr(server, tool_name)(**arguments)
    finally:
        server.configure_client(None)
        await client.aclose()

    assert isinstance(result, dict)
    assert token_route.call_count == 1
    assert business_route.call_count == 1
    assert business_route.calls[0].request.headers["Authorization"] == "Bearer mock-token"
