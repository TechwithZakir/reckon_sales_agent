"""Analytics agent: attribution from discovery to won deals, pilot results, and optimisation advice."""

from __future__ import annotations

import json

import frappe
from frappe.utils import add_days, now_datetime, nowdate

from reckon_sales_agent.agents.analytics import AGENT_FAMILY, funnel, pilot_result, recommendations
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


def dashboard(company: str, days: int = 30, campaign: str | None = None) -> dict:
    """Everything the Campaign Analytics dashboard shows for the last ``days`` days, with the period before
    for comparison. ``campaign`` narrows outreach to one campaign and leads to its discovery campaign."""
    from reckon_sales_agent.agents.analytics import (
        CONTACT_EVENTS,
        POSITIVE_EVENTS,
        REPLY_EVENTS,
        call_summary,
        change,
        daily_buckets,
        reply_rate,
    )
    from reckon_sales_agent.agents.policy import agent_for
    from reckon_sales_agent.campaigns.calls import EVENT

    today = nowdate()
    start, prev_start = add_days(today, -(days - 1)), add_days(today, -(2 * days - 1))
    lead_filter = {"company": company}
    event_filter = {"company": company}
    if campaign:
        event_filter["campaign"] = campaign
        discovery = frappe.db.get_value("Sales Campaign", campaign, "discovery_campaign")
        lead_filter["discovery_campaign"] = discovery or "-"

    def stamps(doctype, filters, since, field="creation"):
        return frappe.get_all(doctype, filters={**filters, field: [">=", f"{since} 00:00:00"]}, pluck=field,
                              limit=100000)

    def split(values):
        """(this period, the period before) from stamps covering both."""
        current = [v for v in values if str(v)[:10] >= str(start)]
        return current, [v for v in values if str(v)[:10] < str(start)]

    leads = frappe.get_all("Sales Prospect", filters={**lead_filter, "creation": [">=", f"{prev_start} 00:00:00"]},
                           fields=["creation", "qualification_status", "crm_lead", "review_status"], limit=100000)
    events = frappe.get_all("Sales Communication Event",
                            filters={**event_filter, "event_time": [">=", f"{prev_start} 00:00:00"]},
                            fields=["event_type", "event_time", "member"], limit=200000)
    now_leads = [r for r in leads if str(r.creation)[:10] >= str(start)]
    old_leads = [r for r in leads if str(r.creation)[:10] < str(start)]

    def ev(types, rows=events):
        return [e.event_time for e in rows if e.event_type in types]

    contacted_now, contacted_old = split(ev(CONTACT_EVENTS))
    replies_now, replies_old = split(ev(REPLY_EVENTS))
    positive_now, positive_old = split(ev(POSITIVE_EVENTS))
    deals = _period_deals(company, prev_start, lead_filter)
    won = _won_statuses()
    deals_now = [d for d in deals if str(d.creation)[:10] >= str(start)]
    deals_old = [d for d in deals if str(d.creation)[:10] < str(start)]

    def members_rate(rows_from_period):
        # Share of contacted leads that replied (live: counting events gave 200%, a reply to an earlier message).
        return reply_rate([(e.event_type, e.member) for e in rows_from_period], CONTACT_EVENTS, REPLY_EVENTS)

    now_events = [e for e in events if str(e.event_time)[:10] >= str(start)]
    old_events = [e for e in events if str(e.event_time)[:10] < str(start)]

    kpis = {
        "leads": change(len(now_leads), len(old_leads)),
        "qualified": change(sum(r.qualification_status == "Qualified" for r in now_leads),
                            sum(r.qualification_status == "Qualified" for r in old_leads)),
        "in_crm": change(sum(bool(r.crm_lead) for r in now_leads), sum(bool(r.crm_lead) for r in old_leads)),
        "contacted": change(len(contacted_now), len(contacted_old)),
        "reply_rate": change(members_rate(now_events), members_rate(old_events)),
        "positive": change(len(positive_now), len(positive_old)),
        "deals": change(len(deals_now), len(deals_old)),
        "won_value": change(round(sum(d.value for d in deals_now if d.status in won), 2),
                            round(sum(d.value for d in deals_old if d.status in won), 2)),
    }
    trend = {
        "start": str(start), "days": days,
        "leads": daily_buckets([r.creation for r in now_leads], str(start), days),
        "contacted": daily_buckets(contacted_now, str(start), days),
        "replies": daily_buckets(replies_now, str(start), days),
        "positive": daily_buckets(positive_now, str(start), days),
    }
    activity = {}
    for row in frappe.get_all("Sales Agent Activity", filters={"company": company,
                                                               "creation": [">=", f"{start} 00:00:00"]},
                              fields=["agent", "creation", "action"], limit=200000):
        if row.action.startswith(("digest_", "autopilot_run")):
            continue  # reports and heartbeats, not work
        # Rows logged before the agent field existed: the action says whose work it was (live: 660 such rows
        # all showed as Governance).
        agent = row.agent or agent_for(row.action)
        activity.setdefault(AGENT_FAMILY.get(agent, agent), []).append(row.creation)
    agents = ("Research", "Content", "Governance", "Engagement", "Analytics")
    calls_now = now_events
    call_counts = {event: sum(1 for e in calls_now if e.event_type == event) for event in EVENT.values()}
    triage = frappe.get_all("Sales Prospect", filters={**lead_filter, "ai_triaged_on": [">=", f"{start} 00:00:00"]},
                            pluck="ai_triage_verdict", limit=100000)
    rows = [r for r in attribution_rows(company, days)]
    segments, sources = funnel(rows, "segment"), funnel(rows, "source")
    campaigns = frappe.get_list("Sales Campaign", filters={"name": campaign} if campaign else {},
                                fields=["name", "campaign_name", "status", "pilot_mode", "pilot_verdict",
                                        "pilot_summary", "latest_insight", "approved_on"],
                                order_by="modified desc", page_length=20)
    from reckon_sales_agent.campaigns.analytics import campaign_metrics

    return {
        "days": days, "start": str(start), "campaign": campaign,
        "kpis": kpis,
        "trend": trend,
        "activity": {"agents": agents, "series": {a: daily_buckets(activity.get(a, []), str(start), days)
                                                  for a in agents}},
        "funnel": funnel([{**r, "all": "all"} for r in rows], "all")[0] if rows else None,
        "by_segment": segments[:10], "by_source": sources[:10],
        "calls": call_summary(sum(1 for e in calls_now if e.event_type == "task_created"), call_counts),
        "call_outcomes": call_counts,
        "triage": {v: triage.count(v) for v in ("approve", "reject", "unsure")},
        "campaigns": [{**c, "metrics": campaign_metrics(c.name)} for c in campaigns],
        "campaign_options": frappe.get_list("Sales Campaign", fields=["name", "campaign_name"],
                                            order_by="modified desc", page_length=50),
        "recommendations": recommendations(segments=segments, sources=sources),
        "channels": channel_report(company, str(start)),
    }


def channel_report(company: str, start: str) -> dict:
    """Where leads talk to the Company: messages in and answered per channel, reply speed, leads and deals."""
    from frappe.utils import get_datetime

    from reckon_sales_agent.agents.analytics import SOURCE_CHANNEL, channel_table
    from reckon_sales_agent.agents.chat import median, response_minutes

    since = f"{start} 00:00:00"
    received = frappe.get_all("Sales Communication Event", filters={"company": company, "event_type": "received",
                                                                    "event_time": [">=", since]},
                              fields=["channel", "message"], limit=100000)
    message_channel = dict(frappe.get_all("Sales Outreach Message", filters={
        "name": ["in", list({r.message for r in received if r.message}) or [""]]}, fields=["name", "channel"],
        as_list=True))
    inbound = [r.channel or message_channel.get(r.message) or "Email" for r in received]
    calls = frappe.db.count("Sales Communication Event", {"company": company, "event_time": [">=", since],
                                                         "event_type": ["like", "call\\_%"]})
    inbound += ["Call"] * calls
    replies = frappe.get_all("Sales Outreach Message", filters={"company": company, "is_reply": 1,
                                                                "status": ["in", ["Sent", "Dry Run"]],
                                                                "sent_on": [">=", since]},
                             fields=["channel", "auto_approved_by_policy"], limit=100000)
    chats = frappe.get_all("Sales Chat Message", filters={"company": company, "sent_at": [">=", since]},
                           fields=["prospect", "channel", "direction", "sent_at", "kind"], order_by="sent_at asc",
                           limit=100000)
    threads: dict[tuple, list] = {}
    for row in chats:
        threads.setdefault((row.channel, row.prospect), []).append((row.direction, get_datetime(row.sent_at)))
    minutes: dict[str, list[float]] = {}
    for (channel, _prospect), rows in threads.items():
        minutes.setdefault(channel, []).extend(response_minutes(rows))
    new_leads = frappe.get_all("Sales Prospect", filters={"company": company, "creation": [">=", since],
                                                          "source_type": ["in", list(SOURCE_CHANNEL)]},
                               fields=["source_type", "crm_lead"], limit=100000)
    deals = _deals_by_lead([p.crm_lead for p in new_leads if p.crm_lead])
    all_minutes = [m for values in minutes.values() for m in values]
    return {
        "rows": channel_table(inbound, [r.channel for r in replies], minutes,
                              [SOURCE_CHANNEL[p.source_type] for p in new_leads],
                              [SOURCE_CHANNEL[p.source_type] for p in new_leads if p.crm_lead and deals.get(p.crm_lead)]),
        "chats": sum(1 for r in chats if r.direction == "In" and r.kind != "Comment"),
        "comments": sum(1 for r in chats if r.kind == "Comment"),
        "instant": sum(1 for r in replies if r.auto_approved_by_policy),
        "median_minutes": median(all_minutes),
    }


def _period_deals(company: str, since: str, lead_filter: dict) -> list:
    """CRM deals since ``since`` on leads the agents found (optionally one discovery campaign's)."""
    leads = frappe.get_all("Sales Prospect", filters={**lead_filter, "crm_lead": ["is", "set"]}, pluck="crm_lead",
                           limit=100000)
    if not leads:
        return []
    return [frappe._dict(d) for rows in _deals_by_lead(leads, since=f"{since} 00:00:00").values() for d in rows]


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
