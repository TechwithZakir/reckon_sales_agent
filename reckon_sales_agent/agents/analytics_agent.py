"""Analytics agent: attribution from discovery to won deals, pilot results, and optimisation advice."""

from __future__ import annotations

import json

import frappe
from frappe.utils import add_days, now_datetime, nowdate

from reckon_sales_agent.agents.analytics import funnel, pilot_result, recommendations
from reckon_sales_agent.campaigns.replies import POSITIVE
from reckon_sales_agent.usage import log_activity

NOT_TREATED = ("Holdout", "Ineligible", "Eligible")
NOT_A_REPLY = ("out_of_office", "irrelevant", None, "")


def _won_statuses() -> set[str]:
    if frappe.db.has_column("CRM Deal Status", "type"):
        names = frappe.get_all("CRM Deal Status", filters={"type": "Won"}, pluck="name")
        if names:
            return set(names)
    return {"Won"}


def _deals_by_lead(leads: list[str], since=None) -> dict[str, list[dict]]:
    if not leads or not frappe.db.table_exists("CRM Deal"):
        return {}
    value_field = next((f for f in ("deal_value", "annual_revenue") if frappe.db.has_column("CRM Deal", f)), None)
    fields = ["name", "lead", "status", "creation"] + ([value_field] if value_field else [])
    filters = {"lead": ["in", leads]}
    if since:
        filters["creation"] = [">=", since]
    out: dict[str, list[dict]] = {}
    for deal in frappe.get_all("CRM Deal", filters=filters, fields=fields, limit=50000):
        deal["value"] = float(deal.get(value_field) or 0) if value_field else 0.0
        out.setdefault(deal.lead, []).append(deal)
    return out


def attribution_rows(company: str, days: int = 180) -> list[dict]:
    """One row per prospect discovered in the window, with funnel stage flags and won value."""
    prospects = frappe.get_all("Sales Prospect", filters={"company": company, "creation": [">=", add_days(nowdate(), -days)]},
                               fields=["name", "discovery_campaign", "source_type", "review_status", "crm_lead"],
                               limit=20000)
    if not prospects:
        return []
    discovery = {d.name: d.targeting_profile for d in frappe.get_all(
        "Sales Discovery Campaign", filters={"company": company}, fields=["name", "targeting_profile"], limit=5000)}
    profiles = {p.name: p.profile_name for p in frappe.get_all(
        "Sales Targeting Profile", filters={"company": company}, fields=["name", "profile_name"], limit=5000)}
    campaigns = {c.name: c.campaign_name for c in frappe.get_all(
        "Sales Campaign", filters={"company": company}, fields=["name", "campaign_name"], limit=5000)}
    members: dict[str, list[dict]] = {}
    for member in frappe.get_all("Sales Campaign Member", filters={"company": company},
                                 fields=["prospect", "campaign", "status", "sequence_position", "reply_classification",
                                         "modified"], order_by="modified asc", limit=50000):
        members.setdefault(member.prospect, []).append(member)
    deals = _deals_by_lead([p.crm_lead for p in prospects if p.crm_lead])
    won = _won_statuses()
    rows = []
    for p in prospects:
        mine = members.get(p.name, [])
        treated = [m for m in mine if m.status not in NOT_TREATED]
        classes = {m.reply_classification for m in treated} - set(NOT_A_REPLY)
        lead_deals = deals.get(p.crm_lead, []) if p.crm_lead else []
        won_deals = [d for d in lead_deals if d.status in won]
        rows.append({
            "segment": profiles.get(discovery.get(p.discovery_campaign)) or "(no segment)",
            "source": p.source_type or "(unknown)",
            "campaign": campaigns.get(mine[-1].campaign) if mine else "(not in a campaign)",
            "approved": p.review_status == "Approved",
            "in_crm": bool(p.crm_lead),
            "contacted": any(m.status in ("Completed", "Stopped", "Converted") or (m.sequence_position or 0) > 0
                             for m in treated),
            "replied": bool(classes),
            "positive": bool(classes & set(POSITIVE)),
            "meetings": "meeting_request" in classes,
            "deals": bool(lead_deals),
            "won": bool(won_deals),
            "won_value": sum(d.value for d in won_deals),
        })
    return rows


def overview(company: str, days: int = 180) -> dict:
    rows = attribution_rows(company, days)
    segments, sources = funnel(rows, "segment"), funnel(rows, "source")
    return {
        "days": days,
        "totals": funnel([{**r, "all": "all"} for r in rows], "all")[0] if rows else None,
        "by_segment": segments,
        "by_source": sources,
        "by_campaign": funnel(rows, "campaign"),
        "recommendations": recommendations(segments=segments, sources=sources),
    }


def pilot_report(campaign) -> dict:
    """Contacted versus hold-out conversion for a pilot campaign; stored on the campaign."""
    members = frappe.get_all("Sales Campaign Member", filters={"campaign": campaign.name},
                             fields=["prospect", "status", "crm_lead", "converted_on"], limit=50000)
    leads = {m.prospect: m.crm_lead or frappe.db.get_value("Sales Prospect", m.prospect, "crm_lead") for m in members}
    deals = _deals_by_lead([lead for lead in leads.values() if lead], since=campaign.approved_on)

    def converted(member) -> bool:
        return bool(member.converted_on) or bool(leads.get(member.prospect) and deals.get(leads[member.prospect]))

    treated = [m for m in members if m.status not in NOT_TREATED]
    holdout = [m for m in members if m.status == "Holdout"]
    result = pilot_result(len(treated), sum(converted(m) for m in treated), len(holdout), sum(converted(m) for m in holdout))
    summary = (f"Contacted {result['treated']} ({result['treated_rate']}% converted) vs hold-out {result['holdout']} "
               f"({result['holdout_rate']}%): lift {result['lift_points']} points, z={result['z']}. {result['why']}")
    from reckon_sales_agent.agents.analytics import call_summary
    from reckon_sales_agent.campaigns.calls import EVENT

    # Frappe 16 rejects SQL functions in ``fields``: one count per outcome.
    calls = call_summary(
        frappe.db.count("Sales Outreach Message", {"campaign": campaign.name, "channel": "Call Task", "status": "Sent"}),
        {event: frappe.db.count("Sales Communication Event", {"campaign": campaign.name, "event_type": event})
         for event in EVENT.values()})
    if calls["calls"]:
        summary += (f" Calls: {calls['calls']} assigned, {calls['logged']} logged, {calls['reached']} reached "
                    f"({calls['reach_rate']}%), {calls['interested']} interested ({calls['interest_rate']}% of reached).")
    campaign.db_set({"pilot_verdict": result["verdict"], "pilot_summary": summary[:1000],
                     "pilot_checked_on": now_datetime()}, update_modified=False)
    log_activity(campaign.company, "pilot_measured", campaign, summary, actor_type="agent", agent="Analytics",
                 policy_outcome="recommendation only" if result["verdict"] == "scale" else None)
    return {**result, "summary": summary, "campaign": campaign.name, "calls": calls}


def metrics_tips(metrics: dict) -> list[str]:
    return recommendations(metrics=metrics)


def as_json(data) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)
