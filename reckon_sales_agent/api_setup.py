"""Backend for the guided setup page ("Get started"): state, AI suggestions and saving, step by step.

Every write goes through the same checked paths as the rest of the app (business profile, market research,
knowledge approval, autopilot); this module only adds the team settings and a salesperson's own details.
"""

from __future__ import annotations

import json

import frappe
from frappe import _

from reckon_sales_agent.agents.setup import progress, steps
from reckon_sales_agent.api_studio import _can_manage
from reckon_sales_agent.tenant import current_company, get_tenant_doc
from reckon_sales_agent.usage import get_settings, log_activity, platform_settings

SEEN_DAY = "sales_agent_seen_day"


def _require_manager() -> None:
    if not _can_manage():
        frappe.throw(_("Ask a Sales Agent admin or manager to do this."), frappe.PermissionError)


def _args(value) -> dict:
    if isinstance(value, str):
        value = json.loads(value or "{}")
    return value if isinstance(value, dict) else {}


@frappe.whitelist()
def status() -> dict:
    from reckon_sales_agent.providers.router import active
    from reckon_sales_agent.research.market import business_profile

    company = current_company()
    settings = get_settings(company)
    user = frappe.session.user
    me = frappe.db.get_value("User", user, ["first_name", "last_name", "mobile_no", "full_name"], as_dict=True) or {}
    profile = business_profile(company, create=False)
    brief = frappe.get_doc("Sales Market Brief", profile.latest_brief) if profile and profile.latest_brief else None
    connector = frappe.db.get_value("Sales Source Connector", {"company": company, "connector_type": "multi_source"},
                                    ["enabled", "policy_reviewed"], as_dict=True) or {}
    facts = frappe.get_all("Sales Knowledge Item", filters={"company": company, "status": ["!=", "Retired"]},
                           fields=["name", "title", "category", "status", "content", "source_url"],
                           order_by="creation asc", limit=30)
    qualify = frappe.db.get_value("Sales Qualification Profile", {"company": company}, "qualify_threshold",
                                  order_by="creation asc") or 60
    providers = {cap: active(cap) for cap in ("places", "page_context", "web_search")}
    state = {
        "has_profile": bool(profile and (profile.what_we_sell or profile.products)),
        "brief_status": brief.status if brief else None,
        "facts_approved": sum(1 for f in facts if f.status == "Approved"),
        "sender_name": settings.sender_name, "physical_address": settings.physical_address,
        "sources_ready": any(providers.values()),
        "connector_ready": bool(connector.get("enabled") and connector.get("policy_reviewed")),
        "autopilot": bool(settings.get("autopilot_enabled")),
        "my_name": me.get("first_name"), "my_phone": me.get("mobile_no"),
        "seen_day": bool(frappe.defaults.get_user_default(SEEN_DAY)),
    }
    seller = not _can_manage()
    rows = steps(state, seller=seller)
    return {
        "company": company, "seller": seller, "steps": rows, "progress": progress(rows),
        "me": me,
        "profile": {f: (profile.get(f) if profile else "") or "" for f in (
            "business_name", "website", "what_we_sell", "products", "problems_solved", "target_industries",
            "business_types", "regions", "competitors", "onboarding_status")},
        "brief": {"name": brief.name, "status": brief.status, "summary": brief.summary, "error": brief.error,
                  "segments": [{"name": r.name, "segment_name": r.segment_name, "priority": r.priority,
                                "fit_reason": r.fit_reason, "include": r.include,
                                "keywords": (r.keywords or "").splitlines()[:6]} for r in brief.segments]}
        if brief else None,
        "facts": facts,
        "team": {
            "sender_name": settings.sender_name or "", "physical_address": settings.physical_address or "",
            "task_assignee": settings.get("task_assignee") or "", "digest_recipients": settings.get("digest_recipients") or "",
            # Live: "Administrator" was suggested as the email signature; a real person's name reads better.
            "suggested_sender": (f"{me.get('full_name')} from {company}"
                                 if me.get("full_name") and user != "Administrator" else f"{company} sales team"),
            "suggested_address": _company_address(company),
            "users": _company_users(company),
        },
        "sources": {"providers": providers, "connector_ready": state["connector_ready"]},
        "autopilot": {"enabled": state["autopilot"], "suggested": {
            "weekly_leads": settings.get("autopilot_weekly_leads") or 50, "min_fit": float(qualify),
            "min_prospects": settings.get("autopilot_campaign_min_prospects") or 5, "ai_triage": 1, "daily_digest": 1}},
        "ai": bool(platform_settings().get("ai_enabled") and settings.ai_enabled),
    }


def _company_address(company: str) -> str:
    """The Company's address in Desk, as one line (a suggestion for the email footer)."""
    name = frappe.db.get_value("Dynamic Link", {"link_doctype": "Company", "link_name": company,
                                                "parenttype": "Address"}, "parent")
    if not name:
        return ""
    row = frappe.db.get_value("Address", name, ["address_line1", "address_line2", "city", "country"], as_dict=True)
    return ", ".join(v for v in (row.address_line1, row.address_line2, row.city, row.country) if v) if row else ""


def _company_users(company: str) -> list[dict]:
    if not frappe.db.exists("DocType", "Tenant User Assignment"):
        return []
    users = frappe.get_all("Tenant User Assignment", filters={"company": company, "active": 1},
                           fields=["user", "role_profile"], limit=200)
    names = {u.name: u.full_name for u in frappe.get_all("User", filters={"name": ["in", [u.user for u in users] or [""]],
                                                                         "enabled": 1}, fields=["name", "full_name"])}
    return [{"user": u.user, "name": names[u.user], "role": u.role_profile} for u in users if u.user in names]


@frappe.whitelist()
def draft_facts() -> int:
    from reckon_sales_agent.agents.setup import draft_facts as draft

    _require_manager()
    return draft(current_company())


@frappe.whitelist()
def approve_facts(names) -> int:
    from reckon_sales_agent import api

    return api.approve_knowledge(names)


@frappe.whitelist()
def choose_segments(brief: str, keep) -> list[str]:
    from reckon_sales_agent.research.market import approve

    _require_manager()
    keep = json.loads(keep) if isinstance(keep, str) else keep
    if not keep:
        frappe.throw(_("Keep at least one segment."))
    return approve(get_tenant_doc("Sales Market Brief", brief, "write"), [str(k) for k in keep])


@frappe.whitelist()
def save_team(data) -> None:
    _require_manager()
    data = _args(data)
    company = current_company()
    settings = get_settings(company)
    settings.sender_name = " ".join(str(data.get("sender_name") or "").split())[:140] or None
    settings.physical_address = str(data.get("physical_address") or "").strip()[:500] or None
    assignee = str(data.get("task_assignee") or "").strip()
    if assignee and not frappe.db.get_value("User", assignee, "enabled"):
        frappe.throw(_("No active user {0}.").format(frappe.utils.escape_html(assignee)))
    settings.task_assignee = assignee or None
    settings.digest_recipients = "\n".join(line.strip() for line in str(data.get("digest_recipients") or "")
                                           .replace(",", "\n").splitlines() if line.strip())[:2000] or None
    settings.save()
    log_activity(company, "setup_team_saved", settings, agent="Governance")


@frappe.whitelist()
def use_smart_sources() -> str:
    from reckon_sales_agent.agents.orchestrator import smart_sources

    _require_manager()
    company = current_company()
    name = smart_sources(company)
    log_activity(company, "connector_setup", frappe.get_doc("Sales Source Connector", name),
                 "Smart Sources confirmed in setup")
    return name


@frappe.whitelist()
def save_me(data) -> None:
    """A salesperson's own name and phone (used in call scripts and the CRM)."""
    data = _args(data)
    user = frappe.session.user
    if user in ("Guest", "Administrator"):
        frappe.throw(_("Sign in with your own account to set your details."))
    first = " ".join(str(data.get("first_name") or "").split())[:80]
    if not first:
        frappe.throw(_("Your first name is needed for the call scripts."))
    frappe.db.set_value("User", user, {"first_name": first,
                                       "last_name": " ".join(str(data.get("last_name") or "").split())[:80] or None,
                                       "mobile_no": " ".join(str(data.get("mobile_no") or "").split())[:20] or None})


@frappe.whitelist()
def seen_day() -> None:
    frappe.defaults.set_user_default(SEEN_DAY, "1")
