"""Scrapingdog Google Maps connector (https://api.scrapingdog.com/google_maps).

Scrapingdog runs the Maps search and returns JSON (``search_results``). It
needs map coordinates (``ll``); known Bangladesh cities map to their centre,
anything else falls back to a country-wide view.
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

ENDPOINT = "https://api.scrapingdog.com/google_maps"
PAGE_SIZE = 20
MAX_PAGES = 6
BD_CITIES = {
    "dhaka": (23.8103, 90.4125), "chattogram": (22.3569, 91.7832), "chittagong": (22.3569, 91.7832),
    "khulna": (22.8456, 89.5403), "rajshahi": (24.3745, 88.6042), "sylhet": (24.8949, 91.8687),
    "barishal": (22.7010, 90.3535), "barisal": (22.7010, 90.3535), "rangpur": (25.7439, 89.2752),
    "mymensingh": (24.7471, 90.4203), "gazipur": (23.9999, 90.4203), "narayanganj": (23.6238, 90.5000),
    "cumilla": (23.4607, 91.1809), "comilla": (23.4607, 91.1809), "bogura": (24.8465, 89.3773),
    "cox's bazar": (21.4272, 92.0058), "jessore": (23.1664, 89.2081), "jashore": (23.1664, 89.2081),
}
COUNTRY_VIEW = "@23.6850,90.3563,7z"


def coordinates_for(location: str) -> str:
    for part in [p.strip().lower() for p in (location or "").split(",")][::-1]:
        if part in BD_CITIES:
            lat, lng = BD_CITIES[part]
            return f"@{lat},{lng},12z"
    return COUNTRY_VIEW


class ScrapingdogMapsConnector:
    source_key = "scrapingdog_google_maps"

    def __init__(self, api_key: str | None, *, enabled: bool, terms_ack: bool, retention_days: int = 30,
                 session=None, timeout: int = 60):
        self.api_key = api_key
        self.enabled = enabled
        self.terms_ack = terms_ack
        self.retention_days = retention_days
        self.session = session or requests.Session()
        self.timeout = timeout

    def capabilities(self) -> dict:
        return {"live": True, "network": True, "provider": "Scrapingdog", "page_size": PAGE_SIZE}

    def default_field_policy(self) -> dict:
        return maps_field_policy(self.retention_days)

    def validate_configuration(self) -> None:
        require_maps_terms(self.terms_ack, self.enabled, self.api_key, "Scrapingdog")

    def discover(self, query: DiscoveryQuery) -> Iterable[SourceRecord]:
        self.validate_configuration()
        returned = 0
        ll = coordinates_for(query.location)
        search = query.keyword if ll != COUNTRY_VIEW else query.query_text
        for page in range(MAX_PAGES):
            if returned >= query.max_results:
                return
            results = self._get({"api_key": self.api_key, "query": search, "ll": ll, "language": "en",
                                 "page": page}).get("search_results") or []
            now = datetime.now(timezone.utc).isoformat()
            for place in results:
                if returned >= query.max_results:
                    return
                returned += 1
                address = place.get("address")
                yield SourceRecord(
                    source_key=self.source_key,
                    external_id=place.get("data_id") or place.get("place_id"),
                    source_url=place.get("link") or place.get("url"),
                    fields={
                        "business_name": place.get("title"),
                        "industry": place.get("type") or query.keyword,
                        "website": place.get("website"),
                        "phone": place.get("phone"),
                        "address": address,
                        "city": city_from_address(address, query.location),
                        "rating": place.get("rating"),
                        "review_count": place.get("reviews"),
                    },
                    retrieved_at=now,
                )
            if len(results) < PAGE_SIZE:
                return

    def _get(self, params: dict) -> dict:
        try:
            response = self.session.get(ENDPOINT, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise ConnectorError(f"Scrapingdog request failed: {type(exc).__name__}") from exc
        if response.status_code in (401, 403):
            raise ConnectorError("Scrapingdog rejected the key or has no credits.", permanent=True, code="auth")
        if response.status_code == 429:
            raise ConnectorError("Scrapingdog rate limit reached.", code="rate_limited")
        if response.status_code >= 400:
            raise ConnectorError(f"Scrapingdog error {response.status_code}.", permanent=response.status_code < 500,
                                 code="http_error")
        return response.json() or {}
