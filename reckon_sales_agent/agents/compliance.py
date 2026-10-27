"""Compliance agent: keeps consent, opt-outs and calling hours consistent across every channel.

Daily it makes the data agree with the do-not-contact list, always in the stricter direction (reversible):

- a lead on the suppression list is marked "do not contact";
- a do-not-contact lead's running sequences stop, and its drafted or approved messages are cancelled.

It never removes a suppression or re-opens anyone; that is a person's decision. It also audits the last 30 days
for messages that went out without a person's approval or the fast-answer policy, and raises them for review.
Calls are only placed inside the Company's calling hours (09:00–20:00 Bangladesh time by default).
``calling_allowed`` and ``parse_hours`` are pure.
"""

from __future__ import annotations

import re
from datetime import datetime, time

DEFAULT_HOURS = "09:00-20:00"
TIMEZONE = "Asia/Dhaka"
REAL_CHANNELS = ("Email", "SMS", "WhatsApp", "Messenger", "Instagram", "Web Chat")


def parse_hours(value: str | None) -> tuple[time, time]:
    match = re.fullmatch(r"\s*(\d{1,2})(?::(\d{2}))?\s*-\s*(\d{1,2})(?::(\d{2}))?\s*", value or "")
    if not match:
        return time(9), time(20)
    a, b, c, d = match.groups()
    try:
        return time(int(a), int(b or 0)), time(int(c), int(d or 0))
    except ValueError:
        return time(9), time(20)


def calling_allowed(local_now: datetime, hours: str | None = None) -> bool:
    start, end = parse_hours(hours or DEFAULT_HOURS)
    return start <= local_now.time() < end


def local_now(tz: str = TIMEZONE) -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo(tz)).replace(tzinfo=None)


def unapproved(messages: list[dict]) -> list[dict]:
    """Messages that reached a person outside the company without an approval or the fast-answer policy."""
    return [m for m in messages if m.get("status") == "Sent" and m.get("channel") in REAL_CHANNELS
            and not m.get("approved_by") and not m.get("auto_approved_by_policy")]


# --------------------------------------------------------------------------- Frappe side


def check_call(company: str) -> None:
    """Refuse a call outside the Company's calling hours."""
    import frappe
    from frappe import _

    from reckon_sales_agent.usage import get_settings

    hours = get_settings(company).get("calling_hours") or DEFAULT_HOURS
    if not calling_allowed(local_now(), hours):
        frappe.throw(_("Calls are allowed only between {0} (Bangladesh time).").format(hours))


def scan(company: str) -> dict:
    """{"fix": n, "audit": [message names]} without changing anything."""
    return _run(company, fix=False)


def enforce(company: str) -> str:
    result = _run(company, fix=True)
    from reckon_sales_agent.usage import log_activity

    summary = (f"{result['marked']} lead(s) marked do-not-contact, {result['stopped']} sequence(s) stopped, "
               f"{result['cancelled']} message(s) cancelled; {len(result['audit'])} to review")
    log_activity(company, "compliance_enforced", None, summary, actor_type="agent", agent="Compliance",
                 policy_outcome="automatic (stricter only, reversible)")
    return summary


def _run(company: str, fix: bool) -> dict:
    import frappe
    from frappe.utils import add_days, nowdate

    from reckon_sales_agent.campaigns.engine import stop_member
    from reckon_sales_agent.campaigns.suppression import is_suppressed

    marked = stopped = cancelled = 0
    # Leads with something still going out: are they suppressed or marked do-not-contact?
    pending = set(frappe.get_all("Sales Campaign Member", filters={"company": company, "status": "Active"},
                                 pluck="prospect", limit=50000))
    pending |= set(frappe.get_all("Sales Outreach Message", filters={"company": company,
                                                                    "status": ["in", ["Draft", "Approved"]]},
                                  pluck="prospect", limit=50000))
    pending.discard(None)
    for row in frappe.get_all("Sales Prospect", filters={"name": ["in", list(pending) or [""]]},
                              fields=["name", "email", "phone", "website", "do_not_contact"], limit=50000):
        blocked = bool(row.do_not_contact)
        if not blocked and is_suppressed(company, email=row.email, phone=row.phone, website=row.website,
                                         channel="Email"):
            blocked = True
            marked += 1
            if fix:
                frappe.db.set_value("Sales Prospect", row.name, "do_not_contact", 1, update_modified=False)
        if not blocked:
            continue
        for member in frappe.get_all("Sales Campaign Member", filters={"prospect": row.name, "status": "Active"},
                                     pluck="name"):
            stopped += 1
            if fix:
                stop_member(frappe.get_doc("Sales Campaign Member", member), "do not contact (compliance)")
        for message in frappe.get_all("Sales Outreach Message", filters={"prospect": row.name,
                                                                         "status": ["in", ["Draft", "Approved"]]},
                                      pluck="name"):
            cancelled += 1
            if fix:
                frappe.db.set_value("Sales Outreach Message", message,
                                    {"status": "Cancelled", "error": "Do not contact (compliance check)"})
    recent = frappe.get_all("Sales Outreach Message", filters={"company": company, "status": "Sent",
                                                               "sent_on": [">=", add_days(nowdate(), -30)]},
                            fields=["name", "status", "channel", "approved_by", "auto_approved_by_policy"],
                            limit=50000)
    return {"marked": marked, "stopped": stopped, "cancelled": cancelled, "fix": marked + stopped + cancelled,
            "audit": [m["name"] for m in unapproved(recent)]}
