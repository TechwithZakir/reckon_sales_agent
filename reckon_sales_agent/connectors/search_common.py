"""Shared rules for Google Search lead sources (pure: no Frappe imports).

A Google Search result is a lead only when it points at a business's own
website: social networks, marketplaces, directories, news and reference
sites are skipped, and each domain counts once. The lead keeps the site's
home page (research reads it next), a name cleaned from the result title,
and a phone number when the snippet shows one.

Whichever way results arrive (Scrapingdog, ScrapingBee, SerpAPI or the
browser bot), the same field policy applies: search-derived fields are kept
for the vendor's retention window unless the company's own website confirms
them, and are attributed to Google Search.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from reckon_sales_agent.connectors.base import ConnectorNotPermitted, DiscoveryQuery, SourceRecord
from reckon_sales_agent.discovery.normalize import (
    PROSPECT_FIELDS,
    normalize_domain,
    normalize_space,
)

ATTRIBUTION = "Google Search"
COUNTRY = "bd"
# Not a business's own site: social, marketplaces, directories, news, reference, search engines.
SKIP_DOMAINS = (
    "facebook.com", "fb.com", "linkedin.com", "instagram.com", "youtube.com", "twitter.com", "x.com",
    "tiktok.com", "pinterest.", "whatsapp.com", "t.me", "google.", "bing.com", "yahoo.com", "duckduckgo.com", "brave.com",
    "wikipedia.org", "wikimedia.org", "quora.com", "reddit.com", "medium.com", "blogspot.", "wordpress.com",
    "amazon.", "alibaba.com", "aliexpress.", "ebay.", "daraz.com", "bikroy.com", "chaldal.com", "foodpanda.",
    "pathao.com", "shohoz.com", "othoba.com", "evaly.com", "ajkerdeal.com", "pickaboo.com",
    "yellowpages", "justdial", "yelp.", "tripadvisor", "bdtradeinfo.com", "bdyellowpages", "dhakayellowpages",
    "cybo.com", "zaubacorp", "opencorporates", "dnb.com", "zoominfo", "crunchbase", "glassdoor", "indeed.",
    "bdjobs.com", "jobsite", "waze.com", "mapcarta", "wikimapia", "foursquare.com", "trustpilot",
    "prothomalo.com", "thedailystar.net", "bdnews24.com", "dhakatribune.com", "tbsnews.net", "jugantor.com",
    "kalerkantho.com", "samakal.com", "ittefaq.com.bd", "banglanews24.com", "risingbd.com", "bbc.", "cnn.com",
    "gov.bd", "edu.bd",
    "medex.com.bd", "mawbiz.com.bd", "bangladeshyp", "bdbusinessdirectory", "infoisinfo", "hotfrog", "brownbook",
    "cylex", "tuugo", "bizdirlib", "allbiz", "lacartes", "nicelocal", "top-rated.online", "helpmecovid",
    "vymaps.com", "medicare24bd.com", "dhakasnob.com", "hugedomains.com", "sedo.com", "dan.com", "afternic.com",
)
# Pages about many businesses (lists, rankings, directories) rather than one business's own site.
LISTICLE_TITLE = re.compile(
    r"^\s*(the\s+)?(top|best)\s+\d+|^\s*(the\s+)?\d+\s+(best|top|great)\b|^\s*list\s+of\b"
    r"|^\s*(the\s+)?best\s+\w+\s+(in|near|around)\b"
    r"|\b(directory|directories|yellow\s*pages|near\s+me|discounts?\s+list|in\s+the\s+city|domains?\s+for\s+sale"
    r"|is\s+for\s+sale|hugedomains)\b",
    re.I,
)
# Words that say nothing about which business a domain belongs to.
NAME_STOPWORDS = {
    "the", "and", "ltd", "limited", "company", "co", "inc", "plc", "pvt", "private", "group", "bangladesh", "dhaka",
    "shop", "store", "stores", "center", "centre", "services", "service", "online", "best", "new", "home", "www", "com",
}
DIRECTORY_PATH = re.compile(r"/(listings?|directory|category|categories|tags?|search|places?|top-\d+|best-\d+)(/|$)", re.I)
TITLE_SEPARATORS = re.compile(r"\s+[|\-–—:·•»]\s+")
GENERIC_TITLE_PARTS = {
    "home", "home page", "homepage", "official website", "official site", "welcome", "about us", "contact us",
    "contact", "best", "top", "online", "bangladesh", "dhaka", "index",
}
BD_PHONE = re.compile(r"(?:\+?880[\s-]?|0)1[3-9]\d(?:[\s-]?\d){7}|(?:\+?880[\s-]?|0)2[\s-]?\d(?:[\s-]?\d){6,7}")


def search_field_policy(retention_days: int | None, attribution: str = ATTRIBUTION) -> dict:
    days = int(retention_days or 0) or None
    return {
        field: {"persist": True, "retention_days": days, "crm_sync": days is None, "attribution": attribution}
        for field in PROSPECT_FIELDS
    }


def require_search_terms(terms_ack: bool, enabled: bool, credential: str | None, name: str,
                         needs_credential: bool = True) -> None:
    if not enabled:
        raise ConnectorNotPermitted(f"{name} is disabled by the platform vendor.")
    if not terms_ack:
        raise ConnectorNotPermitted("The vendor has not accepted responsibility for Google Search data use.")
    if needs_credential and not credential:
        raise ConnectorNotPermitted(f"No {name} credential is configured.")


def _skipped(domain: str, skip: str) -> bool:
    if skip.endswith("."):  # any TLD: "google." matches google.com, maps.google.com.bd
        return domain.startswith(skip) or f".{skip}" in domain
    if "." in skip:  # the domain, its subdomains and country variants (daraz.com.bd); never fedex.com for x.com
        return (domain == skip or domain.endswith(f".{skip}") or domain.startswith(f"{skip}.")
                or f".{skip}." in domain)
    return skip in domain  # a brand fragment: "yellowpages"


SECOND_LEVEL = {"com", "co", "net", "org", "gov", "edu", "ac", "info", "biz"}


def site_key(url: str | None) -> str:
    """One key per business site: web.praavahealth.com and praavahealth.com are the same business;
    shop.example.com.bd -> example.com.bd."""
    labels = (normalize_domain(url or "") or "").split(".")
    if len(labels) >= 3 and labels[-2] in SECOND_LEVEL and len(labels[-1]) == 2:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def is_business_site(url: str | None) -> bool:
    domain = normalize_domain(url or "")
    return bool(domain) and not any(_skipped(domain, skip) for skip in SKIP_DOMAINS)


def home_page(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme or 'https'}://{parts.netloc}/"


def is_listing_page(title: str | None, url: str) -> bool:
    """A page about many businesses ("Top 10 pharmacies in Dhaka", /category/...), not one business."""
    return bool(LISTICLE_TITLE.search(normalize_space(title)) or DIRECTORY_PATH.search(urlsplit(url).path or ""))


def name_matches_domain(name: str, url: str, keyword: str = "") -> bool:
    """Does the site belong to this business? 'BRAC Healthcare' fits brachealthcare.com; 'Gulshan Pharma' does not
    fit medicare24bd.com (a directory page about it). Acronyms of 3 capitals (ACI, BRAC) count as distinctive."""
    host = re.sub(r"[^a-z0-9]", "", (normalize_domain(url) or "").rsplit(".", 1)[0].lower())
    if not host:
        return False
    generic = NAME_STOPWORDS | {normalize_space(keyword).lower()} | set(GENERIC_TITLE_PARTS)
    tokens = [t for t in re.findall(r"[A-Za-z0-9]+", name or "")
              if t.lower() not in generic and (len(t) >= 4 or (len(t) == 3 and t.isupper()))]
    if not tokens:
        return True  # nothing distinctive to compare (the name likely came from the domain itself)
    return any(t.lower() in host for t in tokens)


def is_generic_name(name: str, keyword: str = "") -> bool:
    """'Pharmacy' or 'Home' is a page label, not a business name."""
    lowered = normalize_space(name).lower()
    word = normalize_space(keyword).lower()
    forms = {word, f"{word}s", f"{word[:-1]}ies" if word.endswith("y") else f"{word}s"} if word else set()
    return lowered in GENERIC_TITLE_PARTS or lowered in forms


def business_name(title: str | None, url: str, keyword: str = "") -> str:
    """'ABC Pharma | Best Pharmacy in Dhaka' -> 'ABC Pharma'; falls back to the domain."""
    parts = [normalize_space(p) for p in TITLE_SEPARATORS.split(normalize_space(title)) if normalize_space(p)]
    for part in parts:
        part = re.sub(r"^(welcome to|home of)\s+", "", part, flags=re.I)
        if is_generic_name(part, keyword) or len(part) < 2:
            continue
        return part[:140]
    domain = normalize_domain(url) or ""
    label = domain.split(".")[0].replace("-", " ")
    return label.title()[:140] if label else ""


def phone_from(text: str | None) -> str | None:
    match = BD_PHONE.search(text or "")
    return normalize_space(match.group(0)) if match else None


EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}")


def email_from(text: str | None) -> str | None:
    """The first plausible email in page text (not image names like logo@2x.png)."""
    for match in EMAIL.finditer(text or ""):
        email = match.group(0).strip(".").lower()
        if not email.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")):
            return email
    return None


def records_from_results(results: list[dict], query: DiscoveryQuery, source_key: str, seen: set[str],
                         limit: int) -> list[SourceRecord]:
    """Organic results ({title, link|url, snippet|description}) -> one record per new business domain."""
    now = datetime.now(timezone.utc).isoformat()
    records = []
    for result in results:
        if len(records) >= limit:
            break
        if not isinstance(result, dict):
            continue
        link = result.get("link") or result.get("url") or ""
        if not link.startswith(("http://", "https://")) or not is_business_site(link):
            continue
        if is_listing_page(result.get("title"), link):
            continue
        domain = site_key(link)
        if domain in seen:
            continue
        name = business_name(result.get("title"), link, query.keyword)
        if not name or not name_matches_domain(name, link, query.keyword):
            continue  # a page about the business on someone else's site (directory, marketplace, parked domain)
        seen.add(domain)
        snippet = result.get("snippet") or result.get("description") or ""
        records.append(SourceRecord(
            source_key=source_key,
            external_id=domain,
            source_url=link,
            fields={
                "business_name": name,
                "website": home_page(link),
                "phone": phone_from(snippet),
                "email": email_from(snippet),
                "industry": query.keyword or None,
                "city": (query.location or "").split(",")[-1].strip() or None,
            },
            retrieved_at=now,
        ))
    return records
