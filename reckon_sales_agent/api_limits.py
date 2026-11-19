"""The limits the Sales Agent works within, in one place, so a person can see them on screen instead of meeting them as errors.

Three groups: lead capture (monthly leads and research, jobs at once, the background worker and how long the research
queue will take), the AI (which model, how many calls this month, whether the account is paused) and sending
(per day, per hour, per month, warm-up, and whether sending is live). Everything is limited to the session's Company.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_to_date, now_datetime, nowdate

from reckon_sales_agent.constants import USAGE_AI, USAGE_DISCOVERY, USAGE_MESSAGE, USAGE_RESEARCH
from reckon_sales_agent.limits_math import eta_minutes
from reckon_sales_agent.tenant import current_company
from reckon_sales_agent.usage import assert_entitled, get_limit, get_settings, get_used

RATE_WINDOW_MINUTES = 20
RESEARCH_ACTIONS = ["research_done", "research_failed", "research_partial", "research_blocked"]


def meter(company: str, usage_type: str) -> dict:
    return {"used": get_used(company, usage_type), "limit": get_limit(company, usage_type)}


def _capture(company: str, settings) -> dict:
    from reckon_sales_agent.jobs import worker_status

    since = add_to_date(now_datetime(), minutes=-RATE_WINDOW_MINUTES)
    finished = frappe.db.count("Sales Agent Activity", {"company": company, "action": ["in", RESEARCH_ACTIONS],
                                                       "creation": [">=", since]})
    waiting = frappe.db.count("Sales Prospect", {"company": company, "research_status": "Queued"})
    active = frappe.db.count("Sales Discovery Job", {"company": company, "status": ["in", ["Queued", "Running"]]})
    workers = worker_status()
    return {
        "leads": meter(company, USAGE_DISCOVERY),
        "research": meter(company, USAGE_RESEARCH),
        "per_run_max": int(settings.get("max_results_per_job") or 100),
        "jobs": {"active": active, "max": int(settings.get("max_concurrent_jobs") or 2),
                 "waiting": frappe.db.count("Sales Discovery Job", {"company": company, "status": "Queued"})},
        "research_waiting": waiting,
        "eta_minutes": eta_minutes(waiting, finished, RATE_WINDOW_MINUTES),
        "workers": workers,
    }


def _ai(company: str) -> dict:
    from reckon_sales_agent.api_agent_studio import _ai_label
    from reckon_sales_agent.providers.factory import ai_blocked

    settings = get_settings(company)
    paused = None
    try:
        paused = ai_blocked(company)
    except Exception:
        paused = None
    return {"label": _ai_label(company), "enabled": bool(settings.get("ai_enabled")), "calls": meter(company, USAGE_AI),
            "paused": str(paused)[:200] if paused else None}


def _sending(company: str, settings) -> dict:
    from reckon_sales_agent.agents.deliverability import today_email_limit
    from reckon_sales_agent.campaigns import pacing
    from reckon_sales_agent.campaigns.engine import _sent_today

    last_hour = frappe.db.count("Sales Communication Event", {
        "company": company, "event_type": ["in", ["sent", "dry_run"]],
        "event_time": [">=", add_to_date(now_datetime(), hours=-1)]})
    try:
        email_today = int(today_email_limit(settings))
    except Exception:
        email_today = int(settings.get("daily_message_limit") or 0)
    return {
        "month": meter(company, USAGE_MESSAGE),
        "today": {"used": _sent_today(company), "limit": int(settings.get("daily_message_limit") or 0), "email_limit": email_today},
        "hour": {"used": last_hour, "limit": pacing.config(settings)["hourly"]},
        "live": bool(settings.get("outbound_enabled")),
        "warmup": bool(settings.get("warmup_enabled")),
        "as_of": nowdate(),
    }


@frappe.whitelist()
def overview() -> dict:
    """Everything the limits panel shows, for the session's Company (no keys, no addresses)."""
    company = current_company()
    assert_entitled(company)
    settings = get_settings(company)
    return {"capture": _capture(company, settings), "ai": _ai(company), "sending": _sending(company, settings)}
