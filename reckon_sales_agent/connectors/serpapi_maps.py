"""SerpAPI Google Maps connector (https://serpapi.com/google-maps-api).

SerpAPI runs the Google Maps search and returns structured JSON; we never
touch Google directly. Results are paged 20 at a time (``start``).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

import requests

from reckon_sales_agent.connectors.base import ConnectorError, DiscoveryQuery, SourceRecord
from reckon_sales_agent.connectors.maps_common import (
    city_from_address,
    maps_field_policy,
    require_maps_terms,
)

ENDPOINT = "https://serpapi.com/search.json"
PAGE_SIZE = 20
MAX_START = 100


class SerpAPIMapsConnector:
    source_key = "serpapi_google_maps"

    def __init__(self, api_key: str | None, *, enabled: bool, terms_ack: bool, retention_days: int = 30,
                 session=None, timeout: int = 30):
        self.api_key = api_key
        self.enabled = enabled
        self.terms_ack = terms_ack
        self.retention_days = retention_days
        self.session = session or requests.Session()
        self.timeout = timeout

    def capabilities(self) -> dict:
        return {"live": True, "network": True, "provider": "SerpAPI", "page_size": PAGE_SIZE}

    def default_field_policy(self) -> dict:
        return maps_field_policy(self.retention_days)

    def validate_configuration(self) -> None:
        require_maps_terms(self.terms_ack, self.enabled, self.api_key, "SerpAPI")

    def discover(self, query: DiscoveryQuery) -> Iterable[SourceRecord]:
        self.validate_configuration()
        returned, start = 0, 0
        while returned < query.max_results and start <= MAX_START:
            data = self._get({"engine": "google_maps", "type": "search", "q": query.query_text, "hl": "en",
                              "gl": "bd", "start": start, "api_key": self.api_key})
            results = data.get("local_results") or []
            if isinstance(results, dict):  # a single place match
                results = [results]
            for place in results:
                if returned >= query.max_results:
                    return
                returned += 1
                yield self._record(place, query)
            if len(results) < PAGE_SIZE:
                return
            start += PAGE_SIZE

    def _get(self, params: dict) -> dict:
        try:
            response = self.session.get(ENDPOINT, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise ConnectorError(f"SerpAPI request failed: {type(exc).__name__}") from exc
        if response.status_code in (401, 403):
            raise ConnectorError("SerpAPI rejected the key.", permanent=True, code="auth")
        if response.status_code == 429:
            raise ConnectorError("SerpAPI rate limit or plan quota reached.", code="rate_limited")
        if response.status_code >= 400:
            raise ConnectorError(f"SerpAPI error {response.status_code}.", permanent=response.status_code < 500,
                                 code="http_error")
        data = response.json()
        if data.get("error") and "hasn't returned any results" not in str(data["error"]):
            raise ConnectorError(f"SerpAPI: {str(data['error'])[:200]}", permanent=True, code="provider_error")
        return data

    def _record(self, place: dict, query: DiscoveryQuery) -> SourceRecord:
        place_id = place.get("place_id") or place.get("data_id")
        address = place.get("address")
        return SourceRecord(
            source_key=self.source_key,
            external_id=place_id,
            source_url=f"https://www.google.com/maps/place/?q=place_id:{place_id}" if place.get("place_id") else None,
            fields={
                "business_name": place.get("title"),
                "industry": place.get("type") or (place.get("types") or [query.keyword])[0],
                "website": place.get("website"),
                "phone": place.get("phone"),
                "address": address,
                "city": city_from_address(address, query.location),
                "country": "Bangladesh" if "bangladesh" in (address or "").lower() else None,
                "rating": place.get("rating"),
                "review_count": place.get("reviews"),
            },
            retrieved_at=datetime.now(timezone.utc).isoformat(),
        )
