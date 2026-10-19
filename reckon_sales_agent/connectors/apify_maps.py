"""Apify Google Maps scraper connector (actor ``compass~crawler-google-places`` by default).

Runs the actor synchronously through Apify's API and reads its dataset items.
The token travels in the Authorization header, never in the URL.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from urllib.parse import quote

import requests

from reckon_sales_agent.connectors.base import ConnectorError, DiscoveryQuery, SourceRecord
from reckon_sales_agent.connectors.maps_common import (
    city_from_address,
    maps_field_policy,
    require_maps_terms,
)

API = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
RUN_TIMEOUT = 300


class ApifyMapsConnector:
    source_key = "apify_google_maps"

    def __init__(self, token: str | None, *, enabled: bool, terms_ack: bool, actor: str | None = None,
                 retention_days: int = 30, session=None):
        self.token = token
        self.enabled = enabled
        self.terms_ack = terms_ack
        self.actor = (actor or "compass~crawler-google-places").strip()
        self.retention_days = retention_days
        self.session = session or requests.Session()

    def capabilities(self) -> dict:
        return {"live": True, "network": True, "provider": "Apify", "actor": self.actor}

    def default_field_policy(self) -> dict:
        return maps_field_policy(self.retention_days)

    def validate_configuration(self) -> None:
        require_maps_terms(self.terms_ack, self.enabled, self.token, "Apify")
        if "/" in self.actor.replace("~", "") or not self.actor:
            raise ConnectorError("Apify actor must look like 'username~actor-name'.", permanent=True, code="config")

    def discover(self, query: DiscoveryQuery) -> Iterable[SourceRecord]:
        self.validate_configuration()
        body = {
            "searchStringsArray": [query.keyword],
            "locationQuery": f"{query.location}, Bangladesh" if query.location else "Bangladesh",
            "maxCrawledPlacesPerSearch": int(query.max_results),
            "language": "en",
            "skipClosedPlaces": True,
            "scrapePlaceDetailPage": False,
        }
        try:
            response = self.session.post(
                API.format(actor=quote(self.actor, safe="~")),
                json=body,
                headers={"Authorization": f"Bearer {self.token}"},
                params={"timeout": RUN_TIMEOUT, "format": "json", "clean": "true"},
                timeout=RUN_TIMEOUT + 30,
            )
        except requests.RequestException as exc:
            raise ConnectorError(f"Apify request failed: {type(exc).__name__}") from exc
        if response.status_code in (401, 403):
            raise ConnectorError("Apify rejected the token.", permanent=True, code="auth")
        if response.status_code == 402:
            raise ConnectorError("Apify account has no credit left.", permanent=True, code="billing")
        if response.status_code == 408:
            raise ConnectorError("The Apify run timed out; try fewer results per search.", code="timeout")
        if response.status_code >= 400:
            raise ConnectorError(f"Apify error {response.status_code}.", permanent=response.status_code < 500,
                                 code="http_error")
        now = datetime.now(timezone.utc).isoformat()
        for item in (response.json() or [])[: query.max_results]:
            if not isinstance(item, dict) or not item.get("title"):
                continue
            address = item.get("address")
            yield SourceRecord(
                source_key=self.source_key,
                external_id=item.get("placeId") or item.get("cid") or item.get("url"),
                source_url=item.get("url"),
                fields={
                    "business_name": item.get("title"),
                    "industry": item.get("categoryName") or query.keyword,
                    "website": item.get("website"),
                    "phone": item.get("phoneUnformatted") or item.get("phone"),
                    "address": address,
                    "city": item.get("city") or city_from_address(address, query.location),
                    "country": "Bangladesh" if (item.get("countryCode") or "").upper() == "BD" else None,
                    "rating": item.get("totalScore"),
                    "review_count": item.get("reviewsCount"),
                },
                retrieved_at=now,
            )
