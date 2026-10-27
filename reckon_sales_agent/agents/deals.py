"""Deal coach and Forecast agents, on Frappe CRM deals of the Company.

Deal coach (daily): a deal is *stuck* when nothing moved for 14 days (30 when On Hold), or *overdue* when its
expected closing date passed while it is still open. The coach gives the deal owner one CRM task with the next
best action (once a week per deal at most), can draft a proposal from approved facts as a private note, and
summarises why deals were lost. It never sends anything to the customer and never changes a price.

Forecast (weekly, read only): the expected value of open deals closing in the next 30 and 90 days, from each
deal's probability calibrated against the Company's own win rate, with an 80% range (normal approximation of the
sum of independent won/lost outcomes).

The rules and the forecast maths are pure.
"""

from __future__ import annotations

import math
from datetime import date, datetime

OPEN_TYPES = ("Open", "Ongoing", "On Hold")
STALE_DAYS = {"Open": 14, "Ongoing": 14, "On Hold": 30}
TASK_PREFIX = "Deal coach:"
Z80 = 1.2816  # two-sided 80% interval


def _day(value) -> date | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)[:19]).date()
    except ValueError:
        return None


def deal_health(deal: dict, today: date) -> dict | None:
    """{"problem", "days", "action"} for a deal that needs a push, or None. ``deal`` has status_type,
    last_activity, expected_closure_date, next_step, probability."""
    kind = deal.get("status_type") or "Open"
    if kind not in OPEN_TYPES:
        return None
    last = _day(deal.get("last_activity"))
    idle = (today - last).days if last else None
    close = _day(deal.get("expected_closure_date"))
    if close and close < today:
        return {"problem": "overdue", "days": (today - close).days,
                "action": "The expected closing date has passed: call to confirm the decision date, or close the deal "
                          "as won or lost with a reason."}
    if idle is not None and idle >= STALE_DAYS.get(kind, 14):
        if not deal.get("next_step"):
            action = "No next step is agreed: call and agree one concrete next step with a date."
        elif (deal.get("probability") or 0) >= 60:
            action = (f"Likely to close but quiet for {idle} days: send the proposal or quotation and ask for a "
                      "decision date.")
        else:
            action = f"Quiet for {idle} days: follow up on \"{deal['next_step']}\" and update the deal."
        return {"problem": "stuck", "days": idle, "action": action}
    return None


def loss_summary(reasons: list[str | None]) -> list[tuple[str, int]]:
    """Most common lost reasons first."""
    counts: dict[str, int] = {}
    for reason in reasons:
        key = (reason or "No reason given").strip()
        counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def calibration(predicted: list[float], won: list[bool]) -> float:
    """How far the Company's stated probabilities over- or under-shoot its real win rate (closed deals).

    1.0 with fewer than 10 closed deals; otherwise actual/predicted, kept between 0.5 and 1.5."""
    if len(predicted) < 10 or not sum(predicted):
        return 1.0
    ratio = (sum(won) / len(won)) / (sum(predicted) / len(predicted))
    return max(0.5, min(1.5, ratio))


def forecast(deals: list[dict], today: date, factor: float = 1.0, horizon_days: int = 90) -> dict:
    """Expected won value of open deals closing within ``horizon_days`` (deals with no date count as 90 days out)."""
    expected = variance = 0.0
    counted = 0
    for deal in deals:
        close = _day(deal.get("expected_closure_date"))
        days = (close - today).days if close else 90
        if days > horizon_days or (deal.get("status_type") or "Open") not in OPEN_TYPES:
            continue
        value = float(deal.get("value") or 0)
        p = max(0.0, min(1.0, (float(deal.get("probability") or 0) / 100) * factor))
        expected += value * p
        variance += value * value * p * (1 - p)
        counted += 1
    spread = Z80 * math.sqrt(variance)
    return {"deals": counted, "expected": round(expected, 2), "low": round(max(0.0, expected - spread), 2),
            "high": round(expected + spread, 2)}


# --------------------------------------------------------------------------- Frappe side


def _status_info() -> dict:
    import frappe

    fields = ["name"] + [f for f in ("type", "probability") if frappe.db.has_column("CRM Deal Status", f)]
    return {r.name: r for r in frappe.get_all("CRM Deal Status", fields=fields)}


def company_deals(company: str) -> list[dict]:
    """The Company's CRM deals with what the coach and forecast need."""
    import frappe

    if not frappe.db.table_exists("CRM Deal") or not frappe.db.has_column("CRM Deal", "rsa_company"):
        return []
    wanted = ["name", "status", "deal_owner", "modified", "probability", "next_step", "expected_closure_date",
              "closed_date", "lost_reason", "deal_value", "expected_deal_value", "annual_revenue",
              "organization", "last_responded_on", "lead"]
    fields = [f for f in wanted if f in ("name", "modified") or frappe.db.has_column("CRM Deal", f)]
    statuses = _status_info()
    rows = []
    for deal in frappe.get_all("CRM Deal", filters={"rsa_company": company}, fields=fields, limit=20000):
        status = statuses.get(deal.status) or {}
        kind = status.get("type") or ("Won" if deal.status == "Won" else "Lost" if deal.status == "Lost" else "Open")
        last = max(filter(None, [deal.get("modified"), deal.get("last_responded_on")]), default=None)
        rows.append({**deal, "status_type": kind, "last_activity": last,
                     "probability": deal.get("probability") or status.get("probability") or 0,
                     "value": deal.get("deal_value") or deal.get("expected_deal_value") or deal.get("annual_revenue") or 0})
    return rows


def stuck_count(company: str) -> int:
    from frappe.utils import getdate, nowdate

    today = getdate(nowdate())
    return sum(1 for d in company_deals(company) if deal_health(d, today))


def coach(company: str) -> str:
    """Give each stuck or overdue deal's owner one task with the next action (at most weekly per deal)."""
    import frappe
    from frappe.utils import add_days, getdate, nowdate

    from reckon_sales_agent.usage import get_settings, log_activity

    today = getdate(nowdate())
    fallback = get_settings(company).get("task_assignee")
    created = 0
    deals = company_deals(company)
    for deal in deals:
        health = deal_health(deal, today)
        if not health:
            continue
        recent = frappe.db.exists("CRM Task", {"reference_doctype": "CRM Deal", "reference_docname": deal["name"],
                                               "title": ["like", f"{TASK_PREFIX}%"],
                                               "creation": [">=", add_days(nowdate(), -7)]})
        if recent:
            continue
        owner = deal.get("deal_owner") or fallback
        task = frappe.get_doc({
            "doctype": "CRM Task", "title": f"{TASK_PREFIX} {deal.get('organization') or deal['name']} "
                                           f"({health['problem']} {health['days']} days)"[:140],
            "description": health["action"], "priority": "High" if health["problem"] == "overdue" else "Medium",
            "status": "Todo", "assigned_to": owner, "due_date": f"{add_days(nowdate(), 1)} 10:00:00",
            "reference_doctype": "CRM Deal", "reference_docname": deal["name"],
        })
        if frappe.get_meta("CRM Task").has_field("rsa_company"):
            task.rsa_company = company
        task.insert(ignore_permissions=True)
        created += 1
    ended = {d["name"]: _day(d.get("closed_date") or d.get("modified")) for d in deals if d["status_type"] == "Lost"}
    lost = [d.get("lost_reason") for d in deals if ended.get(d["name"]) and (today - ended[d["name"]]).days <= 90]
    top = ", ".join(f"{reason} ({n})" for reason, n in loss_summary(lost)[:3])
    summary = f"{created} deal task(s)" + (f"; lost in 90 days: {top}" if top else "")
    log_activity(company, "deals_coached", None, summary, actor_type="agent", agent="Deals",
                 policy_outcome="automatic (internal tasks only)")
    return summary


def draft_proposal(company: str, deal_name: str) -> str:
    """An AI proposal from approved facts, saved as a private note on the deal; a person edits and sends it."""
    import frappe
    from frappe import _

    from reckon_sales_agent.agents.content import knowledge_prompt
    from reckon_sales_agent.agents.content_agent import approved_knowledge
    from reckon_sales_agent.constants import USAGE_AI
    from reckon_sales_agent.providers.factory import get_llm
    from reckon_sales_agent.providers.llm import LLMError, untrusted
    from reckon_sales_agent.usage import log_activity, reserve

    deal = frappe.get_doc("CRM Deal", deal_name)
    if deal.get("rsa_company") != company:
        frappe.throw(_("Not your Company's deal."), frappe.PermissionError)
    llm = get_llm(company)
    if not llm:
        frappe.throw(_("Turn on AI to draft proposals."))
    knowledge = approved_knowledge(company, include_competitors=True)
    reserve(company, USAGE_AI, 1, deal)
    schema = {"type": "object", "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
              "required": ["title", "body"], "additionalProperties": False}
    try:
        data = llm.complete_json(
            "You draft a short B2B proposal for a seller in Bangladesh, for the salesperson to edit before sending. "
            "Use ONLY facts, prices and offers in the approved knowledge; where a price is not there, write "
            "[price to confirm]. Sections: the customer's need, what we propose, why us, next step. Under 300 words.",
            untrusted("deal", f"{deal.get('organization') or ''} · next step: {deal.get('next_step') or ''} · "
                      f"industry: {deal.get('industry') or ''}") + "\n"
            + untrusted("approved knowledge", knowledge_prompt(knowledge)),
            schema, max_tokens=2000)
    except LLMError as exc:
        frappe.throw(str(exc))
    note = frappe.get_doc({"doctype": "FCRM Note", "title": f"Draft proposal: {data['title']}"[:140],
                           "content": frappe.utils.escape_html(data["body"]).replace("\n", "<br>"),
                           "reference_doctype": "CRM Deal", "reference_docname": deal.name})
    if frappe.get_meta("FCRM Note").has_field("rsa_company"):
        note.rsa_company = company
    note.insert(ignore_permissions=True)
    log_activity(company, "proposal_drafted", deal, data["title"][:200], actor_type="agent", agent="Deals",
                 policy_outcome="draft only: a person sends it")
    return note.name


def run_forecast(company: str) -> dict:
    """Weekly: the 30- and 90-day forecast, stored on the Company's settings and in the activity log."""
    import json

    import frappe
    from frappe.utils import getdate, nowdate

    from reckon_sales_agent.usage import log_activity

    today = getdate(nowdate())
    deals = company_deals(company)
    closed = [d for d in deals if d["status_type"] in ("Won", "Lost")]
    factor = calibration([float(d["probability"] or 0) / 100 for d in closed], [d["status_type"] == "Won" for d in closed])
    result = {"d30": forecast(deals, today, factor, 30), "d90": forecast(deals, today, factor, 90),
              "calibration": round(factor, 2), "on": str(today)}
    frappe.db.set_value("Sales Agent Settings", company, "forecast_json", json.dumps(result))
    d90 = result["d90"]
    log_activity(company, "forecast_ready", None,
                 f"Next 90 days: {d90['expected']:,.0f} expected (80% range {d90['low']:,.0f}–{d90['high']:,.0f}) "
                 f"from {d90['deals']} open deal(s); calibration ×{result['calibration']}",
                 actor_type="agent", agent="Analytics", policy_outcome="automatic (read only)")
    return result
