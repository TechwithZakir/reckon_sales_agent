"""Google Search lead sources through SERP API providers (Scrapingdog, ScrapingBee, SerpAPI).

Each provider runs "keyword in location" on Google and returns the organic
results as JSON. Results become leads only when they point at a business's
own website (see ``search_common``); research then reads that website.
Keys are sent the way each provider documents and are never logged.
"""

from __future__ import annotations

from collections.abc import Iterable

import requests

from reckon_sales_agent.connectors.base import ConnectorError, DiscoveryQuery, SourceRecord
from reckon_sales_agent.connectors.maps_common import http_error
from reckon_sales_agent.connectors.search_common import (
    COUNTRY,
    records_from_results,
    require_search_terms,
    search_field_policy,
)

MAX_PAGES = 5  # ~50 organic results per search; directories and social sites are filtered out


class _SearchAPIConnector:
    source_key = ""
    provider = ""

    def __init__(self, api_key: str | None, *, enabled: bool, terms_ack: bool, retention_days: int = 30,
                 country: str = COUNTRY, language: str = "en", session=None, timeout: int = 60):
        self.api_key = (api_key or "").strip() or None
        self.enabled = enabled
        self.terms_ack = terms_ack
        self.retention_days = retention_days
        self.country = (country or COUNTRY).lower()[:2]
        self.language = (language or "en")[:8]
        self.session = session or requests.Session()
        self.timeout = timeout

    def capabilities(self) -> dict:
        return {"live": True, "network": True, "provider": self.provider, "result_type": "websites"}

    def default_field_policy(self) -> dict:
        return search_field_policy(self.retention_days)

    def validate_configuration(self) -> None:
        require_search_terms(self.terms_ack, self.enabled, self.api_key, f"{self.provider} (Google Search)")

    def discover(self, query: DiscoveryQuery) -> Iterable[SourceRecord]:
        self.validate_configuration()
        seen: set[str] = set()
        returned = 0
        for page in range(MAX_PAGES):
            results = self._page(query.query_text, page)
            for record in records_from_results(results, query, self.source_key, seen, query.max_results - returned):
                returned += 1
                yield record
            if returned >= query.max_results or not results:
                return

    def _page(self, text: str, page: int) -> list[dict]:
        raise NotImplementedError

    def _get(self, url: str, params: dict, headers: dict | None = None) -> dict:
        try:
            response = self.session.get(url, params=params, headers=headers or {}, timeout=self.timeout)
        except requests.RequestException as exc:
            raise ConnectorError(f"{self.provider} request failed: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise http_error(self.provider, response, self.api_key)
        try:
            return response.json() or {}
        except ValueError as exc:
            raise ConnectorError(f"{self.provider} returned a response that is not JSON.") from exc


class ScrapingdogSearchConnector(_SearchAPIConnector):
    """https://api.scrapingdog.com/google (page is 0-based)."""

    source_key = "scrapingdog_google_search"
    provider = "Scrapingdog"
    endpoint = "https://api.scrapingdog.com/google"

    def _page(self, text: str, page: int) -> list[dict]:
        data = self._get(self.endpoint, {"api_key": self.api_key, "query": text, "country": self.country,
                                         "page": page})
        return data.get("organic_results") or data.get("organic_data") or []


class ScrapingBeeSearchConnector(_SearchAPIConnector):
    """https://app.scrapingbee.com/api/v1/google (page is 1-based; key in the Authorization header)."""

    source_key = "scrapingbee_google_search"
    provider = "ScrapingBee"
    endpoint = "https://app.scrapingbee.com/api/v1/google"

    def _page(self, text: str, page: int) -> list[dict]:
        data = self._get(self.endpoint, {"search": text, "country_code": self.country, "language": self.language,
                                         "page": page + 1}, headers={"Authorization": f"Bearer {self.api_key}"})
        return data.get("organic_results") or []


class SerpAPISearchConnector(_SearchAPIConnector):
    """https://serpapi.com/search.json?engine=google (``start`` is the result offset)."""

    source_key = "serpapi_google_search"
    provider = "SerpAPI"
    endpoint = "https://serpapi.com/search.json"

    def _page(self, text: str, page: int) -> list[dict]:
        data = self._get(self.endpoint, {"engine": "google", "q": text, "api_key": self.api_key,
                                         "gl": self.country, "hl": self.language, "start": page * 10})
        if data.get("error") and "hasn't returned any results" not in str(data["error"]):
            raise ConnectorError(f"SerpAPI: {str(data['error'])[:200]}", code="provider_error")
        return data.get("organic_results") or []
