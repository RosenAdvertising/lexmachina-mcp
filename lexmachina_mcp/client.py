"""Thin asynchronous HTTP client for the documented Lex Machina API."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx

from .config import Config

type JSONObject = dict[str, Any]
type QueryParams = Mapping[str, Any] | list[tuple[str, Any]]


class LexMachinaAPIError(RuntimeError):
    """Preserve the vendor's HTTP status and error message."""

    def __init__(self, status_code: int, vendor_message: str, response_body: Any = None):
        self.status_code = status_code
        self.vendor_message = vendor_message
        self.response_body = response_body
        super().__init__(f"Lex Machina API error ({status_code}): {vendor_message}")


class LexMachinaClient:
    """Authenticate, retry transient failures, and paginate documented endpoints."""

    def __init__(
        self,
        config: Config,
        *,
        http_client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._http = http_client or httpx.AsyncClient(timeout=config.timeout_seconds)
        self._owns_http_client = http_client is None
        self._sleep = sleep
        self._clock = clock
        self._access_token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    async def __aenter__(self) -> LexMachinaClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the internally owned HTTP transport."""

        if self._owns_http_client:
            await self._http.aclose()

    async def _get_access_token(self) -> str:
        if self._access_token and self._clock() < self._token_expires_at:
            return self._access_token

        async with self._token_lock:
            if self._access_token and self._clock() < self._token_expires_at:
                return self._access_token

            request_kwargs: dict[str, Any] = {}
            credentials = {
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "grant_type": "client_credentials",
            }
            if self.config.token_auth_method == "form":
                request_kwargs["data"] = credentials
            elif self.config.token_auth_method == "basic":
                request_kwargs["auth"] = httpx.BasicAuth(
                    self.config.client_id, self.config.client_secret
                )
                request_kwargs["data"] = {"grant_type": "client_credentials"}
            else:
                raise ValueError("Token authentication must use form or basic, never query.")

            response = await self._send_with_retry("POST", self.config.token_url, **request_kwargs)
            payload = self._response_json(response)
            if not isinstance(payload, dict) or not payload.get("access_token"):
                raise LexMachinaAPIError(
                    response.status_code,
                    "Token response did not include access_token.",
                    payload,
                )

            self._access_token = str(payload["access_token"])
            try:
                lifetime = max(0, int(payload.get("expires_in", 3600)))
            except (TypeError, ValueError):
                lifetime = 3600
            self._token_expires_at = self._clock() + max(0, lifetime - 30)
            return self._access_token

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        params: QueryParams | None = None,
        json: JSONObject | None = None,
    ) -> Any:
        """Send one authenticated API request and decode its JSON response."""

        token = await self._get_access_token()
        response = await self._send_with_retry(
            method,
            f"{self.config.base_url}{path}",
            params=params,
            json=json,
            headers={"Authorization": f"Bearer {token}"},
        )
        return self._response_json(response)

    async def paginate_case_query(
        self,
        path: str,
        query: JSONObject,
        *,
        limit: int,
        page_size_cap: int = 100,
    ) -> JSONObject:
        """Collect case references from page/pageSize JSON-body pagination."""

        self._validate_limit(limit)
        page = 1
        items: list[Any] = []
        pages_fetched = 0
        first_payload: JSONObject | None = None

        while len(items) < limit:
            page_size = min(page_size_cap, limit - len(items))
            body = {key: value for key, value in query.items() if key not in {"page", "pageSize"}}
            body.update({"page": page, "pageSize": page_size})
            payload = self._require_object(await self.request_json("POST", path, json=body))
            if first_payload is None:
                first_payload = dict(payload)
            page_items = payload.get("cases", [])
            if not isinstance(page_items, list):
                raise LexMachinaAPIError(
                    200, "Lex Machina response field 'cases' was not a list.", payload
                )
            pages_fetched += 1
            items.extend(page_items[: limit - len(items)])
            if len(page_items) < page_size:
                break
            page += 1

        result = first_payload or {}
        result["cases"] = items
        result["returnedCount"] = len(items)
        result["pagesFetched"] = pages_fetched
        return result

    async def paginate_search(
        self,
        path: str,
        *,
        query: str,
        result_key: str,
        limit: int,
        page_size_cap: int = 100,
    ) -> JSONObject:
        """Collect entity search results from pageNumber/pageSize pagination."""

        self._validate_limit(limit)
        page_number = 1
        items: list[Any] = []
        pages_fetched = 0
        first_payload: JSONObject | None = None
        next_page: Any = None

        while len(items) < limit:
            page_size = min(page_size_cap, limit - len(items))
            payload = self._require_object(
                await self.request_json(
                    "GET",
                    path,
                    params={"q": query, "pageNumber": page_number, "pageSize": page_size},
                )
            )
            if first_payload is None:
                first_payload = dict(payload)
            page_items = payload.get(result_key, [])
            if not isinstance(page_items, list):
                raise LexMachinaAPIError(
                    200,
                    f"Lex Machina response field {result_key!r} was not a list.",
                    payload,
                )
            pages_fetched += 1
            items.extend(page_items[: limit - len(items)])
            next_page = payload.get("nextPage")
            if next_page is None or not page_items:
                break
            try:
                candidate = int(next_page)
            except (TypeError, ValueError):
                candidate = page_number + 1
            if candidate <= page_number:
                break
            page_number = candidate

        result = first_payload or {}
        result[result_key] = items
        result["nextPage"] = next_page
        result["returnedCount"] = len(items)
        result["pagesFetched"] = pages_fetched
        return result

    async def _send_with_retry(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        response: httpx.Response | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = await self._http.request(method, url, **kwargs)
            except httpx.TransportError:
                if attempt >= self.config.max_retries:
                    raise
                await self._sleep(self.config.backoff_base_seconds * (2**attempt))
                continue

            retryable = response.status_code == 429 or response.status_code >= 500
            if retryable and attempt < self.config.max_retries:
                await self._sleep(self._retry_delay(response, attempt))
                continue
            if response.is_error:
                payload = self._safe_response_json(response)
                raise LexMachinaAPIError(
                    response.status_code,
                    self._vendor_error_message(response, payload),
                    payload,
                )
            return response

        assert response is not None  # pragma: no cover - loop always returns or raises
        return response

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                pass
        return self.config.backoff_base_seconds * (2**attempt)

    @staticmethod
    def _safe_response_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return response.text.strip() or None

    @classmethod
    def _response_json(cls, response: httpx.Response) -> Any:
        payload = cls._safe_response_json(response)
        if payload is None or isinstance(payload, str):
            raise LexMachinaAPIError(
                response.status_code,
                "Lex Machina returned a non-JSON response.",
                payload,
            )
        return payload

    @staticmethod
    def _vendor_error_message(response: httpx.Response, payload: Any) -> str:
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if isinstance(detail, str) and detail:
                return detail
            if isinstance(detail, list):
                messages = [
                    str(item.get("msg"))
                    for item in detail
                    if isinstance(item, dict) and item.get("msg")
                ]
                if messages:
                    return "; ".join(messages)
            for key in ("message", "error_description", "error"):
                value = payload.get(key)
                if value:
                    return str(value)
        if isinstance(payload, str) and payload:
            return payload
        return response.reason_phrase or f"HTTP {response.status_code}"

    @staticmethod
    def _require_object(payload: Any) -> JSONObject:
        if not isinstance(payload, dict):
            raise LexMachinaAPIError(
                200, "Lex Machina returned JSON that was not an object.", payload
            )
        return payload

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
