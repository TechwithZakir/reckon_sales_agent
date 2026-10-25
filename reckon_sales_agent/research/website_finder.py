"""Find a prospect's own website when the source listing had none.

Uses whichever Google Search provider the vendor enabled: ScrapingBee or
Scrapingdog. A result is accepted only if its domain shares a distinctive
word with the business name; directories, marketplaces and social sites are
skipped. Keys are sent as the providers require and never logged.
"""

from __future__ import annotations

import requests

from reckon_sales_agent.discovery.normalize import normalize_domain, normalize_name

SCRAPINGDOG_SERP = "https://api.scrapingdog.com/google"
SCRAPINGBEE_SERP = "https://app.scrapingbee.com/api/v1/google"
SKIP_DOMAINS = ("facebook.com", "linkedin.com", "instagram.com", "youtube.com", "twitter.com", "x.com",
                "google.com", "bdtradeinfo.com", "yellowpages", "justdial", "daraz.com.bd", "bikroy.com",
                "wikipedia.org", "tripadvisor", "foodpanda", "pathao", "yelp.com")


def matches_name(domain: str, business_name: str) -> bool:
    words = [w for w in normalize_name(business_name).split() if len(w) >= 4]
    host = domain.replace("-", "").replace(".", " ")
    return any(word in host for word in words)


def pick_website(results: list[dict], business_name: str) -> str | None:
    for result in results:
        link = result.get("link") or result.get("url") or ""
        domain = normalize_domain(link)
        if not domain or any(skip in domain for skip in SKIP_DOMAINS):
            continue
        if matches_name(domain, business_name):
            return f"https://{domain}"
    return None


def find_website(api_key: str, business_name: str, city: str | None, session=None, timeout: int = 60,
                 provider: str = "scrapingdog") -> str | None:
    session = session or requests.Session()
    key = (api_key or "").strip()
    query = f"{business_name} {city or ''} Bangladesh".strip()
    try:
        if provider == "scrapingbee":
            response = session.get(SCRAPINGBEE_SERP, params={"search": query, "country_code": "bd", "language": "en"},
                                   headers={"Authorization": f"Bearer {key}"}, timeout=timeout)
        else:
            response = session.get(SCRAPINGDOG_SERP, params={"api_key": key, "query": query, "country": "bd",
                                                             "page": 0}, timeout=timeout)
    except requests.RequestException:
        return None
    if response.status_code != 200:
        return None
    data = response.json() or {}
    return pick_website(data.get("organic_results") or [], business_name)
