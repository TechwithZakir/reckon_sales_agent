"""Market Research Agent: Business Profile -> web research -> Market Brief -> Targeting Profiles.

1. The seller describes the business once (Sales Business Profile); best
   customers can be imported from won CRM deals.
2. The agent reads the market through the active page-context and web-search
   providers (Brave by default), within the vendor's per-brief request budget.
3. Claude turns the evidence into customer segments with search keywords,
   Bangla variants, locations and buying signals; segments may only cite pages
   the agent read. Without AI, a plan is built from the profile itself.
4. A manager approves the brief; each kept segment becomes a Targeting
   Profile that Lead Finder Studio can search with.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now_datetime

from reckon_sales_agent.connectors.base import ConnectorError
from reckon_sales_agent.constants import USAGE_AI, USAGE_RESEARCH
from reckon_sales_agent.providers.factory import get_llm
from reckon_sales_agent.providers.llm import LLMError, untrusted
from reckon_sales_agent.research.market_plan import (
    MARKET_SCHEMA,
    MARKET_SYSTEM,
    SEGMENT_FIELDS,
    best_customer_line,
    clean_brief,
    profile_prompt,
    research_queries,
    rule_brief,
    segment_to_targeting,
)
from reckon_sales_agent.usage import log_activity, platform_settings, remaining, reserve

PROFILE = "Sales Business Profile"
BRIEF = "Sales Market Brief"
EVIDENCE_CHARS_PER_PAGE = 1500
EVIDENCE_CHARS_TOTAL = 60_000


def business_profile(company: str, create: bool = True):
    name = frappe.db.get_value(PROFILE, {"company": company})
    if name:
        return frappe.get_doc(PROFILE, name)
    if not create:
        return None
    return frappe.get_doc({"doctype": PROFILE, "company": company, "business_name": company,
                           "languages": "English, Bangla"})


def import_best_customers(profile) -> int:
    """Add organisations from the Company's won CRM deals to the profile's best customers."""
    if not frappe.db.table_exists("CRM Deal"):
        return 0
    won = ["Won"]
    if frappe.db.has_column("CRM Deal Status", "type"):
        won = frappe.get_all("CRM Deal Status", filters={"type": "Won"}, pluck="name") or won
    organizations = frappe.get_all("CRM Deal", filters={"rsa_company": profile.company, "status": ["in", won],
                                                        "organization": ["is", "set"]},
                                   pluck="organization", order_by="modified desc", limit=60)
    existing = {line.split("|")[0].strip().lower() for line in (profile.best_customers or "").splitlines() if line}
    added = []
    for name in dict.fromkeys(organizations):
        org = frappe.db.get_value("CRM Organization", name, ["organization_name", "website", "industry"], as_dict=True)
        if org and org.organization_name and org.organization_name.lower() not in existing:
            added.append(best_customer_line(org.organization_name, org.website, org.industry))
            existing.add(org.organization_name.lower())
    if added:
        profile.best_customers = "\n".join(filter(None, [(profile.best_customers or "").strip(), *added[:30]]))
    profile.best_customers_synced_on = now_datetime()
    return len(added)


def start_research(profile) -> str:
    """Create a brief and research it in the background (or build it from rules when AI is off)."""
    if not (profile.what_we_sell or profile.products or profile.target_industries or profile.business_types):
        frappe.throw(_("Describe what you sell and who buys it first."))
    brief = frappe.get_doc({
        "doctype": BRIEF, "company": profile.company, "business_profile": profile.name, "status": "Researching",
        "brief_title": _("Market brief · {0}").format(now_datetime().strftime("%Y-%m-%d %H:%M")),
    }).insert(ignore_permissions=True)
    profile.db_set("latest_brief", brief.name)
    log_activity(profile.company, "market_research_started", brief)
    if not get_llm(profile.company):
        _save(brief, rule_brief(profile.as_dict()), method="rules", sources=[], providers=[], requests=0)
        return brief.name
    frappe.enqueue("reckon_sales_agent.research.market.run_market_research", queue="long", timeout=1200,
                   enqueue_after_commit=True, brief=brief.name)
    return brief.name


def run_market_research(brief: str) -> None:
    doc = frappe.get_doc(BRIEF, brief)
    try:
        _research(doc)
    except Exception as exc:
        frappe.db.rollback()
        frappe.log_error(title="Sales Agent market research failed", reference_doctype=BRIEF, reference_name=brief)
        doc.reload()
        doc.db_set({"status": "Failed", "error": str(exc)[:500], "researched_on": now_datetime()})
        frappe.db.commit()


def _research(doc) -> None:
    from reckon_sales_agent.providers.router import page_context

    profile = frappe.get_doc(PROFILE, doc.business_profile).as_dict()
    budget = int(platform_settings().market_research_max_requests or 12)
    region = (profile.get("regions") or "").splitlines()[0] if profile.get("regions") else ""
    evidence, sources, providers, errors, requests = [], [], set(), [], 0
    for query in research_queries(profile, max_queries=budget):
        if requests >= budget or remaining(doc.company, USAGE_RESEARCH) <= 0:
            break
        reserve(doc.company, USAGE_RESEARCH, 1, doc)
        frappe.db.commit()  # no open transaction across the network call
        requests += 1
        try:
            rows, provider = page_context(query, location=region, count=6)
        except ConnectorError as exc:
            errors.append(str(exc))
            if exc.permanent and exc.code in ("provider_budget", "not_permitted", "auth", "billing"):
                break
            continue
        providers.add(provider)
        for row in rows:
            if row["url"] in sources:
                continue
            sources.append(row["url"])
            evidence.append(f"[{row['url']}] {row['title']}\n{row['text'][:EVIDENCE_CHARS_PER_PAGE]}")
    if not evidence:
        brief = rule_brief(profile)
        brief["unknowns"] = (["Web research found nothing: " + "; ".join(errors[-2:])] if errors else []) \
            + brief["unknowns"]
        _save(doc, brief, method="rules", sources=[], providers=sorted(providers), requests=requests)
        return
    llm = get_llm(doc.company)
    if not llm or remaining(doc.company, USAGE_AI) <= 0:
        _save(doc, rule_brief(profile), method="rules", sources=sources, providers=sorted(providers),
              requests=requests)
        return
    reserve(doc.company, USAGE_AI, 1, doc)
    frappe.db.commit()
    pages = "\n\n".join(evidence)[:EVIDENCE_CHARS_TOTAL]
    try:
        data = llm.complete_json(
            MARKET_SYSTEM,
            untrusted("seller business profile", profile_prompt(profile)) + "\n"
            + untrusted("web pages about the market", pages),
            MARKET_SCHEMA,
            max_tokens=8000,
        )
    except LLMError as exc:
        brief = rule_brief(profile)
        brief["unknowns"].insert(0, f"AI analysis failed: {exc}")
        _save(doc, brief, method="rules", sources=sources, providers=sorted(providers), requests=requests)
        return
    brief = clean_brief(data, set(sources))
    if not brief["segments"]:
        fallback = rule_brief(profile)
        brief["segments"] = fallback["segments"]
        brief["unknowns"].insert(0, "The AI proposed no usable segment; these come from your profile.")
    _save(doc, brief, method="ai", sources=sources, providers=sorted(providers), requests=requests, model=llm.model)


def _save(doc, brief: dict, *, method: str, sources: list[str], providers: list[str], requests: int,
          model: str | None = None) -> None:
    doc.reload()
    doc.set("segments", [])
    for segment in brief["segments"]:
        row = {"include": 1, "segment_name": segment["segment_name"], "priority": segment["priority"],
               "fit_reason": segment["fit_reason"]}
        row.update({field: "\n".join(segment.get(field) or []) for field in SEGMENT_FIELDS})
        doc.append("segments", row)
    doc.update({
        "status": "Ready", "summary": brief["summary"], "unknowns": "\n".join(brief["unknowns"]),
        "sources": "\n".join(sources[:80]), "method": method, "model": model,
        "providers_used": ", ".join(providers), "provider_requests": requests, "researched_on": now_datetime(),
        "error": None,
    })
    doc.flags.ignore_permissions = True
    doc.save()
    log_activity(doc.company, "market_research_ready", doc, f"{len(brief['segments'])} segments ({method})",
                 actor_type="agent")
    frappe.db.commit()


def approve(doc, keep: list[str] | None = None) -> list[str]:
    """Create a Targeting Profile for each kept segment; returns their names."""
    if doc.status not in ("Ready", "Approved"):
        frappe.throw(_("The brief is not ready yet."))
    profile = frappe.get_doc(PROFILE, doc.business_profile).as_dict()
    created = []
    for row in doc.segments:
        if keep is not None:
            row.include = 1 if row.name in keep else 0
        if not row.include:
            continue
        segment = {"segment_name": row.segment_name}
        segment.update({field: [line for line in (row.get(field) or "").splitlines() if line.strip()]
                        for field in SEGMENT_FIELDS})
        values = segment_to_targeting(segment, profile)
        locations = values.pop("locations")
        target = frappe.get_doc("Sales Targeting Profile", row.targeting_profile) if row.targeting_profile \
            else frappe.get_doc({"doctype": "Sales Targeting Profile", "company": doc.company})
        target.update(values)
        target.set("locations", locations)
        target.save() if not target.is_new() else target.insert()
        row.targeting_profile = target.name
        created.append(target.name)
    if not created:
        frappe.throw(_("Keep at least one segment."))
    doc.update({"status": "Approved", "approved_by": frappe.session.user, "approved_on": now_datetime(),
                "targeting_profiles": "\n".join(created)})
    doc.save()
    log_activity(doc.company, "market_brief_approved", doc, f"{len(created)} targeting profiles")
    return created
