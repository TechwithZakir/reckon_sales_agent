"""Backend for the Campaign Studio page: overview, campaigns, audiences, recipients, copilot and autopilot.

Anyone who can see the Company's campaigns can read here. Changing an audience, creating a campaign or switching the
autopilot needs a Sales Agent manager. Approving a campaign stays with the existing approval endpoints (api.py), so a
person is always the one who launches it. Everything is limited to the session's Company.
"""

from __future__ import annotations

import json
import re

import frappe
from frappe import _
from frappe.utils import add_days, nowdate

from reckon_sales_agent.api_studio import _can_manage
from reckon_sales_agent.campaigns import audience as audience_rules
from reckon_sales_agent.campaigns import autopilot, builder, copilot, timeline, variants
from reckon_sales_agent.campaigns.audience_resolve import preview as resolve_preview
from reckon_sales_agent.campaigns.audience_resolve import refresh as refresh_size
from reckon_sales_agent.campaigns.metrics import funnel, rate
from reckon_sales_agent.campaigns.people import by_person as _by_person
from reckon_sales_agent.campaigns.people import events as _events
from reckon_sales_agent.campaigns.people import hot_people as _hot_people
from reckon_sales_agent.tenant import current_company, get_tenant_doc
from reckon_sales_agent.usage import assert_entitled, get_settings, log_activity

TOP = 10
AUDIENCE_FIELDS = ("audience_name", "audience_type", "description", "status_filter", "source_filter", "owner_filter",
                   "city_filter", "industry_filter", "minimum_fit_score", "require_email", "require_phone",
                   "sms_opt_in", "whatsapp_opt_in", "opt_in_source")
MEMBER_FIELDS = ("reference_doctype", "reference_name", "person_name", "email", "phone")


def _require_manager() -> None:
    if not _can_manage():
        frappe.throw(_("Ask a Sales Agent admin or manager to do this."), frappe.PermissionError)


def _json(value) -> dict:
    if isinstance(value, dict):
        return value
    try:
        data = json.loads(value or "{}")
    except ValueError:
        frappe.throw(_("That request is not valid."))
    return data if isinstance(data, dict) else {}


def _audience_suggestions(company: str) -> list[dict]:
    unused = frappe.db.sql(
        """select count(*) from `tabSales Prospect` p
           where p.company = %s and p.review_status = 'Approved' and ifnull(p.do_not_contact, 0) = 0
             and (ifnull(p.email, '') != '' or ifnull(p.phone, '') != '')
             and not exists (select 1 from `tabSales Campaign Member` m where m.prospect = p.name)""", company)[0][0]
    if not unused:
        return []
    return [{"id": "unused_prospects", "severity": copilot.INFO,
             "title": f"{unused} approved prospects are not in any campaign",
             "detail": "Make an audience from them and start with a small pilot.", "action": "new_audience"}]


def _autopilot_state(settings) -> dict:
    level = autopilot.normalize_level(settings.get("campaign_autopilot"))
    return {"level": level, "levels": list(autopilot.LEVELS), "descriptions": autopilot.DESCRIPTIONS,
            "window": settings.get("campaign_send_window") or "", "track_opens": bool(settings.get("track_opens")),
            "track_clicks": bool(settings.get("track_clicks")), "outbound_enabled": bool(settings.get("outbound_enabled")),
            "approval_required": bool(settings.get("human_approval_required"))}


# Overview and campaigns ----------------------------------------------------


@frappe.whitelist()
def overview() -> dict:
    company = current_company()
    assert_entitled(company)
    settings = get_settings(company)
    events = _events(company, since=add_days(nowdate(), -30))
    engagement = funnel(events)
    statuses = {r.status: r.n for r in frappe.db.sql(
        "select status, count(*) as n from `tabSales Campaign` where company = %s group by status", company, as_dict=True)}
    context = {"hot_recipients": len(_hot_people(events)), "outbound_enabled": bool(settings.get("outbound_enabled")),
               "campaign_new": True}
    suggestions = copilot.suggest({"engagement": engagement}, context) + _audience_suggestions(company)
    return {
        "company": company, "can_manage": _can_manage(), "campaign_statuses": statuses, "engagement": engagement,
        "suggestions": suggestions[:6], "autopilot": _autopilot_state(settings),
        "audiences": frappe.db.count("Sales Audience", {"company": company}),
        "pending_approval": frappe.db.count("Sales Outreach Message", {"company": company, "status": "Draft"}),
    }


@frappe.whitelist()
def campaigns() -> list[dict]:
    company = current_company()
    assert_entitled(company)
    fields = ["name", "campaign_name", "status", "audience", "language", "member_count", "sent_count", "open_count",
              "click_count", "reply_count", "positive_reply_count", "bounce_count", "unsubscribe_count", "meeting_count",
              "converted_count", "content_status", "start_date", "modified"]
    rows = frappe.get_all("Sales Campaign", filters={"company": company}, fields=fields, order_by="modified desc", limit=200)
    channels: dict[str, set] = {}
    if rows:
        for step in frappe.get_all("Sales Campaign Step", filters={"parenttype": "Sales Campaign",
                                                                 "parent": ["in", [r.name for r in rows]]},
                                   fields=["parent", "channel"]):
            channels.setdefault(step.parent, set()).add(step.channel or "Email")
    audiences = {r.name: r.audience_name for r in frappe.get_all(
        "Sales Audience", filters={"company": company}, fields=["name", "audience_name"], limit=500)}
    # A reply can be two events (a reply, then its classification), so count the messages that were answered.
    replied = {r.campaign: r.n for r in frappe.db.sql(
        """select campaign, count(distinct message) as n from `tabSales Communication Event`
           where company = %s and event_type in ('replied', 'positive_reply', 'meeting_requested') group by campaign""",
        company, as_dict=True)}
    for row in rows:
        sent = row.sent_count or 0
        row.update({"channels": sorted(channels.get(row.name, [])), "audience_name": audiences.get(row.audience, ""),
                    "replied": replied.get(row.name, 0),
                    "open_rate": rate(row.open_count or 0, sent), "click_rate": rate(row.click_count or 0, sent),
                    "reply_rate": min(rate(replied.get(row.name, 0), sent), 100.0),
                    "bounce_rate": rate(row.bounce_count or 0, sent)})
    return rows


def _sms_parts(doc) -> int:
    parts = 0
    for step in doc.steps:
        if (step.channel or "Email") == "SMS":
            text = re.sub(r"<[^>]+>", " ", step.body_template or "")
            parts = max(parts, builder.sms_parts(" ".join(text.split())))
    return parts


@frappe.whitelist()
def campaign(name: str) -> dict:
    doc = get_tenant_doc("Sales Campaign", name, "read")
    from reckon_sales_agent.campaigns.analytics import campaign_metrics

    settings = get_settings(doc.company)
    metrics = campaign_metrics(doc.name)
    events = _events(doc.company, campaign=doc.name)
    people = _by_person(events)
    ranked = sorted(((timeline.summarize_person(rows), prospect) for prospect, rows in people.items()),
                    key=lambda item: -item[0]["score"])
    top = ranked[:TOP]
    details = {r.name: r for r in frappe.get_all(
        "Sales Prospect", filters={"name": ["in", [prospect for _summary, prospect in top]]},
        fields=["name", "business_name", "email", "phone"])} if top else {}
    unreached = frappe.db.count("Sales Campaign Member", {"campaign": doc.name, "status": "Ineligible"})
    context = {"hot_recipients": sum(1 for summary, _p in ranked if summary["temperature"] == "Hot"),
               "outbound_enabled": bool(settings.get("outbound_enabled")), "sms_parts": _sms_parts(doc),
               "unreached": unreached, "campaign_new": doc.status in ("Draft", "Pending Approval")}
    links = frappe.db.sql(
        """select url, sum(hits) as clicks, sum(case when hits > 0 then 1 else 0 end) as people
           from `tabSales Tracked Link` where campaign = %s and kind = 'click' group by url order by clicks desc limit 10""",
        doc.name, as_dict=True)
    return {
        "name": doc.name, "campaign_name": doc.campaign_name, "status": doc.status, "audience": doc.get("audience"),
        "offer": doc.offer, "language": doc.language, "content_status": doc.content_status,
        "content_issues": doc.content_issues, "metrics": metrics, "suggestions": copilot.suggest(metrics, context),
        "top_links": links, "unreached": unreached,
        "top_recipients": [{**details.get(p, {"name": p}), **summary, "prospect": p} for summary, p in top
                           if summary["score"] > 0],
        "steps": [{"step_no": s.step_no, "channel": s.channel, "delay_days": s.delay_days, "subject": s.subject_template,
                   "template": s.get("message_template"), "variants": variants.parse(s.get("subject_variants"))}
                  for s in doc.steps],
    }


@frappe.whitelist()
def templates() -> list[dict]:
    """Approved templates a campaign step can use."""
    company = current_company()
    return frappe.get_all("Sales Message Template", filters={"company": company, "status": "Approved"},
                          fields=["name", "template_name", "channel", "language", "subject"], order_by="modified desc",
                          limit=200)


@frappe.whitelist(methods=["POST"])
def create_campaign(data) -> str:
    """A draft campaign from an audience and approved templates. A person submits and approves it afterwards."""
    _require_manager()
    company = current_company()
    assert_entitled(company)
    values = _json(data)
    steps = [s for s in values.get("steps") or [] if isinstance(s, dict) and s.get("template")]
    if not steps:
        frappe.throw(_("Add at least one step with an approved template."))
    name = " ".join(str(values.get("campaign_name") or "").split())[:140]
    if not name:
        frappe.throw(_("Give the campaign a name."))
    audience = values.get("audience") or None
    if audience:
        get_tenant_doc("Sales Audience", audience, "read")
    pilot = bool(values.get("pilot"))
    goal = values.get("goal") if values.get("goal") in ("Book a meeting", "Re-engage", "Upsell", "Event invite") else None
    doc = frappe.get_doc({
        "doctype": "Sales Campaign", "company": company, "campaign_name": name, "audience": audience, "goal": goal,
        "offer": str(values.get("offer") or "")[:500],
        "language": values.get("language") if values.get("language") in ("English", "Bangla") else "English",
        "daily_limit": int(values.get("daily_limit") or 50), "status": "Draft",
        "start_date": values.get("start_date") or None,
        "pilot_mode": 1 if pilot else 0,
        "pilot_max_members": max(1, min(int(values.get("pilot_max") or 50), 1000)) if pilot else 0,
        "holdout_percent": max(0, min(int(values.get("holdout") or 20), 50)) if pilot else 0,
        "steps": [{"step_no": i, "message_template": s["template"], "delay_days": int(s.get("delay_days") or 0)}
                  for i, s in enumerate(steps, start=1)],
    })
    doc.insert()  # the template's exact wording is copied in on validate
    log_activity(company, "campaign_created", doc, f"{len(steps)} steps")
    if values.get("submit"):
        from reckon_sales_agent.api import submit_campaign

        submit_campaign(doc.name)  # waits for a person's approval; nothing is sent
    return doc.name


# Audiences -----------------------------------------------------------------


def _audience_from(company: str, data: dict):
    kind = data.get("audience_type") or audience_rules.PROSPECTS
    if kind not in audience_rules.AUDIENCE_TYPES:
        frappe.throw(_("Choose who the audience is made of."))
    members = [frappe._dict({k: row.get(k) for k in MEMBER_FIELDS}) for row in data.get("members") or []
               if isinstance(row, dict)]
    return frappe._dict({**{k: data.get(k) for k in AUDIENCE_FIELDS}, "audience_type": kind, "company": company,
                         "members": members, "minimum_fit_score": float(data.get("minimum_fit_score") or 0)})


@frappe.whitelist()
def audiences() -> list[dict]:
    company = current_company()
    assert_entitled(company)
    rows = frappe.get_all("Sales Audience", filters={"company": company},
                          fields=["name", "audience_name", "audience_type", "description", "size", "size_email",
                                  "size_phone", "last_refreshed", "sms_opt_in", "whatsapp_opt_in"],
                          order_by="modified desc", limit=200)
    used = {r.audience: r.n for r in frappe.db.sql(
        "select audience, count(*) as n from `tabSales Campaign` where company = %s and ifnull(audience, '') != '' "
        "group by audience", company, as_dict=True)}
    for row in rows:
        row["campaigns"] = used.get(row.name, 0)
    return rows


@frappe.whitelist()
def audience(name: str) -> dict:
    doc = get_tenant_doc("Sales Audience", name, "read")
    data = {k: doc.get(k) for k in ("name", *AUDIENCE_FIELDS, "size", "size_email", "size_phone")}
    data["members"] = [{k: row.get(k) for k in MEMBER_FIELDS} for row in doc.members]
    return data


@frappe.whitelist(methods=["POST"])
def audience_preview(config) -> dict:
    """Who an audience would include right now, without saving or creating anything."""
    company = current_company()
    assert_entitled(company)
    data = _json(config)
    return resolve_preview(_audience_from(company, data), data.get("channels"))


@frappe.whitelist(methods=["POST"])
def save_audience(config) -> dict:
    _require_manager()
    company = current_company()
    assert_entitled(company)
    data = _json(config)
    _audience_from(company, data)  # checks the type
    doc = get_tenant_doc("Sales Audience", data["name"], "write") if data.get("name") else frappe.new_doc("Sales Audience")
    if doc.is_new():
        doc.company = company
    for field in AUDIENCE_FIELDS:
        if field in data:
            doc.set(field, data[field])
    doc.set("members", [])
    if doc.audience_type == audience_rules.SPECIFIC:
        for row in data.get("members") or []:
            if isinstance(row, dict):
                doc.append("members", {k: row.get(k) for k in MEMBER_FIELDS})
    doc.save()
    if doc.sms_opt_in or doc.whatsapp_opt_in:
        log_activity(company, "audience_opt_in_claimed", doc,
                     f"SMS {'yes' if doc.sms_opt_in else 'no'}, WhatsApp {'yes' if doc.whatsapp_opt_in else 'no'}: "
                     f"{doc.opt_in_source}")
    return {"name": doc.name, "summary": refresh_size(doc.name)}


@frappe.whitelist(methods=["POST"])
def refresh_audience(name: str) -> dict:
    _require_manager()
    get_tenant_doc("Sales Audience", name, "write")
    return refresh_size(name)


@frappe.whitelist(methods=["POST"])
def delete_audience(name: str) -> None:
    _require_manager()
    doc = get_tenant_doc("Sales Audience", name, "delete")
    if frappe.db.exists("Sales Campaign", {"audience": doc.name}):
        frappe.throw(_("This audience is used by a campaign. Remove it from the campaign first."))
    frappe.delete_doc("Sales Audience", doc.name)


# Recipients ----------------------------------------------------------------


@frappe.whitelist()
def recipients(search: str = "") -> list[dict]:
    """People with campaign activity: the newest first, or those matching a name, email or phone."""
    company = current_company()
    assert_entitled(company)
    term = (search or "").strip()
    if term:
        like = f"%{term}%"
        rows = frappe.get_all("Sales Prospect", filters={"company": company},
                              or_filters=[["business_name", "like", like], ["email", "like", like], ["phone", "like", like]],
                              fields=["name", "business_name", "email", "phone", "crm_lead"], limit=25)
    else:
        rows = frappe.db.sql(
            """select p.name, p.business_name, p.email, p.phone, p.crm_lead from `tabSales Prospect` p
               join (select m.prospect, max(e.event_time) as last_event from `tabSales Communication Event` e
                     join `tabSales Outreach Message` m on m.name = e.message where e.company = %s
                     group by m.prospect) x on x.prospect = p.name
               order by x.last_event desc limit 25""", company, as_dict=True)
    if not rows:
        return []
    events = frappe.db.sql(
        """select m.prospect, e.event_type, e.event_time, e.campaign from `tabSales Communication Event` e
           join `tabSales Outreach Message` m on m.name = e.message
           where e.company = %s and m.prospect in %s""", (company, tuple(r.name for r in rows)), as_dict=True)
    grouped: dict[str, list[dict]] = {}
    for event in events:
        grouped.setdefault(event.prospect, []).append(event)
    for row in rows:
        mine = grouped.get(row.name, [])
        row.update(timeline.summarize_person(mine))
        row["campaigns"] = len({e["campaign"] for e in mine if e.get("campaign")})
    return sorted(rows, key=lambda r: (-r["score"], r.get("last_activity") or ""))


def _timeline_for(company: str, prospect: str) -> dict:
    messages = frappe.get_all("Sales Outreach Message", filters={"company": company, "prospect": prospect},
                              fields=["name", "campaign", "channel", "step_no", "subject", "status", "sent_on"],
                              order_by="creation asc", limit=500)
    events = frappe.get_all("Sales Communication Event",
                            filters={"company": company, "message": ["in", [m.name for m in messages] or [""]]},
                            fields=["event_type", "event_time", "message", "campaign", "channel", "detail"],
                            order_by="event_time asc", limit=2000)
    for event in events:
        event["event_time"] = str(event["event_time"] or "")
    return {"timeline": timeline.build_timeline(messages, events), **timeline.summarize_person(events),
            "campaigns": sorted({m.campaign for m in messages if m.campaign})}


@frappe.whitelist()
def recipient_timeline(prospect: str) -> dict:
    """Everything one person has been sent, across all campaigns, and what they did with it."""
    doc = get_tenant_doc("Sales Prospect", prospect, "read")
    return {"prospect": doc.name, "business_name": doc.business_name, "email": doc.email, "phone": doc.phone,
            "crm_lead": doc.get("crm_lead"), **_timeline_for(doc.company, doc.name)}


@frappe.whitelist()
def history(doctype: str, name: str) -> list[dict]:
    """Campaign history for a CRM lead, a contact or a prospect: every person it matches, with their timeline."""
    company = current_company()
    assert_entitled(company)
    if doctype not in ("Sales Prospect", "CRM Lead", "Contact", "CRM Deal"):
        frappe.throw(_("Campaign history is kept for prospects, leads, contacts and customers."))
    doc = get_tenant_doc(doctype, name, "read")
    prospects: set[str] = set()
    if doctype == "Sales Prospect":
        prospects.add(doc.name)
    else:
        prospects.update(frappe.get_all("Sales Prospect", filters={"company": company, "crm_lead": doc.name}, pluck="name")
                         if doctype == "CRM Lead" else [])
        prospects.update(frappe.get_all("Sales Campaign Member", filters={"company": company, "source_doctype": doctype,
                                                                          "source_name": doc.name}, pluck="prospect"))
        email = doc.get("email") or doc.get("email_id")
        phone = doc.get("mobile_no") or doc.get("phone")
        if email:
            prospects.update(frappe.get_all("Sales Prospect", filters={"company": company, "email": email}, pluck="name"))
        if phone:
            normal = audience_rules.normalize_phone(phone)
            if normal:
                prospects.update(frappe.get_all("Sales Prospect", filters={"company": company, "normalized_phone": normal},
                                                pluck="name"))
    return [{"prospect": p, "business_name": frappe.db.get_value("Sales Prospect", p, "business_name"),
             **_timeline_for(company, p)} for p in sorted(prospects)]


# Copilot and autopilot -----------------------------------------------------


@frappe.whitelist()
def copilot_suggestions() -> list[dict]:
    """Suggestions for every active campaign, plus the Company-wide ones. The copilot only suggests."""
    company = current_company()
    assert_entitled(company)
    settings = get_settings(company)
    out = []
    for row in frappe.get_all("Sales Campaign", filters={"company": company, "status": ["in", ["Active", "Paused"]]},
                              fields=["name", "campaign_name"], order_by="modified desc", limit=20):
        from reckon_sales_agent.campaigns.analytics import campaign_metrics

        events = _events(company, campaign=row.name)
        context = {"hot_recipients": len(_hot_people(events)), "outbound_enabled": bool(settings.get("outbound_enabled")),
                   "campaign_new": False}
        for item in copilot.suggest(campaign_metrics(row.name), context):
            out.append({**item, "campaign": row.name, "campaign_name": row.campaign_name})
    out += [{**item, "campaign": "", "campaign_name": ""} for item in _audience_suggestions(company)]
    return sorted(out, key=lambda i: copilot.ORDER[i["severity"]])[:40]


@frappe.whitelist(methods=["POST"])
def set_autopilot(level: str | None = None, window: str | None = None, track_opens: int | None = None,
                  track_clicks: int | None = None) -> dict:
    _require_manager()
    company = current_company()
    assert_entitled(company)
    changes: dict = {}
    if level is not None:
        if level not in autopilot.LEVELS:
            frappe.throw(_("Choose Off, Assist or Auto-send."))
        changes["campaign_autopilot"] = level
    if window is not None:
        window = window.strip()
        if window and not autopilot.parse_window(window):
            frappe.throw(_("Write the window like 09:00-20:00."))
        changes["campaign_send_window"] = window
    if track_opens is not None:
        changes["track_opens"] = 1 if int(track_opens) else 0
    if track_clicks is not None:
        changes["track_clicks"] = 1 if int(track_clicks) else 0
    if changes:
        frappe.db.set_value("Sales Agent Settings", company, changes, update_modified=True)
        log_activity(company, "campaign_autopilot_changed", None, ", ".join(f"{k}={v}" for k, v in changes.items()),
                     agent="Governance", policy_outcome="set by a person")
    return _autopilot_state(get_settings(company))
