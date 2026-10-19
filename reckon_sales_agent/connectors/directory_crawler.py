"""Permitted-directory lead crawler (pure: no Frappe imports).

Crawls listing pages of a business directory, association member list or
similar source that the tenant has confirmed it may use (``policy_reviewed``
on the connector). Every request goes through the SSRF-safe fetcher, obeys
``robots.txt`` for its host, waits between requests, and stays within the
configured page budget and path. No logins, no CAPTCHA handling, no evasion.

Extraction, most reliable first:
1. schema.org JSON-LD (LocalBusiness, Organization, Store, ...).
2. Listing links that point to a business's own website.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from datetime import datetime, timezone
from urllib.parse import quote_plus, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup

from reckon_sales_agent.connectors.base import (
    ConnectorError,
    ConnectorNotPermitted,
    DiscoveryQuery,
    SourceRecord,
    keep_all_policy,
)
from reckon_sales_agent.discovery.normalize import normalize_domain, normalize_space
from reckon_sales_agent.research.url_safety import FetchError, UnsafeURL, fetch

BUSINESS_TYPES = {"localbusiness", "organization", "corporation", "store", "wholesalestore", "pharmacy",
                  "medicalbusiness", "foodestablishment", "professionalservice", "homeandconstructionbusiness",
                  "automotivebusiness", "electronicsstore", "lodgingbusiness", "financialservice"}
GENERIC_LINK_TEXT = {"home", "contact", "about", "login", "sign in", "register", "website", "visit website",
                     "read more", "more", "next", "previous", "privacy", "terms", "facebook", "linkedin"}
MAX_PAGES_HARD = 50


class DirectoryCrawler:
    source_key = "permitted_directory"

    def __init__(self, start_urls: list[str], *, user_agent: str, allowed_path_prefix: str | None = None,
                 max_pages: int = 10, delay: float = 2.0, timeout: float = 10.0, max_bytes: int = 1_048_576,
                 fetcher=fetch, sleep=time.sleep, ai_extractor=None):
        self.start_urls = [u.strip() for u in start_urls if u and u.strip()]
        self.user_agent = user_agent
        self.allowed_path_prefix = (allowed_path_prefix or "").strip()
        self.max_pages = max(1, min(int(max_pages or 1), MAX_PAGES_HARD))
        self.delay = max(float(delay or 0), 1.0)
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.fetcher = fetcher
        self.sleep = sleep
        # Optional LLM fallback (ScrapeGraphAI-style): (page_text, url) -> [business dicts].
        self.ai_extractor = ai_extractor
        self._robots: dict[str, RobotFileParser | None] = {}

    def capabilities(self) -> dict:
        return {"live": True, "network": True, "official_api": False, "requires_policy_review": True,
                "max_pages": self.max_pages}

    def default_field_policy(self) -> dict:
        return keep_all_policy(attribution="Directory listing")

    def validate_configuration(self) -> None:
        if not self.start_urls:
            raise ConnectorNotPermitted("Add at least one start URL for the directory.")
        for url in self.start_urls:
            if not url.lower().startswith(("http://", "https://")):
                raise ConnectorNotPermitted(f"Start URL must be http(s): {url}")
            if "google." in (urlsplit(url).hostname or "") and "/maps" in url:
                raise ConnectorNotPermitted("Use a Google Maps connector (Places API, SerpAPI, Scrapingdog, Apify or the experimental browser) for Google Maps.")

    def discover(self, query: DiscoveryQuery) -> Iterable[SourceRecord]:
        self.validate_configuration()
        returned, pages, seen_pages, seen_keys = 0, 0, set(), set()
        queue = [self._fill(url, query) for url in self.start_urls]
        while queue and pages < self.max_pages and returned < query.max_results:
            url = queue.pop(0)
            if url in seen_pages:
                continue
            seen_pages.add(url)
            if not self._allowed(url):
                continue
            if pages:
                self.sleep(self.delay)
            try:
                result = self.fetcher(url, user_agent=self.user_agent, timeout=self.timeout, max_bytes=self.max_bytes)
            except UnsafeURL as exc:
                raise ConnectorError(f"Unsafe directory URL: {exc}", permanent=True, code="unsafe_url") from exc
            except FetchError:
                continue
            pages += 1
            soup = BeautifulSoup(result.text or "", "html.parser")
            now = datetime.now(timezone.utc).isoformat()
            found = extract_businesses(soup, result.url)
            if not found and self.ai_extractor:
                found = verified_ai_listings(self.ai_extractor(_visible_text(soup), result.url), soup)
            for fields in found:
                key = normalize_domain(fields.get("website")) or fields["business_name"].lower()
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                if not fields.get("city") and query.location:
                    fields["city"] = query.location.split(",")[-1].strip()
                if not fields.get("industry"):
                    fields["industry"] = query.keyword
                returned += 1
                yield SourceRecord(self.source_key, key, result.url, fields, now)
                if returned >= query.max_results:
                    return
            queue.extend(link for link in pagination_links(soup, result.url, self.allowed_path_prefix)
                         if link not in seen_pages)

    def _fill(self, template: str, query: DiscoveryQuery) -> str:
        return template.replace("{keyword}", quote_plus(query.keyword)).replace("{location}", quote_plus(query.location))

    def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
            try:
                text = self.fetcher(robots_url, user_agent=self.user_agent, timeout=self.timeout,
                                    max_bytes=256 * 1024).text
                parser = RobotFileParser()
                parser.parse(text.splitlines())
                self._robots[origin] = parser
            except FetchError:
                self._robots[origin] = None  # no robots.txt: no restriction
            except UnsafeURL:
                return False
        parser = self._robots[origin]
        return parser is None or parser.can_fetch(self.user_agent, url)


def _types(value) -> set[str]:
    values = value if isinstance(value, list) else [value]
    return {str(v).lower() for v in values if v}


def _jsonld_items(soup) -> list[dict]:
    items = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except (ValueError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                stack.extend(node.get("@graph") or [])
                stack.extend(node.get("itemListElement") or [])
                if isinstance(node.get("item"), dict):
                    stack.append(node["item"])
                if _types(node.get("@type")) & BUSINESS_TYPES:
                    items.append(node)
    return items


def _address(value) -> tuple[str, str, str]:
    if isinstance(value, dict):
        street = normalize_space(value.get("streetAddress"))
        city = normalize_space(value.get("addressLocality"))
        country = value.get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name")
        full = ", ".join(p for p in [street, city, normalize_space(value.get("addressRegion"))] if p)
        return full, city, normalize_space(country)
    return normalize_space(value), "", ""


def extract_businesses(soup, page_url: str) -> list[dict]:
    businesses = []
    for item in _jsonld_items(soup):
        name = normalize_space(item.get("name"))
        if not name:
            continue
        address, city, country = _address(item.get("address"))
        website = item.get("url") or item.get("sameAs")
        if isinstance(website, list):
            website = next((w for w in website if normalize_domain(w)), None)
        businesses.append({
            "business_name": name[:140],
            "website": website if website and normalize_domain(str(website)) else None,
            "phone": normalize_space(item.get("telephone")) or None,
            "email": normalize_space(item.get("email")).removeprefix("mailto:") or None,
            "address": address or None,
            "city": city or None,
            "country": country or None,
            "industry": normalize_space(item.get("description"))[:80] or None,
        })
    if businesses:
        return businesses
    page_host = (urlsplit(page_url).hostname or "").lower()
    for anchor in soup.find_all("a", href=True):
        href = urljoin(page_url, anchor["href"])
        host = (urlsplit(href).hostname or "").lower()
        text = normalize_space(anchor.get_text(" "))
        if not host or host == page_host or not normalize_domain(href):
            continue
        if not 3 <= len(text) <= 80 or text.lower() in GENERIC_LINK_TEXT or text.lower().startswith("http"):
            continue
        businesses.append({"business_name": text, "website": href})
    return businesses


def _visible_text(soup) -> str:
    copy = BeautifulSoup(str(soup), "html.parser")
    for tag in copy(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()
    return " ".join(copy.get_text(" ").split())[:15000]


def verified_ai_listings(items, soup) -> list[dict]:
    """Keep AI-extracted listings whose name really appears on the page; never invent contacts."""
    text = " ".join(soup.get_text(" ").split()).lower()
    kept = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        name = normalize_space(item.get("business_name"))
        if len(name) < 3 or name.lower() not in text:
            continue
        fields = {"business_name": name[:140]}
        for key in ("website", "phone", "email", "address", "city", "industry"):
            value = normalize_space(item.get(key))
            # Contact details must also be on the page, verbatim.
            if value and (key in ("city", "industry") or value.lower() in text):
                fields[key] = value
        if fields.get("website") and not normalize_domain(fields["website"]):
            fields.pop("website")
        kept.append(fields)
    return kept[:100]


def pagination_links(soup, page_url: str, allowed_prefix: str) -> list[str]:
    host = (urlsplit(page_url).hostname or "").lower()
    links = []
    for anchor in soup.find_all("a", href=True):
        href = urljoin(page_url, anchor["href"]).split("#")[0]
        parts = urlsplit(href)
        if (parts.hostname or "").lower() != host:
            continue
        if allowed_prefix and not parts.path.startswith(allowed_prefix):
            continue
        rel = " ".join(anchor.get("rel") or []).lower()
        text = normalize_space(anchor.get_text(" ")).lower()
        if "next" in rel or text in {"next", "next »", "»", "›", "পরবর্তী"} or "page=" in parts.query \
                or "/page/" in parts.path:
            if href not in links:
                links.append(href)
    return links[:10]
