"""Fully mocked tests for authentication, retries, errors, and pagination."""

from __future__ import annotations

import json
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from lexmachina_mcp.client import LexMachinaAPIError, LexMachinaClient
from lexmachina_mcp.config import Config

BASE_URL = "https://api.sandbox.lexmachina.com"
TOKEN_URL = f"{BASE_URL}/oauth2/token"


def mock_token(router: respx.MockRouter) -> respx.Route:
    return router.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "mock-token", "token_type": "bearer", "expires_in": "3600"},
        )
    )


@pytest.mark.asyncio
async def test_happy_path_uses_form_oauth_and_bearer_token(
    respx_mock: respx.MockRouter, config: Config
) -> None:
    token_route = mock_token(respx_mock)

    def business_response(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer mock-token"
        return httpx.Response(200, json={"alerts": []})

    alerts_route = respx_mock.get(f"{BASE_URL}/alerts").mock(side_effect=business_response)

    async with LexMachinaClient(config) as client:
        assert await client.request_json("GET", "/alerts") == {"alerts": []}

    form = parse_qs(token_route.calls[0].request.content.decode())
    assert form == {
        "client_id": ["test-client-id"],
        "client_secret": ["test-client-secret"],
        "grant_type": ["client_credentials"],
    }
    assert token_route.call_count == 1
    assert alerts_route.call_count == 1


@pytest.mark.asyncio
async def test_auth_failure_surfaces_vendor_validation_message(
    respx_mock: respx.MockRouter, config: Config
) -> None:
    respx_mock.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            422,
            json={
                "detail": [
                    {
                        "loc": ["body", "client_secret"],
                        "msg": "client secret is invalid",
                        "type": "value_error",
                    }
                ]
            },
        )
    )

    async with LexMachinaClient(config) as client:
        with pytest.raises(LexMachinaAPIError) as exc_info:
            await client.request_json("GET", "/alerts")

    assert exc_info.value.status_code == 422
    assert "client secret is invalid" in str(exc_info.value)


@pytest.mark.asyncio
async def test_429_is_retried_with_retry_after(
    respx_mock: respx.MockRouter, config: Config
) -> None:
    mock_token(respx_mock)
    route = respx_mock.get(f"{BASE_URL}/alerts").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}, json={"message": "slow down"}),
            httpx.Response(200, json={"alerts": [{"alertId": 7}]}),
        ]
    )
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    async with LexMachinaClient(config, sleep=fake_sleep) as client:
        result = await client.request_json("GET", "/alerts")

    assert result == {"alerts": [{"alertId": 7}]}
    assert route.call_count == 2
    assert delays == [0.0]


@pytest.mark.asyncio
async def test_case_query_pagination_caps_pages_and_collects_limit(
    respx_mock: respx.MockRouter, config: Config
) -> None:
    mock_token(respx_mock)
    route = respx_mock.post(f"{BASE_URL}/query-district-cases").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "cases": [
                        {"districtCaseId": 1, "url": "/district-cases/1"},
                        {"districtCaseId": 2, "url": "/district-cases/2"},
                    ]
                },
            ),
            httpx.Response(
                200,
                json={"cases": [{"districtCaseId": 3, "url": "/district-cases/3"}]},
            ),
        ]
    )

    async with LexMachinaClient(config) as client:
        result = await client.paginate_case_query(
            "/query-district-cases",
            {"courts": {"include": ["ded"]}, "page": 99, "pageSize": 999},
            limit=3,
            page_size_cap=2,
        )

    bodies = [json.loads(call.request.content) for call in route.calls]
    assert bodies == [
        {"courts": {"include": ["ded"]}, "page": 1, "pageSize": 2},
        {"courts": {"include": ["ded"]}, "page": 2, "pageSize": 1},
    ]
    assert [item["districtCaseId"] for item in result["cases"]] == [1, 2, 3]
    assert result["pagesFetched"] == 2
    assert result["returnedCount"] == 3


@pytest.mark.asyncio
async def test_entity_search_follows_next_page(
    respx_mock: respx.MockRouter, config: Config
) -> None:
    mock_token(respx_mock)
    route = respx_mock.get(f"{BASE_URL}/search-law-firms").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "totalCount": 3,
                    "page": 1,
                    "nextPage": 2,
                    "lawFirms": [{"lawFirmId": 1}, {"lawFirmId": 2}],
                },
            ),
            httpx.Response(
                200,
                json={
                    "totalCount": 3,
                    "page": 2,
                    "nextPage": None,
                    "lawFirms": [{"lawFirmId": 3}],
                },
            ),
        ]
    )

    async with LexMachinaClient(config) as client:
        result = await client.paginate_search(
            "/search-law-firms", query="Example", result_key="lawFirms", limit=3, page_size_cap=2
        )

    assert route.calls[0].request.url.params["pageNumber"] == "1"
    assert route.calls[1].request.url.params["pageNumber"] == "2"
    assert [item["lawFirmId"] for item in result["lawFirms"]] == [1, 2, 3]
    assert result["returnedCount"] == 3
