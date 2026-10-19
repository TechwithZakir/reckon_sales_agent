"""Whitelisted methods for the Sales Agent pages and forms.

Every method loads records through ``doc.check_permission`` (which applies the
Company isolation hooks), checks the SaaS subscription for billable or
outbound work, and records an audit event. Client-supplied Company, score,
approval or quota values are never trusted.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from reckon_sales_agent.constants import APPROVER_ROLES, SAAS_ROLES
from reckon_sales_agent.tenant import current_company, get_tenant_doc
from reckon_sales_agent.usage import assert_entitled, log_activity, usage_summary


def _require_approver() -> None:
    if frappe.session.user == "Administrator":
        return
    if not set(frappe.get_roles()) & APPROVER_ROLES:
        frappe.throw(_("Only Sales Agent admins and managers can do this."), frappe.PermissionError)


def _names(value) -> list[str]:
    if isinstance(value, str):
        value = json.loads(value) if value.strip().startswith("[") else [value]
    if not isinstance(value, list) or len(value) > 200:
        frappe.throw(_("Pass a list of up to 200 records."))
    return [str(v) for v in value]


@frappe.whitelist()
def check_app_permission() -> bool:
    user = frappe.session.user
    if user == "Guest":
        return False
    if user == "Administrator":
        return True
    return bool(set(frappe.get_roles(user)) & {*SAAS_ROLES, "System Manager", "Reckon Vendor Superuser"})


# Discovery -----------------------------------------------------------------


@frappe.whitelist()
def preview_plan(campaign: str) -> list[dict]:
    from reckon_sales_agent.discovery.runner import build_plan

    doc = get_tenant_doc("Sales Discovery Campaign", campaign, "write")
    if doc.status == "Running":
        frappe.throw(_("The campaign is running."))
    build_plan(doc)
    doc.save()
    doc.db_set("status", "Planned")  # status is server-managed; save() keeps the stored value
    return [row.as_dict() for row in doc.planned_queries]


@frappe.whitelist()
def start_discovery(campaign: str) -> str:
    from reckon_sales_agent.jobs import enqueue_discovery

    doc = get_tenant_doc("Sales Discovery Campaign", campaign, "write")
    assert_entitled(doc.company)
    return enqueue_discovery(doc)


@frappe.whitelist()
def cancel_job(job: str) -> None:
    doc = get_tenant_doc("Sales Discovery Job", job, "read")
    _require_approver()
    if doc.status == "Queued":
        doc.db_set({"status": "Cancelled", "cancel_requested": 1, "finished_at": now_datetime()})
    elif doc.status == "Running":
        doc.db_set("cancel_requested", 1)
    log_activity(doc.company, "job_cancel_requested", doc)


@frappe.whitelist()
def check_connector(connector: str) -> dict:
    from reckon_sales_agent.connectors.base import ConnectorError
    from reckon_sales_agent.connectors.registry import build_connector

    doc = get_tenant_doc("Sales Source Connector", connector, "write")
    try:
        instance = build_connector(doc)
        instance.validate_configuration()
        status, error = "OK", None
    except ConnectorError as exc:
        status, error = "Not ready", str(exc)
    doc.db_set({"last_health_status": f"{status} · {now_datetime():%Y-%m-%d %H:%M}", "last_error": error})
    return {"status": status, "error": error}


# Prospects -----------------------------------------------------------------


@frappe.whitelist()
def research(prospects) -> int:
    from reckon_sales_agent.jobs import enqueue_research

    names = _names(prospects)
    company = None
    for name in names:
        doc = get_tenant_doc("Sales Prospect", name, "write")
        company = company or doc.company
        if doc.company != company:
            frappe.throw(_("Prospects belong to different Companies."), frappe.PermissionError)
    if company:
        assert_entitled(company)
        enqueue_research(company, names)
    return len(names)


@frappe.whitelist()
def qualify(prospect: str) -> str:
    from reckon_sales_agent.qualification.service import qualify_prospect

    doc = get_tenant_doc("Sales Prospect", prospect, "write")
    return qualify_prospect(doc.name)


@frappe.whitelist()
def review_prospects(prospects, action: str, notes: str | None = None, merge_into: str | None = None) -> int:
    from reckon_sales_agent.crm_sync import review

    names = _names(prospects)
    for name in names:
        review(get_tenant_doc("Sales Prospect", name, "write"), action, notes, merge_into)
    return len(names)


@frappe.whitelist()
def sync_prospect(prospect: str) -> str | None:
    from reckon_sales_agent.crm_sync import sync_to_crm

    return sync_to_crm(get_tenant_doc("Sales Prospect", prospect, "write"))


@frappe.whitelist()
def override_qualification(qualification: str, result: str, reason: str) -> None:
    _require_approver()
    if result not in ("Qualified", "Not Qualified", ""):
        frappe.throw(_("Choose Qualified or Not Qualified."))
    if result and not (reason or "").strip():
        frappe.throw(_("Give a reason for the override."))
    doc = get_tenant_doc("Sales Qualification", qualification, "write")
    doc.db_set({"override_result": result or None, "override_reason": reason, "overridden_by": frappe.session.user})
    prospect = frappe.get_doc("Sales Prospect", doc.prospect)
    prospect.db_set("qualification_status", result or doc.result)
    log_activity(doc.company, "qualification_overridden", doc, f"{result}: {reason}")


@frappe.whitelist()
def review_queue(status: str = "Pending", qualification: str | None = None, start: int = 0) -> list[dict]:
    filters = {"review_status": status}
    if qualification:
        filters["qualification_status"] = qualification
    return frappe.get_list(
        "Sales Prospect",
        filters=filters,
        fields=["name", "business_name", "industry", "city", "website", "email", "phone", "fit_score",
                "ai_fit_score", "deal_probability",
                "buying_signal_score", "evidence_confidence", "qualification_status", "research_status",
                "possible_duplicate_of", "contactability", "latest_research", "source_type"],
        order_by="deal_probability desc, fit_score desc, creation desc",
        start=int(start or 0),
        page_length=50,
    )


# Campaigns -----------------------------------------------------------------


@frappe.whitelist()
def submit_campaign(campaign: str) -> None:
    doc = get_tenant_doc("Sales Campaign", campaign, "write")
    if doc.status not in ("Draft", "Paused"):
        frappe.throw(_("Only draft or paused campaigns can be submitted."))
    doc.db_set("status", "Pending Approval")
    log_activity(doc.company, "campaign_submitted", doc)


@frappe.whitelist()
def approve_campaign(campaign: str) -> int:
    from reckon_sales_agent.campaigns.engine import build_members

    _require_approver()
    doc = get_tenant_doc("Sales Campaign", campaign, "write")
    if doc.status not in ("Pending Approval", "Paused", "Approved"):
        frappe.throw(_("Submit the campaign for approval first."))
    assert_entitled(doc.company)
    doc.db_set({"status": "Active", "approved_by": frappe.session.user, "approved_on": now_datetime()})
    added = build_members(doc)
    log_activity(doc.company, "campaign_approved", doc, f"{added} members added")
    return added


@frappe.whitelist()
def pause_campaign(campaign: str) -> None:
    doc = get_tenant_doc("Sales Campaign", campaign, "write")
    doc.db_set("status", "Paused")
    log_activity(doc.company, "campaign_paused", doc)


@frappe.whitelist()
def refresh_members(campaign: str) -> int:
    from reckon_sales_agent.campaigns.engine import build_members

    doc = get_tenant_doc("Sales Campaign", campaign, "write")
    if doc.status != "Active":
        frappe.throw(_("Only active campaigns take new members."))
    return build_members(doc)


@frappe.whitelist()
def draft_now(campaign: str) -> int:
    from reckon_sales_agent.campaigns.engine import draft_due_messages

    doc = get_tenant_doc("Sales Campaign", campaign, "write")
    if doc.status != "Active":
        frappe.throw(_("Approve the campaign first."))
    assert_entitled(doc.company)
    return draft_due_messages(doc)


@frappe.whitelist()
def approve_messages(messages) -> int:
    from reckon_sales_agent.campaigns.engine import approve_message

    _require_approver()
    names = _names(messages)
    for name in names:
        doc = get_tenant_doc("Sales Outreach Message", name, "write")
        approve_message(doc)
        log_activity(doc.company, "message_approved", doc)
    return len(names)


@frappe.whitelist()
def send_approved() -> int:
    from reckon_sales_agent.campaigns.engine import send_due_messages

    _require_approver()
    company = current_company()
    assert_entitled(company)
    return send_due_messages(company)


@frappe.whitelist()
def stop_member(member: str, reason: str = "manual stop") -> None:
    from reckon_sales_agent.campaigns.engine import stop_member as stop

    doc = get_tenant_doc("Sales Campaign Member", member, "read")
    _require_approver()
    stop(doc, reason[:140])
    log_activity(doc.company, "member_stopped", doc, reason)


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def unsubscribe(token: str | None = None) -> None:
    """GET shows a confirmation button; only the POST unsubscribes.

    Mail security scanners prefetch links, so a GET must not change anything.
    """
    from frappe.utils import escape_html

    from reckon_sales_agent.campaigns.engine import unsubscribe_member

    valid = bool(token) and len(token) <= 64 and token.isalnum() and frappe.db.exists(
        "Sales Campaign Member", {"unsubscribe_token": token})
    if not valid:
        frappe.respond_as_web_page(_("Link not valid"),
                                   _("This unsubscribe link is not valid."), indicator_color="orange")
        return
    if frappe.request and frappe.request.method == "POST":
        unsubscribe_member(token)
        frappe.db.commit()
        frappe.respond_as_web_page(_("Unsubscribed"),
                                   _("You will not receive further emails from this sender."),
                                   indicator_color="green")
        return
    frappe.respond_as_web_page(
        _("Unsubscribe"),
        f'<form method="post" action="/api/method/reckon_sales_agent.api.unsubscribe">'
        f'<input type="hidden" name="token" value="{escape_html(token)}">'
        f'<p>{escape_html(_("Stop receiving emails from this sender?"))}</p>'
        f'<button class="btn btn-primary" type="submit">{escape_html(_("Unsubscribe"))}</button></form>',
        indicator_color="blue",
    )


# Targeting master and analytics ---------------------------------------------


@frappe.whitelist()
def suggest_targeting(profile: str) -> dict | None:
    """Ask Claude for keywords, Bangla variants, segments and exclusions (stored, not applied)."""
    from reckon_sales_agent.discovery.ai_planner import suggest

    doc = get_tenant_doc("Sales Targeting Profile", profile, "write")
    assert_entitled(doc.company)
    result = suggest(doc)
    log_activity(doc.company, "targeting_suggested", doc)
    return result


@frappe.whitelist()
def apply_targeting_suggestions(profile: str) -> None:
    """Merge the stored AI suggestions into the profile's fields."""
    from reckon_sales_agent.discovery.targeting import merge_lines

    doc = get_tenant_doc("Sales Targeting Profile", profile, "write")
    suggestions = json.loads(doc.ai_suggestions or "{}")
    if not suggestions:
        frappe.throw(_("Ask for AI suggestions first."))
    doc.keywords = merge_lines(doc.keywords, (suggestions.get("keywords") or []) + (suggestions.get("bangla_keywords") or []))
    doc.b2b_segments = merge_lines(doc.b2b_segments, suggestions.get("b2b_segments") or [])
    doc.industries = merge_lines(doc.industries, suggestions.get("industries") or [])
    doc.exclude_keywords = merge_lines(doc.exclude_keywords, suggestions.get("exclude_keywords") or [])
    doc.save()
    log_activity(doc.company, "targeting_applied", doc)


@frappe.whitelist()
def preview_targeting(profile: str, target_count: int = 100, per_query_limit: int = 20) -> list[dict]:
    from reckon_sales_agent.discovery.targeting import plan_from_profile
    from reckon_sales_agent.usage import get_settings

    doc = get_tenant_doc("Sales Targeting Profile", profile, "read")
    plan = plan_from_profile(doc.as_dict(), int(target_count), int(per_query_limit),
                             get_settings(doc.company).max_results_per_job or 100)
    return [{"query_text": p.query_text, "max_results": p.max_results} for p in plan]


@frappe.whitelist()
def analyze_campaign(campaign: str) -> str:
    from reckon_sales_agent.campaigns.analytics import analyze_campaign as analyze

    doc = get_tenant_doc("Sales Campaign", campaign, "write")
    return analyze(doc)


@frappe.whitelist()
def campaign_analytics() -> list[dict]:
    """Metrics for the Company's campaigns, with the latest insight text."""
    from reckon_sales_agent.campaigns.analytics import campaign_metrics

    rows = []
    for campaign in frappe.get_list("Sales Campaign", fields=["name", "campaign_name", "status", "latest_insight"],
                                    order_by="modified desc", page_length=20):
        insight = frappe.db.get_value("Sales Campaign Insight", campaign.latest_insight,
                                      ["summary", "recommendations", "generated_on"], as_dict=True) \
            if campaign.latest_insight else None
        rows.append({**campaign, "metrics": campaign_metrics(campaign.name), "insight": insight})
    return rows


# Dashboard -----------------------------------------------------------------


@frappe.whitelist()
def dashboard() -> dict:
    company = current_company()

    def count(doctype, **filters):
        return frappe.db.count(doctype, {"company": company, **filters})

    from reckon_sales_agent.usage import get_settings

    settings = get_settings(company)
    return {
        "company": company,
        "prospects": count("Sales Prospect"),
        "pending_review": count("Sales Prospect", review_status="Pending"),
        "qualified": count("Sales Prospect", qualification_status="Qualified"),
        "in_crm": count("Sales Prospect", crm_lead=["is", "set"]),
        "running_jobs": count("Sales Discovery Job", status=["in", ["Queued", "Running"]]),
        "active_campaigns": count("Sales Campaign", status="Active"),
        "drafts_waiting": count("Sales Outreach Message", status="Draft"),
        "replies": count("Sales Communication Event", event_type="replied"),
        "outbound_enabled": bool(settings.outbound_enabled),
        "kill_switch": bool(settings.kill_switch),
        "ai_enabled": bool(settings.ai_enabled),
        "autopilot": bool(settings.auto_approve_enabled),
        "auto_approved": count("Sales Prospect", auto_approved=1),
        "positive_replies": count("Sales Communication Event", event_type=["in", ["positive_reply", "meeting_requested"]]),
        "scheduled_campaigns": count("Sales Discovery Campaign", schedule=["is", "set"]),
        "hot_prospects": frappe.get_list("Sales Prospect", filters={"company": company, "deal_probability": [">", 0]},
                                         fields=["name", "business_name", "city", "deal_probability", "fit_score",
                                                 "review_status"],
                                         order_by="deal_probability desc", page_length=8),
        "usage": usage_summary(company),
        "recent_jobs": frappe.get_list("Sales Discovery Job", filters={"company": company},
                                       fields=["name", "discovery_campaign", "status", "progress_done",
                                               "progress_total", "created_count", "modified"],
                                       order_by="modified desc", page_length=5),
    }
