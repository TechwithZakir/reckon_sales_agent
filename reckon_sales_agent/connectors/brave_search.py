"""Brave Search API lead source (https://api.search.brave.com/res/v1/web/search).

Brave's official web search API with its own index: no scraping and no
CAPTCHAs, billed per request. It searches "keyword in location" and, like
the Google Search sources, keeps only results that are a business's own
website. The key goes in the ``X-Subscription-Token`` header, never the URL.
"""

from __future__ import annotations

import re

from reckon_sales_agent.connectors.base import ConnectorNotPermitted
from reckon_sales_agent.connectors.search_api import _SearchAPIConnector
from reckon_sales_agent.connectors.search_common import search_field_policy

ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
PAGE_SIZE = 20  # Brave's maximum per request
TAGS = re.compile(r"<[^>]+>")


class BraveSearchConnector(_SearchAPIConnector):
    """``offset`` is the page number (0-based); results are in ``web.results``."""

    source_key = "brave_web_search"
    provider = "Brave Search"
    page_size = PAGE_SIZE

    def __init__(self, api_key: str | None, *, enabled: bool, retention_days: int = 30, country: str = "",
                 language: str = "en", session=None, timeout: int = 30):
        # Brave is an official API, so there is no Google-style responsibility tick to accept.
        super().__init__(api_key, enabled=enabled, terms_ack=True, retention_days=retention_days,
                         country=country, language=language, session=session, timeout=timeout)
        self.country = (country or "").strip().upper()[:2]  # empty: Brave's default (all countries)

    def default_field_policy(self) -> dict:
        return search_field_policy(self.retention_days, attribution="Brave Search")

    def validate_configuration(self) -> None:
        if not self.enabled:
            raise ConnectorNotPermitted("Brave Search is disabled by the platform vendor.")
        if not self.api_key:
            raise ConnectorNotPermitted("No Brave Search API key is configured.")

    def _page(self, text: str, page: int) -> list[dict]:
        params = {"q": text[:400], "count": PAGE_SIZE, "offset": page, "result_filter": "web",
                  "search_lang": self.language.split("-")[0]}
        if self.country:
            params["country"] = self.country
        data = self._get(ENDPOINT, params, headers={"Accept": "application/json",
                                                    "X-Subscription-Token": self.api_key})
        results = ((data.get("web") or {}).get("results")) or []
        return [{"title": TAGS.sub("", r.get("title") or ""), "url": r.get("url"),
                 "description": TAGS.sub("", r.get("description") or "")}
                for r in results if isinstance(r, dict)]
