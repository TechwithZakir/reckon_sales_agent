"""ScrapingBee Google Maps connector (https://www.scrapingbee.com/documentation/google/).

Calls ScrapingBee's Google Search API with ``search_type=maps`` and reads the
business listings from the JSON. The key goes in the Authorization header,
never in the URL.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

import requests

from reckon_sales_agent.connectors.base import ConnectorError, DiscoveryQuery, SourceRecord
from reckon_sales_agent.connectors.maps_common import (
    city_from_address,
    http_error,
    maps_field_policy,
    require_maps_terms,
)
from reckon_sales_agent.discovery.normalize import normalize_domain

ENDPOINT = "https://app.scrapingbee.com/api/v1/google"
RESULT_KEYS = ("maps_results", "map_results", "local_results", "places")
MAX_PAGES = 5


def maps_results(data: dict) -> list[dict]:
    """The listing array, whichever key this response uses."""
    for key in RESULT_KEYS:
        value = data.get(key)
        if isinstance(value, list) and value:
            return [item for item in value if isinstance(item, dict)]
    return []


def own_website(item: dict) -> str | None:
    """A listing's own website; Google ad/redirect links are not the business's site."""
    for key in ("website", "url", "link"):
        value = item.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            domain = normalize_domain(value)
            if domain and "google." not in domain:
                return value
    return None


class ScrapingBeeMapsConnector:
    source_key = "scrapingbee_google_maps"

    def __init__(self, api_key: str | None, *, enabled: bool, terms_ack: bool, retention_days: int = 30,
                 session=None, timeout: int = 90):
        self.api_key = (api_key or "").strip() or None
        self.enabled = enabled
        self.terms_ack = terms_ack
        self.retention_days = retention_days
        self.session = session or requests.Session()
        self.timeout = timeout

    def capabilities(self) -> dict:
        return {"live": True, "network": True, "provider": "ScrapingBee", "search_type": "maps"}

    def default_field_policy(self) -> dict:
        return maps_field_policy(self.retention_days)

    def validate_configuration(self) -> None:
        require_maps_terms(self.terms_ack, self.enabled, self.api_key, "ScrapingBee")

    def discover(self, query: DiscoveryQuery) -> Iterable[SourceRecord]:
        self.validate_configuration()
        returned, seen = 0, set()
        for page in range(1, MAX_PAGES + 1):
            if returned >= query.max_results:
                return
            results = maps_results(self._get({"search": query.query_text, "search_type": "maps",
                                              "country_code": "bd", "language": "en", "page": page}))
            now = datetime.now(timezone.utc).isoformat()
            new = 0
            for item in results:
                title = item.get("title") or item.get("name")
                key = item.get("place_id") or item.get("cid") or item.get("data_id") or f"{title}|{item.get('address')}"
                if not title or key in seen:
                    continue
                seen.add(key)
                new += 1
                returned += 1
                address = item.get("address")
                yield SourceRecord(
                    source_key=self.source_key,
                    external_id=str(key),
                    source_url=None,
                    fields={
                        "business_name": title,
                        "industry": item.get("category") or item.get("type") or query.keyword,
                        "website": own_website(item),
                        "phone": item.get("phone"),
                        "address": address,
                        "city": city_from_address(address, query.location),
                        "rating": item.get("rating") or item.get("review"),
                        "review_count": item.get("reviews") or item.get("review_count"),
                    },
                    retrieved_at=now,
                )
                if returned >= query.max_results:
                    return
            if not new:
                return

    def _get(self, params: dict) -> dict:
        try:
            response = self.session.get(ENDPOINT, params=params, timeout=self.timeout,
                                        headers={"Authorization": f"Bearer {self.api_key}"})
        except requests.RequestException as exc:
            raise ConnectorError(f"ScrapingBee request failed: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise http_error("ScrapingBee", response, self.api_key)
        return response.json() or {}
