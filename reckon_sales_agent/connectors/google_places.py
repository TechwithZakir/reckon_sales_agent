"""Google Places API (New) Text Search connector.

Uses only the official, documented API with the vendor's API key. Google Maps
Platform terms restrict caching and reuse of Places content, so the default
policy keeps the Place ID indefinitely (Google allows storing it) and every
other Places field only for the configured retention window. Prospects keep
their name and website beyond that only once our own website research has
re-established them from the company's site.

Scraping Google Maps web pages is deliberately not implemented.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

import requests

from reckon_sales_agent.connectors.base import (
    ConnectorError,
    ConnectorNotPermitted,
    DiscoveryQuery,
    SourceRecord,
)

ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.websiteUri",
        "places.nationalPhoneNumber",
        "places.internationalPhoneNumber",
        "places.primaryTypeDisplayName",
        "places.addressComponents",
        "nextPageToken",
    ]
)
PAGE_SIZE = 20
ATTRIBUTION = "Google Maps"


class GooglePlacesConnector:
    source_key = "google_places_api"

    def __init__(self, api_key: str | None, *, enabled: bool, terms_reviewed: bool,
                 retention_days: int = 30, session=None, timeout: int = 15):
        self.api_key = api_key
        self.enabled = enabled
        self.terms_reviewed = terms_reviewed
        self.retention_days = max(int(retention_days or 30), 1)
        self.session = session or requests.Session()
        self.timeout = timeout

    def capabilities(self) -> dict:
        return {"live": True, "network": True, "official_api": True, "max_page_size": PAGE_SIZE}

    def default_field_policy(self) -> dict:
        restricted = {"persist": True, "retention_days": self.retention_days, "crm_sync": False,
                      "attribution": ATTRIBUTION}
        return {
            "business_name": restricted,
            "industry": restricted,
            "website": restricted,
            "phone": restricted,
            "address": restricted,
            "city": restricted,
            "country": restricted,
        }

    def validate_configuration(self) -> None:
        if not self.enabled:
            raise ConnectorNotPermitted("The Google Places connector is disabled by the platform vendor.")
        if not self.terms_reviewed:
            raise ConnectorNotPermitted("Google Maps Platform terms have not been marked as reviewed.")
        if not self.api_key:
            raise ConnectorNotPermitted("No Google Places API key is configured.")

    def discover(self, query: DiscoveryQuery) -> Iterable[SourceRecord]:
        self.validate_configuration()
        page_token = None
        returned = 0
        while returned < query.max_results:
            body = {"textQuery": query.query_text, "pageSize": min(PAGE_SIZE, query.max_results - returned),
                    "regionCode": "BD"}
            if page_token:
                body["pageToken"] = page_token
            data = self._post(body)
            for place in data.get("places") or []:
                if returned >= query.max_results:
                    return
                returned += 1
                yield self._record(place, query)
            page_token = data.get("nextPageToken")
            if not page_token:
                return

    def _post(self, body: dict) -> dict:
        try:
            response = self.session.post(
                ENDPOINT,
                json=body,
                headers={"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": FIELD_MASK},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ConnectorError(f"Places request failed: {type(exc).__name__}") from exc
        if response.status_code in (401, 403):
            raise ConnectorError("Places API rejected the key or project.", permanent=True, code="auth")
        if response.status_code == 429:
            raise ConnectorError("Places API rate limit reached.", code="rate_limited")
        if response.status_code >= 400:
            raise ConnectorError(f"Places API error {response.status_code}.",
                                 permanent=response.status_code < 500, code="http_error")
        return response.json()

    def _record(self, place: dict, query: DiscoveryQuery) -> SourceRecord:
        city = ""
        country = ""
        for component in place.get("addressComponents") or []:
            types = component.get("types") or []
            if "locality" in types or ("administrative_area_level_2" in types and not city):
                city = component.get("longText") or city
            if "country" in types:
                country = component.get("longText") or ""
        place_id = place.get("id")
        return SourceRecord(
            source_key=self.source_key,
            external_id=place_id,
            source_url=f"https://www.google.com/maps/place/?q=place_id:{place_id}" if place_id else None,
            fields={
                "business_name": (place.get("displayName") or {}).get("text"),
                "industry": (place.get("primaryTypeDisplayName") or {}).get("text") or query.keyword,
                "website": place.get("websiteUri"),
                "phone": place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber"),
                "address": place.get("formattedAddress"),
                "city": city or query.location,
                "country": country,
            },
            retrieved_at=datetime.now(timezone.utc).isoformat(),
        )
