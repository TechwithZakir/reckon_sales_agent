"""Competitor agent: keeps a battlecard of named competitors from their own public websites.

Weekly, for each competitor the Company lists (up to five, "Name | https://their-site" per line), it reads the
home page and up to three pages about products, pricing or clients, with the same safe fetcher as lead research
(public addresses only, size and time limits). The AI pulls out launches, prices, products and named clients,
each with the exact sentence it came from; a fact whose sentence is not on the page is dropped. Facts are saved as
Draft knowledge items in the "Competitor" category: nothing is used until a person approves it, and approved
competitor facts are only used where a battlecard belongs (proposals and the salesperson's own view), never in
cold outreach. ``parse_competitors``, ``pick_pages`` and ``on_page`` are pure.
"""

from __future__ import annotations

import re

MAX_COMPETITORS = 5
PAGE_WORDS = ("pricing", "price", "plans", "product", "products", "solution", "clients", "customers", "case",
              "news", "blog", "about", "features", "মূল্য", "পণ্য")
SCHEMA = {
    "type": "object",
    "properties": {"facts": {"type": "array", "items": {
        "type": "object",
        "properties": {"kind": {"type": "string", "enum": ["product", "pricing", "client", "launch", "positioning"]},
                       "statement": {"type": "string"}, "evidence": {"type": "string"}, "url": {"type": "string"}},
        "required": ["kind", "statement", "evidence", "url"], "additionalProperties": False}}},
    "required": ["facts"], "additionalProperties": False,
}


def parse_competitors(text: str | None) -> list[tuple[str, str]]:
    out = []
    for line in (text or "").splitlines():
        name, _, url = line.partition("|")
        name, url = name.strip(), url.strip()
        if name and url:
            out.append((name[:80], url if "://" in url else f"https://{url}"))
    return out[:MAX_COMPETITORS]


def pick_pages(links: list[str], limit: int = 3) -> list[str]:
    scored = [(sum(word in link.lower() for word in PAGE_WORDS), link) for link in dict.fromkeys(links)]
    return [link for score, link in sorted(scored, key=lambda x: -x[0]) if score][:limit]


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def on_page(evidence: str, page_texts: dict[str, str]) -> str | None:
    """The page URL whose text contains the evidence sentence, or None."""
    needle = _squash(evidence)
    if len(needle) < 12:
        return None
    return next((url for url, text in page_texts.items() if needle in _squash(text)), None)


# --------------------------------------------------------------------------- Frappe side


def watch(company: str) -> str:
    import frappe

    from reckon_sales_agent.constants import USAGE_AI
    from reckon_sales_agent.providers.factory import get_llm
    from reckon_sales_agent.providers.llm import LLMError, untrusted
    from reckon_sales_agent.research.parser import parse_html
    from reckon_sales_agent.research.url_safety import FetchError, UnsafeURL, fetch
    from reckon_sales_agent.usage import (
        get_settings,
        log_activity,
        platform_settings,
        remaining,
        reserve,
    )

    llm = get_llm(company)
    if not llm:
        return "AI is off: competitors not checked"
    platform = platform_settings()
    limits = dict(user_agent=platform.user_agent or "ReckonSalesAgent/1.0", timeout=platform.fetch_timeout or 10,
                  max_bytes=(platform.max_page_kb or 1024) * 1024)
    added = 0
    for name, home in parse_competitors(get_settings(company).get("competitors")):
        pages = []
        try:
            first = parse_html(fetch(home, **limits).text, home)
            pages.append(first)
            for url in pick_pages(first.internal_links):
                try:
                    pages.append(parse_html(fetch(url, **limits).text, url))
                except (UnsafeURL, FetchError):
                    continue
        except (UnsafeURL, FetchError):
            continue
        finally:
            frappe.db.commit()
        if remaining(company, USAGE_AI) <= 0:
            break
        reserve(company, USAGE_AI, 1, None)
        texts = {p.url: f"{p.title} {p.description} {p.text}" for p in pages}
        try:
            data = llm.complete_json(
                "You extract facts about a competitor of a B2B seller in Bangladesh from its own website, for the "
                "seller's battlecard. Only facts the pages state: products, prices, named clients, launches, how they "
                "position themselves. For each, copy the exact sentence from the page as evidence and give its URL. "
                "No opinions, no guesses.",
                "\n".join(untrusted(f"page {p.url}", texts[p.url][:6000]) for p in pages), SCHEMA, max_tokens=2500)
        except LLMError:
            continue
        for fact in (data.get("facts") or [])[:12]:
            url = on_page(str(fact.get("evidence") or ""), texts)
            if not url:
                continue  # the sentence is not on their site: drop it
            title = f"{name}: {str(fact.get('statement') or '')[:100]}"[:140]
            if frappe.db.exists("Sales Knowledge Item", {"company": company, "title": title}):
                continue
            frappe.get_doc({
                "doctype": "Sales Knowledge Item", "company": company, "title": title, "category": "Competitor",
                "status": "Draft", "language": "Any", "source_url": url,
                "content": f"{fact.get('statement')}\n\nFrom their site ({fact.get('kind')}): \"{fact.get('evidence')}\"",
            }).insert(ignore_permissions=True)
            added += 1
        frappe.db.commit()
    log_activity(company, "competitors_checked", None, f"{added} competitor fact(s) drafted for your approval",
                 actor_type="agent", agent="Content", policy_outcome="draft only: a person approves")
    return f"{added} competitor fact(s) to approve"
