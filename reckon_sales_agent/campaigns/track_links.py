"""Tracking on the Frappe side: tracked links for a message, recording opens and clicks, and warm-up for hot recipients.

The message stored in the database is never changed: the links are swapped on the copy that goes out, so what a person
approved is exactly what is stored. A click or an open becomes a Sales Communication Event, which feeds the funnel, the
recipient's timeline and their engagement score. Visits that identify themselves as scanners or previews are counted
apart (``bot_hits``) and never become events.
"""

from __future__ import annotations

import frappe
from frappe.utils import get_url, now_datetime

from reckon_sales_agent.campaigns import tracking
from reckon_sales_agent.campaigns.autopilot import creates_followup_tasks, normalize_level

TRACKED_CHANNELS = ("Email", "SMS", "WhatsApp")
CLICK_PATH = "/l/"
OPEN_PATH = "/api/method/reckon_sales_agent.api_track.open_pixel"
HOT_CLICKS = 2  # a second click means real interest


def _link(message, kind: str, url: str = "") -> str:
    code = tracking.new_code()
    frappe.get_doc({"doctype": "Sales Tracked Link", "company": message.company, "code": code, "kind": kind,
                    "url": url, "campaign": message.campaign, "message": message.name, "member": message.member,
                    "prospect": message.prospect}).insert(ignore_permissions=True)
    return code


def instrument(message, settings) -> None:
    """Swap the links in the outgoing copy of ``message`` (in memory only) and add the open pixel."""
    channel = message.get("channel")
    if message.get("is_reply") or channel not in TRACKED_CHANNELS:
        return
    clicks = bool(settings.get("track_clicks"))
    opens = bool(settings.get("track_opens")) and channel == "Email"
    if channel == "WhatsApp" and message.get("whatsapp_template"):
        clicks = False  # a template's wording is fixed by Meta; there is no link of ours to swap
    if not clicks and not opens:
        return
    codes: dict[str, str] = {}

    def make(url: str) -> str:
        if url not in codes:
            codes[url] = get_url(f"{CLICK_PATH}{_link(message, 'click', url)}")
        return codes[url]

    body = message.body or ""
    if clicks:
        body = (tracking.rewrite_html_links(body, make) if channel == "Email"
                else tracking.rewrite_text_links(body, make))
    if opens:
        body = tracking.add_pixel(body, get_url(f"{OPEN_PATH}?c={_link(message, 'open')}"))
    message.body = body


# Visits ----------------------------------------------------------------------


def _visit(code: str, kind: str, user_agent: str | None):
    """Count one visit. Returns (link row, message name) for a real person, or (link row, None) for a scanner."""
    link = frappe.db.get_value("Sales Tracked Link", {"code": code, "kind": kind},
                               ["name", "url", "message", "member", "campaign"], as_dict=True)
    if not link:
        return None, None
    if tracking.is_bot(user_agent):
        frappe.db.sql("update `tabSales Tracked Link` set bot_hits = ifnull(bot_hits, 0) + 1 where name = %s", link.name)
        frappe.db.commit()
        return link, None
    now = now_datetime()
    frappe.db.sql("update `tabSales Tracked Link` set hits = ifnull(hits, 0) + 1, first_hit = ifnull(first_hit, %s), "
                  "last_hit = %s where name = %s", (now, now, link.name))
    return link, link.message


def _record(link, message_name: str, event_type: str) -> None:
    from reckon_sales_agent.campaigns.engine import _refresh_metrics, record_event

    message = frappe.get_doc("Sales Outreach Message", message_name)
    # The same link in the same minute is one visit: a mail app often loads an image or a link twice.
    record_event(message, event_type, f"{event_type}:{link.name}:{int(now_datetime().timestamp()) // 60}")
    _refresh_metrics(message.campaign)


def opened(code: str, user_agent: str | None = None) -> bool:
    link, message = _visit(code, "open", user_agent)
    if message:
        _record(link, message, "opened")
    frappe.db.commit()
    return bool(message)


def clicked(code: str, user_agent: str | None = None) -> str | None:
    """Record a click and return where to send the visitor, or None for an unknown or unsafe link."""
    link, message = _visit(code, "click", user_agent)
    if not link or not str(link.url or "").lower().startswith(("http://", "https://")):
        return None
    if message:
        _record(link, message, "clicked")
        _follow_up_if_hot(message)
    frappe.db.commit()
    return link.url


def _follow_up_if_hot(message_name: str) -> None:
    """A second click earns a call task for a person (internal work: nobody outside is contacted)."""
    try:
        from reckon_sales_agent.campaigns.engine import record_event
        from reckon_sales_agent.providers.channels import create_task
        from reckon_sales_agent.usage import get_settings

        message = frappe.get_doc("Sales Outreach Message", message_name)
        settings = get_settings(message.company)
        if not creates_followup_tasks(normalize_level(settings.get("campaign_autopilot"))):
            return
        clicks = frappe.db.sql("select count(*) from `tabSales Communication Event` where member = %s "
                               "and event_type = 'clicked'", message.member)[0][0]
        key = f"hot_task:{message.member}"
        if clicks < HOT_CLICKS or frappe.db.exists("Sales Communication Event", {"idempotency_key": key}):
            return
        prospect = frappe.db.get_value("Sales Prospect", message.prospect, "business_name")
        visitor = frappe.session.user
        frappe.set_user("Administrator")  # a public visit has no permissions of its own; the task is internal work
        try:
            create_task(message.prospect, f"Hot lead: call now · {prospect}",
                        "They clicked links in your campaign more than once, so they are interested. Call while it is fresh.",
                        settings, priority="High")
            record_event(message, "task_created", key, detail="Hot lead: clicked more than once")
        finally:
            frappe.set_user(visitor)
    except Exception:
        frappe.log_error(title="Sales Agent hot-lead task failed")  # never break the visitor's redirect
