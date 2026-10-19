"""EXPERIMENTAL google_maps_browser_experimental: headless Chromium (Playwright) on Google Maps.

Not an API, not supported by Google, and restricted by Google's Terms of
Service. Disabled unless the platform vendor enables it and accepts
responsibility. Deliberately simple and honest:

* the browser's own user agent, no proxies, no stealth plugins, no
  fingerprint changes, no CAPTCHA solving, no login;
* a consent wall, CAPTCHA or "unusual traffic" page stops the run;
* a delay between place pages and a hard cap on places per search.

Google changes the page often, so selectors live in one place below and a
change shows up as empty results, not wrong data. Requires
``pip install playwright`` and ``playwright install --with-deps chromium``
on the bench server.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote, urlsplit

from reckon_sales_agent.connectors.base import (
    ConnectorError,
    ConnectorNotPermitted,
    DiscoveryQuery,
    SourceRecord,
)
from reckon_sales_agent.connectors.maps_common import (
    city_from_address,
    looks_blocked,
    maps_field_policy,
    require_maps_terms,
)
from reckon_sales_agent.discovery.normalize import normalize_space

HARD_CAP = 100
SEARCH_URL = "https://www.google.com/maps/search/{query}?hl={language}"
FEED = 'div[role="feed"]'
PLACE_LINKS = 'a[href*="/maps/place/"]'
EXTRACT_JS = """() => {
  const q = (s) => document.querySelector(s);
  const attr = (s, a) => { const el = q(s); return el ? el.getAttribute(a) : null; };
  return {
    name: q('h1') ? q('h1').innerText : null,
    category: q('button[jsaction*="category"]') ? q('button[jsaction*="category"]').innerText : null,
    address: attr('[data-item-id="address"]', 'aria-label'),
    website: attr('a[data-item-id="authority"]', 'href'),
    phone: attr('[data-item-id^="phone:tel:"]', 'aria-label'),
  };
}"""


def place_id_from_url(url: str) -> str | None:
    """Stable Maps feature id from a place URL ('!1s0x...:0x...'), else the place path."""
    match = re.search(r"!1s(0x[0-9a-f]+:0x[0-9a-f]+)", url or "", flags=re.I)
    if match:
        return match.group(1)
    match = re.search(r"/maps/place/([^/@?]+)", url or "")
    return match.group(1) if match else None


def clean_label(value: str | None) -> str:
    """'Address: Road 5, Dhaka' / 'Phone: 01711-000000 ' -> the value only."""
    text = normalize_space(value)
    return re.sub(r"^(address|phone|website|ঠিকানা|ফোন)\s*:\s*", "", text, flags=re.I).strip()


def unwrap_website(href: str | None) -> str | None:
    """Google sometimes wraps outbound links as /url?q=<target>."""
    if not href:
        return None
    parts = urlsplit(href)
    if parts.path == "/url":
        target = (parse_qs(parts.query).get("q") or [None])[0]
        return target
    return href if href.startswith(("http://", "https://")) else None


def parse_place(raw: dict, url: str, query: DiscoveryQuery) -> dict | None:
    name = normalize_space(raw.get("name"))
    if not name:
        return None
    address = clean_label(raw.get("address")) or None
    return {
        "business_name": name[:140],
        "industry": normalize_space(raw.get("category")) or query.keyword,
        "website": unwrap_website(raw.get("website")),
        "phone": clean_label(raw.get("phone")) or None,
        "address": address,
        "city": city_from_address(address, query.location),
        "country": "Bangladesh" if address and "bangladesh" in address.lower() else None,
    }


class GoogleMapsBrowserConnector:
    source_key = "google_maps_browser_experimental"

    def __init__(self, *, enabled: bool, terms_ack: bool, max_results: int = 40, delay: float = 3.0,
                 language: str = "en", retention_days: int = 30, playwright_factory=None, sleep=time.sleep):
        self.enabled = enabled
        self.terms_ack = terms_ack
        self.max_results = max(1, min(int(max_results or 1), HARD_CAP))
        self.delay = max(float(delay or 0), 2.0)
        self.language = re.sub(r"[^a-zA-Z-]", "", language or "en")[:8] or "en"
        self.retention_days = retention_days
        self.playwright_factory = playwright_factory
        self.sleep = sleep

    def capabilities(self) -> dict:
        return {"live": True, "network": True, "experimental": True, "official_api": False,
                "max_results": self.max_results}

    def default_field_policy(self) -> dict:
        return maps_field_policy(self.retention_days)

    def validate_configuration(self) -> None:
        require_maps_terms(self.terms_ack, self.enabled, None, "google_maps_browser_experimental",
                           needs_credential=False)
        if self.playwright_factory is None:
            try:
                import playwright.sync_api  # noqa: F401
            except ImportError as exc:
                raise ConnectorNotPermitted(
                    "Playwright is not installed on the server (pip install playwright; "
                    "playwright install --with-deps chromium).") from exc

    def discover(self, query: DiscoveryQuery) -> Iterable[SourceRecord]:
        self.validate_configuration()
        limit = min(query.max_results, self.max_results)
        factory = self.playwright_factory
        if factory is None:
            from playwright.sync_api import sync_playwright

            factory = sync_playwright
        with factory() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_context(locale=self.language).new_page()
                page.set_default_timeout(20_000)
                page.goto(SEARCH_URL.format(query=quote(query.query_text), language=self.language),
                          wait_until="domcontentloaded")
                self._check(page)
                links = self._collect_links(page, limit)
                if not links and "/maps/place/" in page.url:
                    links = [page.url]  # the search opened a single place directly
                now = datetime.now(timezone.utc).isoformat()
                for index, link in enumerate(links[:limit]):
                    if index:
                        self.sleep(self.delay)
                    page.goto(link, wait_until="domcontentloaded")
                    self._check(page)
                    try:
                        page.wait_for_selector("h1", timeout=10_000)
                    except Exception:
                        continue
                    fields = parse_place(page.evaluate(EXTRACT_JS) or {}, page.url, query)
                    if fields:
                        yield SourceRecord(self.source_key, place_id_from_url(page.url) or link, page.url,
                                           fields, now, warnings=["experimental browser source"])
            finally:
                browser.close()

    def _check(self, page) -> None:
        try:
            text = page.inner_text("body")[:5000]
        except Exception:
            text = ""
        if looks_blocked(page.url, text):
            raise ConnectorError("Google showed a consent, CAPTCHA or unusual-traffic page; stopping.",
                                 permanent=True, code="blocked")

    def _collect_links(self, page, limit: int) -> list[str]:
        try:
            page.wait_for_selector(FEED, timeout=15_000)
        except Exception:
            return []
        links: list[str] = []
        stale = 0
        while len(links) < limit and stale < 3:
            found = page.eval_on_selector_all(PLACE_LINKS, "els => els.map(e => e.href)") or []
            before = len(links)
            for href in found:
                if href not in links:
                    links.append(href)
            stale = stale + 1 if len(links) == before else 0
            page.eval_on_selector(FEED, "el => el.scrollBy(0, el.scrollHeight)")
            self.sleep(self.delay)
        return links[:limit]
