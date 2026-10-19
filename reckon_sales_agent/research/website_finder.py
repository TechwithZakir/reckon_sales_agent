"""Find a prospect's own website when the source listing had none.

Uses the Scrapingdog Google SERP API when the vendor enabled Scrapingdog. A
result is accepted only if its domain shares a distinctive word with the
business name, and directories, marketplaces and social sites are skipped.
"""

from __future__ import annotations

import requests

from reckon_sales_agent.discovery.normalize import normalize_domain, normalize_name

SERP_ENDPOINT = "https://api.scrapingdog.com/google"
SKIP_DOMAINS = ("facebook.com", "linkedin.com", "instagram.com", "youtube.com", "twitter.com", "x.com",
                "google.com", "bdtradeinfo.com", "yellowpages", "justdial", "daraz.com.bd", "bikroy.com",
                "wikipedia.org", "tripadvisor", "foodpanda", "pathao")


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


def find_website(api_key: str, business_name: str, city: str | None, session=None, timeout: int = 30) -> str | None:
    session = session or requests.Session()
    try:
        response = session.get(SERP_ENDPOINT, params={
            "api_key": api_key, "query": f"{business_name} {city or ''} Bangladesh".strip(),
            "country": "bd", "page": 0,
        }, timeout=timeout)
    except requests.RequestException:
        return None
    if response.status_code != 200:
        return None
    data = response.json() or {}
    return pick_website(data.get("organic_results") or [], business_name)
