"""Brave Search API lead sources (https://api-dashboard.search.brave.com/documentation).

Brave's official APIs on its own index: no scraping, no CAPTCHAs, billed per
request. The key goes in the ``X-Subscription-Token`` header, never the URL.

* ``brave_web_search``: Web Search (``/res/v1/web/search``). Results that are
  a business's own website become leads (same filtering as Google Search).
* ``brave_place_search``: Place Search (``/res/v1/local/place_search``).
  Local businesses with name, website, phone, email, address, rating and
  categories, like a Maps listing, up to 100 in one request.
* ``brave_llm_context``: LLM Context (``/res/v1/llm/context``). Search results
  with text extracted from each page, so phones and emails come from the page
  itself; local business entries (``poi``/``map``) become leads too.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from reckon_sales_agent.connectors.base import ConnectorNotPermitted, DiscoveryQuery, SourceRecord
from reckon_sales_agent.connectors.search_api import _SearchAPIConnector
from reckon_sales_agent.connectors.search_common import (
    business_name,
    email_from,
    home_page,
    is_business_site,
    is_generic_name,
    is_listing_page,
    name_matches_domain,
    phone_from,
    search_field_policy,
    site_key,
    tidy_name,
)
from reckon_sales_agent.discovery.normalize import normalize_domain, normalize_space

API = "https://api.search.brave.com/res/v1"
WEB_PAGE_SIZE = 20  # Brave's maximum per Web Search request
WEB_MAX_OFFSET = 9
PLACE_MAX = 100
TAGS = re.compile(r"<[^>]+>")
# Place Search wants "city country" with no commas; these are the countries we expect to sell in.
# Country codes Brave's ``country`` parameter accepts (an enum; anything else is HTTP 422). Bangladesh is not
# one of them, so for BD the country travels in the search text and the Places location string instead.
BRAVE_COUNTRIES = frozenset({
    "AR", "AU", "AT", "BE", "BR", "CA", "CL", "DK", "FI", "FR", "DE", "HK", "IN", "ID", "IT", "JP", "KR", "MY",
    "MX", "NL", "NZ", "NO", "CN", "PL", "PT", "PH", "RU", "SA", "ZA", "ES", "SE", "CH", "TW", "TR", "GB", "US",
})
COUNTRY_NAMES = {
    "BD": "bangladesh", "IN": "india", "PK": "pakistan", "NP": "nepal", "LK": "sri lanka", "AE": "united arab emirates",
    "SA": "saudi arabia", "QA": "qatar", "MY": "malaysia", "SG": "singapore", "GB": "united kingdom",
    "US": "united states", "CA": "canada", "AU": "australia",
}


def clean(text) -> str:
    return normalize_space(TAGS.sub("", str(text or "")))


class _BraveConnector(_SearchAPIConnector):
    provider = "Brave Search"
    attribution = "Brave Search"

    def __init__(self, api_key: str | None, *, enabled: bool, retention_days: int = 30, country: str = "",
                 language: str = "en", session=None, timeout: int = 30):
        # Brave is an official API, so there is no Google-style responsibility tick to accept.
        super().__init__(api_key, enabled=enabled, terms_ack=True, retention_days=retention_days,
                         country=country, language=language, session=session, timeout=timeout)
        self.country = (country or "").strip().upper()[:2]  # where the leads are (also unsupported codes)
        self.language = (language or "en").split("-")[0][:8]

    @property
    def brave_country(self) -> str:
        """The ``country`` parameter to send: only codes Brave accepts, else nothing."""
        return self.country if self.country in BRAVE_COUNTRIES else ""

    def default_field_policy(self) -> dict:
        return search_field_policy(self.retention_days, attribution=self.attribution)

    def validate_configuration(self) -> None:
        if not self.enabled:
            raise ConnectorNotPermitted(f"{self.provider} is disabled by the platform vendor.")
        if not self.api_key:
            raise ConnectorNotPermitted("No Brave Search API key is configured.")

    def _brave(self, path: str, params: dict, headers: dict | None = None) -> dict:
        return self._get(f"{API}{path}", params, headers={"Accept": "application/json",
                                                           "X-Subscription-Token": self.api_key, **(headers or {})})


class BraveSearchConnector(_BraveConnector):
    """Web Search: ``offset`` is the page number (0-9); results are in ``web.results``."""

    source_key = "brave_web_search"
    page_size = WEB_PAGE_SIZE

    def discover(self, query: DiscoveryQuery):
        self._more = True
        yield from super().discover(query)

    def search(self, text: str, count: int = 10) -> list[dict]:
        self._more = True
        return super().search(text, count)

    def _page(self, text: str, page: int) -> list[dict]:
        if not self._more or page > WEB_MAX_OFFSET:
            return []  # Brave said there are no more results: no paid request
        params = {"q": text[:400], "count": WEB_PAGE_SIZE, "offset": page, "search_lang": self.language}
        if self.country:
            params["country"] = self.brave_country or "ALL"  # unsupported (e.g. BD): all countries
        data = self._brave("/web/search", params)
        self._more = bool((data.get("query") or {}).get("more_results_available"))
        results = ((data.get("web") or {}).get("results")) or []
        return [{"title": clean(r.get("title")), "url": r.get("url"),
                 "description": " ".join([clean(r.get("description"))]
                                         + [clean(s) for s in r.get("extra_snippets") or []])}
                for r in results if isinstance(r, dict)]


class BravePlaceSearchConnector(_BraveConnector):
    """Place Search: local businesses for "keyword" around "location", one request of up to 100."""

    source_key = "brave_place_search"
    provider = "Brave Place Search"
    attribution = "Brave Places"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.country = self.country or "BD"

    def place_location(self, location: str) -> str:
        """'Mirpur, Dhaka' -> 'mirpur dhaka bangladesh' (Brave wants no commas)."""
        words = normalize_space((location or "").replace(",", " ")).lower()
        if any(name in words for name in COUNTRY_NAMES.values()):
            return words  # the location already names its country
        country = COUNTRY_NAMES.get(self.country, "")
        return normalize_space(f"{words} {country}") if country else words

    def discover(self, query: DiscoveryQuery):
        self.validate_configuration()
        params = {"q": (query.keyword or query.query_text)[:400], "count": max(1, min(query.max_results, PLACE_MAX)),
                  "search_lang": self.language, "units": "metric"}
        if self.brave_country:
            params["country"] = self.brave_country
        if query.location:
            params["location"] = self.place_location(query.location)
        data = self._brave("/local/place_search", params)
        now = datetime.now(timezone.utc).isoformat()
        seen: set[str] = set()
        returned = 0
        for place in data.get("results") or []:
            if returned >= query.max_results:
                return
            record = self._record(place, query, now)
            if record and record.external_id not in seen:
                seen.add(record.external_id)
                returned += 1
                yield record

    def _record(self, place: dict, query: DiscoveryQuery, now: str) -> SourceRecord | None:
        if not isinstance(place, dict):
            return None
        name = tidy_name(clean(place.get("title")), query.keyword)[:140]
        if not name:
            return None
        address = place.get("postal_address") or {}
        contact = place.get("contact") or {}
        rating = place.get("rating") or {}
        coordinates = place.get("coordinates") or []
        url = place.get("url") or ""
        website = url if url.startswith(("http://", "https://")) and is_business_site(url) else None
        categories = [clean(c) for c in place.get("categories") or [] if clean(c)]
        # Brave's place ids expire after ~8 hours, so the stable key is name + position.
        key = f"{name.lower()}@{','.join(f'{float(c):.4f}' for c in coordinates[:2])}" if len(coordinates) >= 2 \
            else f"{name.lower()}@{clean(address.get('displayAddress')).lower()}"
        return SourceRecord(
            source_key=self.source_key,
            external_id=key[:140],
            source_url=place.get("provider_url") or url or None,
            fields={
                "business_name": name,
                "website": website,
                "phone": clean(contact.get("telephone")) or None,
                "email": clean(contact.get("email")).lower() or None,
                "address": clean(address.get("displayAddress") or address.get("streetAddress")) or None,
                "city": clean(address.get("addressLocality")) or (query.location or "").split(",")[-1].strip() or None,
                "country": clean(address.get("country")) or None,
                "industry": categories[0] if categories else query.keyword or None,
                "rating": rating.get("ratingValue"),
                "review_count": rating.get("reviewCount"),
            },
            retrieved_at=now,
        )


class BraveLLMContextConnector(_BraveConnector):
    """LLM Context: grounding results with page text; one request per search (up to 50 sources)."""

    source_key = "brave_llm_context"
    provider = "Brave LLM Context"
    attribution = "Brave Search"

    def _grounding(self, text: str, location: str, count: int, tokens_per_url: int = 1024) -> list[dict]:
        """Local business entries (poi, map) first, then the generic results, each with page snippets."""
        self.validate_configuration()
        params = {"q": text[:600], "count": max(1, min(count, 50)), "search_lang": self.language,
                  "enable_local": "true", "maximum_number_of_tokens_per_url": tokens_per_url,
                  "maximum_number_of_tokens": 16384}
        if self.brave_country:
            params["country"] = self.brave_country
        headers = {}
        city = (location or "").split(",")[-1].strip()
        if city:
            headers["X-Loc-City"] = city
        if self.brave_country:
            headers["X-Loc-Country"] = self.brave_country
        grounding = (self._brave("/llm/context", params, headers) or {}).get("grounding") or {}
        poi = grounding.get("poi")
        return ([poi] if isinstance(poi, dict) else []) + list(grounding.get("map") or []) \
            + list(grounding.get("generic") or [])

    def context(self, text: str, location: str = "", count: int = 10) -> list[dict]:
        """[{url, title, text}] with page text (market research); 2048 tokens per page for richer evidence."""
        rows = []
        for entry in self._grounding(text, location, count, tokens_per_url=2048):
            url = (entry or {}).get("url") or ""
            if url.startswith(("http://", "https://")):
                rows.append({"url": url, "title": clean(entry.get("title") or entry.get("name")),
                             "text": " ".join(clean(s) for s in entry.get("snippets") or [] if s)})
        return rows[:count]

    def discover(self, query: DiscoveryQuery):
        entries = self._grounding(query.query_text, query.location, query.max_results * 2)
        now = datetime.now(timezone.utc).isoformat()
        seen: set[str] = set()
        returned = 0
        for entry in entries:
            if returned >= query.max_results:
                return
            record = self._record(entry, query, now)
            if record and record.external_id not in seen:
                seen.add(record.external_id)
                returned += 1
                yield record

    def _record(self, entry: dict, query: DiscoveryQuery, now: str) -> SourceRecord | None:
        if not isinstance(entry, dict):
            return None
        url = entry.get("url") or ""
        if not url.startswith(("http://", "https://")) or not is_business_site(url):
            return None
        title = clean(entry.get("title"))
        if not entry.get("name") and is_listing_page(title, url):
            return None  # a list or directory page, not one business (local poi/map entries are businesses)
        text = " ".join(clean(s) for s in entry.get("snippets") or [] if s)
        local = bool(clean(entry.get("name")))  # poi/map entries name a real local business
        name = tidy_name(clean(entry.get("name")), query.keyword) if entry.get("name") else ""
        if not name or is_generic_name(name, query.keyword):
            name = business_name(title, url, query.keyword)
        if not name:
            return None
        own_site = name_matches_domain(name, url, query.keyword)
        if not own_site and not local:
            return None  # a page about the business on someone else's site
        return SourceRecord(
            source_key=self.source_key,
            external_id=site_key(url) if own_site else f"{name.lower()}@{normalize_domain(url)}"[:140],
            source_url=url,
            fields={
                "business_name": name[:140],
                "website": home_page(url) if own_site else None,
                "phone": phone_from(text),
                "email": email_from(text),
                "industry": query.keyword or None,
                "city": (query.location or "").split(",")[-1].strip() or None,
            },
            retrieved_at=now,
        )
