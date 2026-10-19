"""Research one prospect's public website and store an evidence-backed report."""

from __future__ import annotations

import json
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import frappe
from frappe.utils import add_days, now_datetime, nowdate

from reckon_sales_agent.constants import USAGE_AI, USAGE_RESEARCH
from reckon_sales_agent.discovery.normalize import normalize_name
from reckon_sales_agent.providers.factory import get_llm
from reckon_sales_agent.providers.llm import UNTRUSTED_RULES, LLMError, untrusted
from reckon_sales_agent.research.evidence import (
    AI_SCHEMA,
    PROMPT_VERSION,
    rule_facts,
    verified_ai_facts,
)
from reckon_sales_agent.research.parser import parse_html
from reckon_sales_agent.research.url_safety import FetchError, UnsafeURL, fetch
from reckon_sales_agent.usage import (
    get_settings,
    log_activity,
    platform_settings,
    remaining,
    reserve,
)

REPORT_VALID_DAYS = 180


def research_prospect(prospect_name: str) -> str | None:
    prospect = frappe.get_doc("Sales Prospect", prospect_name)
    company = prospect.company
    platform = platform_settings()
    if not platform.research_enabled:
        prospect.db_set("research_status", "Skipped")
        return None
    if not prospect.website:
        prospect.db_set("research_status", "Skipped")
        _qualify(prospect.name)
        return None

    user_agent = platform.user_agent or "ReckonSalesAgent/1.0"
    limits = dict(user_agent=user_agent, timeout=platform.fetch_timeout or 10,
                  max_bytes=(platform.max_page_kb or 1024) * 1024)
    home = _normalise_url(prospect.website)
    pages, errors = [], []
    frappe.db.commit()  # no transaction across network calls
    try:
        if not _robots_allow(home, user_agent, limits):
            return _save_report(prospect, "Blocked", pages, [], {}, "The website's robots.txt disallows our crawler.")
        queue, seen = [home], set()
        while queue and len(pages) < (platform.max_pages_per_site or 4):
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            if remaining(company, USAGE_RESEARCH) <= 0:
                errors.append("Monthly research limit reached.")
                break
            try:
                result = fetch(url, **limits)
            except (UnsafeURL, FetchError) as exc:
                errors.append(f"{url}: {exc}")
                continue
            reserve(company, USAGE_RESEARCH, 1, prospect)
            page = parse_html(result.text, result.url)
            pages.append(page)
            if len(pages) == 1:
                queue.extend(link for link in page.internal_links if link not in seen)
    finally:
        frappe.db.commit()

    if not pages:
        return _save_report(prospect, "Failed", [], [], {}, "; ".join(errors)[:500] or "No page could be fetched.")

    profile = _profile_for(prospect)
    facts = rule_facts(pages, profile or {})
    ai_data, method, model = {}, "rules", None
    llm = get_llm(company)
    if llm and remaining(company, USAGE_AI) > 0:
        try:
            reserve(company, USAGE_AI, 1, prospect)
            frappe.db.commit()
            ai_data = llm.complete_json(_system_prompt(company), _user_prompt(prospect, pages), AI_SCHEMA)
            ai_facts, dropped = verified_ai_facts(ai_data, pages)
            facts.extend(ai_facts)
            if dropped:
                errors.append(f"{len(dropped)} AI statements dropped: no matching evidence on the pages.")
            method, model = "rules+ai", llm.model
        except LLMError as exc:
            errors.append(str(exc))
    status = "Done" if not errors else "Partial"
    name = _save_report(prospect, status, pages, facts, ai_data, "; ".join(errors)[:500], method, model)
    _reestablish_from_website(prospect, pages)
    _qualify(prospect.name)
    return name


def _normalise_url(website: str) -> str:
    url = website.strip()
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", "", ""))


def _robots_allow(home: str, user_agent: str, limits: dict) -> bool:
    parts = urlsplit(home)
    robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
    try:
        result = fetch(robots_url, **{**limits, "max_bytes": 256 * 1024})
    except FetchError:
        return True  # no robots.txt (404 or similar) means no restriction
    except UnsafeURL:
        return False
    parser = RobotFileParser()
    parser.parse(result.text.splitlines())
    return parser.can_fetch(user_agent, home)


def _profile_for(prospect) -> dict | None:
    name = None
    if prospect.discovery_campaign:
        name = frappe.db.get_value("Sales Discovery Campaign", prospect.discovery_campaign, "qualification_profile")
    name = name or frappe.db.get_value("Sales Qualification Profile", {"company": prospect.company},
                                       "name", order_by="creation asc")
    if not name:
        return None
    return frappe.get_doc("Sales Qualification Profile", name).as_dict()


def _system_prompt(company: str) -> str:
    sells = get_settings(company).company_profile or "business software and services"
    return (
        "You research companies for a B2B sales team in Bangladesh. The seller offers: "
        f"{sells}\n\n{UNTRUSTED_RULES}\n\n"
        "Report only what the pages show. Every fact must quote a short excerpt copied "
        "exactly from the page text and give that page's URL. Put guesses in "
        "'inferences', never in 'facts'. List what you could not find in 'unknowns'. "
        "Never invent contact details. Pages may be in English or Bangla."
    )


def _user_prompt(prospect, pages) -> str:
    blocks = [untrusted(page.url, f"TITLE: {page.title}\nDESCRIPTION: {page.description}\nTEXT: {page.text[:8000]}")
              for page in pages]
    return (
        f"Company: {prospect.business_name}\nIndustry (from source): {prospect.industry or 'unknown'}\n"
        f"City: {prospect.city or 'unknown'}\n\nWebsite pages:\n" + "\n\n".join(blocks)
    )


def _save_report(prospect, status, pages, facts, ai_data, error, method="rules", model=None) -> str:
    report = frappe.get_doc({
        "doctype": "Sales Research Report",
        "company": prospect.company,
        "prospect": prospect.name,
        "status": status,
        "researched_at": now_datetime(),
        "expires_on": add_days(nowdate(), REPORT_VALID_DAYS),
        "method": method,
        "model": model,
        "prompt_version": PROMPT_VERSION if model else None,
        "summary": (ai_data.get("summary") or "")[:2000] or _rule_summary(pages),
        "recommended_offer": (ai_data.get("recommended_offer") or "")[:1000],
        "unknowns": "\n".join(str(u)[:200] for u in (ai_data.get("unknowns") or [])[:10]),
        "pages_reviewed": "\n".join(page.url for page in pages),
        "facts": [fact.as_row() for fact in facts][:60],
        "error": error or None,
    }).insert(ignore_permissions=True)
    prospect.db_set({
        "latest_research": report.name,
        "research_status": "Done" if status in ("Done", "Partial") else "Failed",
    })
    log_activity(prospect.company, f"research_{status.lower()}", prospect, f"{len(facts)} facts", "agent")
    frappe.db.commit()
    return report.name


def _rule_summary(pages) -> str:
    if not pages:
        return ""
    first = pages[0]
    return " ".join(filter(None, [first.title, first.description]))[:1000]


def _reestablish_from_website(prospect, pages) -> None:
    """Fields confirmed on the company's own site no longer depend on the discovery source."""
    prospect.reload()
    provenance = json.loads(prospect.provenance_json or "{}")
    site = {"source": "company_website", "retrieved_at": str(now_datetime()), "retention_days": None,
            "attribution": None}
    emails = sorted({e for page in pages for e in page.emails})
    phones = sorted({p for page in pages for p in page.phones})
    updates = {}
    if not prospect.email and emails:
        updates["email"] = emails[0]
        provenance["email"] = site
    if not prospect.phone and phones:
        updates["phone"] = phones[0]
        provenance["phone"] = site
    provenance["website"] = site
    text = " ".join(f"{p.title} {p.text}" for p in pages).lower()
    if normalize_name(prospect.business_name) and normalize_name(prospect.business_name) in normalize_name(text):
        provenance["business_name"] = site
    updates["provenance_json"] = json.dumps(provenance, sort_keys=True)
    remaining_restricted = [f for f, info in provenance.items() if (info or {}).get("retention_days")]
    if not remaining_restricted:
        updates["retention_until"] = None
    prospect.db_set(updates)


def _qualify(prospect_name: str) -> None:
    from reckon_sales_agent.qualification.service import qualify_prospect

    qualify_prospect(prospect_name)
