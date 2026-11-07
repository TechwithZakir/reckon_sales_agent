"""Segments on the Frappe side: describe each person to the rules, and find who matches (rules: campaigns.segments).

Every query is filtered by Company here, because ``frappe.get_all`` does not apply the tenant permission hooks.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import add_days, get_datetime, now_datetime

from reckon_sales_agent.campaigns import people, segments, timeline
from reckon_sales_agent.campaigns import tags as tag_rules

LIMIT = 20000
HISTORY_DAYS = 730
REPLIES = ("replied", "positive_reply", "meeting_requested", "negative_reply", "question", "interested")
FIELDS = ["name", "business_name", "contact_name", "email", "phone", "city", "industry", "source_type", "fit_score", "tags",
          "sms_consent", "whatsapp_consent", "optin_status", "email_status", "creation"]


def _days(stamp, now):
    if not stamp:
        return None
    return max((now - get_datetime(stamp)).days, 0)


def _view(row, mine: list[dict], now) -> dict:
    last: dict[str, str] = {}
    for event in mine:  # oldest first, so the last write is the latest
        kind = "replied" if event["event_type"] in REPLIES else event["event_type"]
        last[kind] = event["event_time"]
    summary = timeline.summarize_person(mine) if mine else {"temperature": "Cold"}
    return {
        "name": row.name, "business_name": row.business_name, "contact_name": row.contact_name, "email": row.email or "",
        "phone": row.phone or "", "city": row.city or "", "industry": row.industry or "", "source": row.source_type or "",
        "fit_score": row.fit_score or 0, "tags": tag_rules.normalize(row.tags), "sms_consent": bool(row.sms_consent),
        "whatsapp_consent": bool(row.whatsapp_consent), "confirmed": row.optin_status != "Unconfirmed", "email_status": row.email_status or "",
        "joined_days": _days(row.creation, now), "last_opened_days": _days(last.get("opened"), now),
        "last_clicked_days": _days(last.get("clicked"), now), "last_replied_days": _days(last.get("replied"), now),
        "last_sent_days": _days(last.get("sent"), now), "temperature": summary.get("temperature") or "Cold",
    }


def person_views(company: str, names: list[str] | None = None) -> list[dict]:
    """Everyone a campaign could reach (approved, not do-not-contact), described to the segment rules."""
    now = now_datetime()
    filters = {"company": company, "review_status": "Approved", "do_not_contact": 0, "merged_into": ["is", "not set"]}
    if names is not None:
        if not names:
            return []
        filters["name"] = ["in", names]
    rows = frappe.get_all("Sales Prospect", filters=filters, fields=FIELDS, limit=LIMIT)
    events = people.by_person(people.events(company, since=str(add_days(now, -HISTORY_DAYS))))
    return [_view(row, events.get(row.name, []), now) for row in rows]


def _rules(segment) -> tuple[list[dict], str]:
    raw = segment.get("rules") if hasattr(segment, "get") else segment
    try:
        rows = json.loads(raw or "[]") if isinstance(raw, str) else raw or []
    except ValueError:
        rows = []
    conditions, _problems = segments.clean_conditions(rows)
    mode = segment.get("match_mode") if hasattr(segment, "get") else segments.ALL
    return conditions, mode if mode in segments.MATCH_MODES else segments.ALL


def resolve(segment) -> list[dict]:
    """The people a saved segment (a Sales Segment document) matches right now."""
    conditions, mode = _rules(segment)
    return [p for p in person_views(segment.company) if segments.matches(p, conditions, mode)]


def preview(company: str, rules, mode: str) -> dict:
    """Who a set of rules would match, without saving anything."""
    conditions, problems = segments.clean_conditions(rules)
    if problems or not conditions:
        return {"total": 0, "sample": [], "problems": problems or ["Add at least one rule."]}
    found = [p for p in person_views(company) if segments.matches(p, conditions, mode if mode in segments.MATCH_MODES else segments.ALL)]
    return {"total": len(found), "problems": [], "sample": [
        {"name": p["name"], "label": p["contact_name"] or p["business_name"], "email": p["email"], "phone": p["phone"]}
        for p in found[:8]]}


def refresh(name: str) -> int:
    segment = frappe.get_doc("Sales Segment", name)
    total = len(resolve(segment))
    frappe.db.set_value("Sales Segment", name, {"size": total, "last_refreshed": now_datetime()}, update_modified=False)
    return total


def person_in(company: str, prospect: str, segment_name: str) -> bool:
    """True when this one person is in the named segment of the Company (an automation asks this)."""
    row = frappe.db.get_value("Sales Segment", {"company": company, "segment_name": segment_name}, ["rules", "match_mode"],
                              as_dict=True) or frappe.db.get_value("Sales Segment", {"company": company, "name": segment_name},
                                                                    ["rules", "match_mode"], as_dict=True)
    if not row:
        return False
    conditions, mode = _rules(row)
    views = person_views(company, [prospect])
    return bool(views) and segments.matches(views[0], conditions, mode)


def recipients(segment) -> list[dict]:
    """The segment as audience recipients (one per person, with an address)."""
    from reckon_sales_agent.campaigns import audience as rules

    return [r for r in (rules.recipient("Prospect", "Sales Prospect", p["name"], p["contact_name"] or p["business_name"],
                                        p["email"], p["phone"]) for p in resolve(segment)) if r]
