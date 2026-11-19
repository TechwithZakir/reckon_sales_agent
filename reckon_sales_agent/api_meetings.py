"""Backend for the Meetings page: book proposed demos, see what is coming, log what happened."""

from __future__ import annotations

import json
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import now_datetime

from reckon_sales_agent.tenant import current_company, get_tenant_doc

FIELDS = ["name", "title", "status", "prospect", "crm_lead", "assigned_to", "mode", "location", "slot_options",
          "starts_on", "ends_on", "invite_message", "outcome_notes", "source", "event"]


def _stats(rows, now) -> dict:
    """The numbers at the top of the page."""
    today = now.date()
    week_end = now + timedelta(days=7)
    booked = [r for r in rows if r.status == "Booked" and r.starts_on]
    month_ago = now - timedelta(days=30)
    recent = [r for r in rows if r.status in ("Held", "No-show") and r.starts_on and r.starts_on >= month_ago]
    held = sum(1 for r in recent if r.status == "Held")
    return {
        "today": sum(1 for r in booked if r.starts_on.date() == today and r.ends_on and r.ends_on >= now),
        "week": sum(1 for r in booked if now <= r.starts_on <= week_end),
        "to_book": sum(1 for r in rows if r.status == "Proposed"),
        "to_log": sum(1 for r in booked if r.ends_on and r.ends_on < now),
        "held": held,
        "no_show_rate": round(100 * (len(recent) - held) / len(recent)) if recent else None,
    }


@frappe.whitelist()
def board() -> dict:
    company = current_company()
    rows = frappe.get_list("Sales Meeting", filters={"company": company}, fields=FIELDS,
                           order_by="starts_on asc, creation desc", page_length=200)
    names = {p.name: p for p in frappe.get_all("Sales Prospect", filters={"name": ["in", [r.prospect for r in rows] or [""]]},
                                               fields=["name", "business_name", "phone", "email"])}
    invites = {m.name: m.status for m in frappe.get_all("Sales Outreach Message", filters={
        "name": ["in", [r.invite_message for r in rows if r.invite_message] or [""]]}, fields=["name", "status"])}
    now = now_datetime()
    events = {}
    try:
        events = {e.name: e for e in frappe.get_all("Event", filters={"name": ["in", [r.event for r in rows if r.event] or [""]]},
                                                   fields=["name", "sync_with_google_calendar", "google_meet_link"])}
    except Exception:
        events = {}
    out = {"to_book": [], "upcoming": [], "to_log": [], "done": []}
    for r in rows:
        p = names.get(r.prospect) or {}
        item = {**r, "business": p.get("business_name"), "phone": p.get("phone"), "email": p.get("email"),
                "slots": json.loads(r.slot_options or "[]"), "invite_status": invites.get(r.invite_message),
                "synced": bool((events.get(r.event) or {}).get("sync_with_google_calendar")),
                "meet_link": (events.get(r.event) or {}).get("google_meet_link")}
        if r.status == "Proposed":
            out["to_book"].append(item)
        elif r.status == "Booked" and r.ends_on and r.ends_on < now:
            out["to_log"].append(item)
        elif r.status == "Booked":
            out["upcoming"].append(item)
        else:
            out["done"].append(item)
    out["done"] = out["done"][-200:]
    out["stats"] = _stats(rows, now)
    out["me"] = frappe.session.user
    out["owners"] = sorted({r.assigned_to for r in rows if r.assigned_to})
    return out


@frappe.whitelist()
def find_leads(search: str = "") -> list[dict]:
    """Leads a meeting can be set up with: the Company's prospects, matched by name, email or phone."""
    company = current_company()
    needle = f"%{(search or '').strip()}%"
    filters = {"company": company, "do_not_contact": 0}
    or_filters = [["business_name", "like", needle], ["email", "like", needle], ["phone", "like", needle]] if (search or "").strip() else None
    return frappe.get_list("Sales Prospect", filters=filters, or_filters=or_filters,
                           fields=["name", "business_name", "email", "phone", "city"],
                           order_by="modified desc", page_length=20)


@frappe.whitelist(methods=["POST"])
def schedule(prospect: str, starts_on: str, mode: str = "", location: str = "", notes: str = "") -> str:
    """Set up and book a meeting by hand."""
    from reckon_sales_agent.agents.meetings import schedule_meeting

    get_tenant_doc("Sales Prospect", prospect, "write")
    return schedule_meeting(prospect, starts_on, mode, location, notes)


@frappe.whitelist(methods=["POST"])
def cancel(meeting: str, notes: str | None = None) -> None:
    from reckon_sales_agent.agents.meetings import record_outcome

    doc = get_tenant_doc("Sales Meeting", meeting, "write")
    if doc.status not in ("Proposed", "Booked"):
        frappe.throw(_("This meeting is {0}.").format(doc.status))
    record_outcome(meeting, "Cancelled", notes or "")


@frappe.whitelist(methods=["POST"])
def save_notes(meeting: str, notes: str = "") -> None:
    doc = get_tenant_doc("Sales Meeting", meeting, "write")
    doc.db_set("outcome_notes", (notes or "")[:2000])


def _calendar_parts(doc):
    """(title, start, end, location, description) with the times in UTC, for the calendar file and links."""
    from datetime import timezone
    from zoneinfo import ZoneInfo

    from frappe.utils import get_datetime, get_system_timezone

    if not doc.starts_on:
        frappe.throw(_("This meeting has no time yet."))
    zone = ZoneInfo(get_system_timezone())
    start = get_datetime(doc.starts_on).replace(tzinfo=zone).astimezone(timezone.utc)
    end = get_datetime(doc.ends_on or doc.starts_on).replace(tzinfo=zone).astimezone(timezone.utc)
    prospect = frappe.db.get_value("Sales Prospect", doc.prospect, ["business_name", "phone", "email"], as_dict=True) or {}
    description = "\n".join(x for x in (doc.mode, prospect.get("business_name"), prospect.get("phone"), prospect.get("email"),
                                         doc.outcome_notes) if x)
    return doc.title, start, end, doc.location or "", description


@frappe.whitelist()
def calendar(meeting: str) -> dict:
    """Links to add this meeting to Google Calendar, Office 365 or Outlook, and the calendar file."""
    from reckon_sales_agent.agents.meetings import calendar_links

    doc = get_tenant_doc("Sales Meeting", meeting, "read")
    title, start, end, location, description = _calendar_parts(doc)
    return {**calendar_links(title, start, end, location, description),
            "ics": f"/api/method/reckon_sales_agent.api_meetings.ics?meeting={doc.name}", "event": doc.event}


@frappe.whitelist()
def ics(meeting: str) -> None:
    """The meeting as a calendar file (.ics) that any calendar app opens."""
    from reckon_sales_agent.agents.meetings import build_ics

    doc = get_tenant_doc("Sales Meeting", meeting, "read")
    title, start, end, location, description = _calendar_parts(doc)
    frappe.response["filename"] = f"{doc.name}.ics"
    frappe.response["filecontent"] = build_ics(f"{doc.name}@reckon-sales-agent", title, start, end, location, description,
                                               now_utc=now_datetime())
    frappe.response["type"] = "download"


@frappe.whitelist()
def timeline(meeting: str) -> list[dict]:
    """What the agents and people did about this meeting, newest first."""
    doc = get_tenant_doc("Sales Meeting", meeting, "read")
    return frappe.get_all("Sales Agent Activity", filters={"company": doc.company, "reference_doctype": "Sales Meeting",
                                                           "reference_name": doc.name},
                          fields=["action", "summary", "agent", "actor_type", "actor", "creation"],
                          order_by="creation desc", limit=30)


@frappe.whitelist()
def book(meeting: str, starts_on: str) -> str:
    from reckon_sales_agent.agents.meetings import book as do_book

    get_tenant_doc("Sales Meeting", meeting, "write")
    return do_book(meeting, starts_on)


@frappe.whitelist()
def outcome(meeting: str, result: str, notes: str | None = None) -> None:
    from reckon_sales_agent.agents.meetings import record_outcome

    get_tenant_doc("Sales Meeting", meeting, "write")
    record_outcome(meeting, result, notes or "")


@frappe.whitelist()
def propose(prospect: str) -> str | None:
    from reckon_sales_agent.agents.meetings import start_meeting

    get_tenant_doc("Sales Prospect", prospect, "write")
    return start_meeting(prospect, "proposed by a person")
