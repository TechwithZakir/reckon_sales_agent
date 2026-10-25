"""EXPERIMENTAL google_search_browser_experimental: headless Chromium (Playwright) on Google Search.

Opens google.com, types "keyword in location", reads the organic results and
follows "Next" for a few pages. Same rules as the Maps browser bot: not an
API, not supported by Google, restricted by Google's Terms of Service, and
off unless the platform vendor enables it and accepts responsibility.

* the browser's own user agent, no proxies, no stealth plugins, no
  fingerprint changes, no CAPTCHA solving, no login;
* a consent wall, CAPTCHA or "unusual traffic" page stops the run;
* a delay between result pages and a hard cap on results per search.

Google Search blocks automated traffic from data-centre addresses sooner than
Maps does; prefer an API provider for regular use. Selectors live in one
place below. Installation is the same as for the Maps browser bot.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable
from urllib.parse import quote

from reckon_sales_agent.connectors.base import (
    ConnectorError,
    ConnectorNotPermitted,
    DiscoveryQuery,
    SourceRecord,
)
from reckon_sales_agent.connectors.maps_common import guard_google_page
from reckon_sales_agent.connectors.search_common import (
    COUNTRY,
    records_from_results,
    require_search_terms,
    search_field_policy,
)

HARD_CAP = 50
MAX_PAGES = 5
SEARCH_HOME = "https://www.google.com/?hl={language}&gl={country}"
SEARCH_URL = "https://www.google.com/search?q={query}&hl={language}&gl={country}"
SEARCH_BOX = 'textarea[name="q"], input[name="q"]'
RESULTS = "#search"
NEXT_PAGE = "a#pnnext"
NO_RESULTS = re.compile(r"did not match any documents|no results found|কোনো ফলাফল", re.I)
# Organic results: links with a heading, plus the visible text of their result block (for phone numbers).
EXTRACT_JS = """() => [...document.querySelectorAll('#search a:has(h3)')].map((a) => {
  const block = a.closest('div.g, div.MjjYud, div[data-hveid]') || a;
  return { link: a.href, title: a.querySelector('h3').innerText, snippet: (block.innerText || '').slice(0, 500) };
})"""


class GoogleSearchBrowserConnector:
    source_key = "google_search_browser_experimental"

    def __init__(self, *, enabled: bool, terms_ack: bool, max_results: int = 30, delay: float = 4.0,
                 language: str = "en", country: str = COUNTRY, retention_days: int = 30,
                 playwright_factory=None, sleep=time.sleep):
        self.enabled = enabled
        self.terms_ack = terms_ack
        self.max_results = max(1, min(int(max_results or 1), HARD_CAP))
        self.delay = max(float(delay or 0), 3.0)
        self.language = re.sub(r"[^a-zA-Z-]", "", language or "en")[:8] or "en"
        self.country = re.sub(r"[^a-zA-Z]", "", country or COUNTRY)[:2].lower() or COUNTRY
        self.retention_days = retention_days
        self.playwright_factory = playwright_factory
        self.sleep = sleep
        self._declined = False  # Google's consent wall, declined at most once

    def capabilities(self) -> dict:
        return {"live": True, "network": True, "experimental": True, "official_api": False,
                "result_type": "websites", "max_results": self.max_results}

    def default_field_policy(self) -> dict:
        return search_field_policy(self.retention_days)

    def validate_configuration(self) -> None:
        require_search_terms(self.terms_ack, self.enabled, None, "google_search_browser_experimental",
                             needs_credential=False)
        if self.playwright_factory is None:
            try:
                import playwright.sync_api  # noqa: F401
            except ImportError as exc:
                raise ConnectorNotPermitted(
                    "Playwright is not installed on the server. In the bench folder run "
                    "./env/bin/pip install playwright, then as the bench user "
                    "./env/bin/playwright install chromium.") from exc

    def discover(self, query: DiscoveryQuery) -> Iterable[SourceRecord]:
        self.validate_configuration()
        limit = min(query.max_results, self.max_results)
        factory = self.playwright_factory
        if factory is None:
            from playwright.sync_api import sync_playwright

            factory = sync_playwright
        with factory() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True)
            except Exception as exc:
                if "Executable doesn't exist" in str(exc) or "playwright install" in str(exc):
                    raise ConnectorNotPermitted(
                        "Chromium is not installed for the bench user. As that user (no sudo) run: "
                        "./env/bin/playwright install chromium ; and once as root: "
                        "sudo ./env/bin/playwright install-deps chromium") from exc
                raise ConnectorError(f"Headless browser failed to start: {str(exc).splitlines()[0][:200]}",
                                     permanent=True, code="browser_start") from exc
            try:
                page = browser.new_context(locale=self.language).new_page()
                page.set_default_timeout(20_000)
                self._search(page, query)
                seen: set[str] = set()
                returned = 0
                for number in range(MAX_PAGES):
                    if not self._wait_for_results(page):
                        return
                    results = page.evaluate(EXTRACT_JS) or []
                    for record in records_from_results(results, query, self.source_key, seen, limit - returned):
                        returned += 1
                        yield record
                    if returned >= limit or number == MAX_PAGES - 1 or not self._next_page(page):
                        return
            finally:
                browser.close()

    def _search(self, page, query: DiscoveryQuery) -> None:
        """Open google.com, type the search and press Enter; fall back to the search URL."""
        page.goto(SEARCH_HOME.format(language=self.language, country=self.country), wait_until="domcontentloaded")
        self._check(page)
        try:
            page.wait_for_selector(SEARCH_BOX, timeout=10_000)
            page.fill(SEARCH_BOX, query.query_text)
            page.press(SEARCH_BOX, "Enter")
            page.wait_for_load_state("domcontentloaded")
        except Exception:
            page.goto(SEARCH_URL.format(query=quote(query.query_text), language=self.language, country=self.country),
                      wait_until="domcontentloaded")
        self._check(page)

    def _wait_for_results(self, page) -> bool:
        """True when organic results are on the page; False when Google says there are none."""
        try:
            page.wait_for_selector(RESULTS, timeout=20_000)
            return True
        except Exception as exc:
            self._check(page)
            if NO_RESULTS.search(self._text(page)):
                return False
            raise ConnectorError("Google Search did not show results in time.", code="no_results_list") from exc

    def _next_page(self, page) -> bool:
        try:
            href = page.get_attribute(NEXT_PAGE, "href", timeout=2_000)
        except Exception:
            return False
        if not href:
            return False
        self.sleep(self.delay)
        page.goto(href if href.startswith("http") else f"https://www.google.com{href}", wait_until="domcontentloaded")
        self._check(page)
        return True

    def _text(self, page) -> str:
        try:
            return page.inner_text("body")[:5000]
        except Exception:
            return ""

    def _check(self, page) -> None:
        self._declined = guard_google_page(page, self._declined)
