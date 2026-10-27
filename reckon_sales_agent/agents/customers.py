"""Customer agent: re-orders, upsell and referrals from the Company's own sales on this site (Reckon Distribution).

Weekly it reads the Company's submitted Sales Invoices (ERPNext) and gives the salesperson a check-in task for:

- a regular customer who is late: at least 3 invoices in the last year and no order for longer than 1.5 times
  their usual gap (at least 30 days), so a re-order call is due before they drift to a competitor;
- a growing customer: the last 90 days' sales are at least 30% above the 90 days before, a good moment to offer
  the wider range or ask for a referral.

Customers are existing relationships, so the agent only creates tasks for a person; it sends nothing.
``lapsed`` and ``growing`` are pure.
"""

from __future__ import annotations

from datetime import date
from statistics import median

PREFIX = "Customer check-in:"


def lapsed(dates: list[date], today: date) -> dict | None:
    """{"days", "usual"} when a regular customer is overdue for an order, else None."""
    dates = sorted(set(dates))
    if len(dates) < 3:
        return None
    gaps = [(b - a).days for a, b in zip(dates, dates[1:], strict=False) if (b - a).days > 0]
    if not gaps:
        return None
    usual = median(gaps)
    since = (today - dates[-1]).days
    return {"days": since, "usual": round(usual)} if since > max(30, 1.5 * usual) else None


def growing(recent: float, before: float) -> bool:
    return before > 0 and recent >= 1.3 * before


# --------------------------------------------------------------------------- Frappe side


def check_ins(company: str) -> str:
    import html

    import frappe
    from frappe.utils import add_days, getdate, nowdate

    from reckon_sales_agent.usage import get_settings, log_activity

    if not frappe.db.table_exists("Sales Invoice"):
        return "No sales data on this site"
    user = get_settings(company).get("task_assignee")
    if not user:
        return "Name the salesperson first (autopilot settings)"
    today = getdate(nowdate())
    rows = frappe.get_all("Sales Invoice", filters={"company": company, "docstatus": 1, "is_return": 0,
                                                    "posting_date": [">=", add_days(today, -365)]},
                          fields=["customer", "customer_name", "posting_date", "base_grand_total"], limit=200000)
    by: dict[str, list] = {}
    for row in rows:
        by.setdefault(row.customer, []).append(row)
    created = {"late": 0, "growing": 0}
    for customer, invoices in by.items():
        late = lapsed([getdate(r.posting_date) for r in invoices], today)
        recent = sum(r.base_grand_total or 0 for r in invoices if (today - getdate(r.posting_date)).days <= 90)
        before = sum(r.base_grand_total or 0 for r in invoices if 90 < (today - getdate(r.posting_date)).days <= 180)
        if late:
            kind, title = "late", (f"{PREFIX} {invoices[0].customer_name or customer} has not ordered for "
                                   f"{late['days']} days (usually every {late['usual']})")
            body = ("A regular customer is late. Call to ask how stock is moving, whether anything went wrong, and "
                    "take the next order.")
        elif growing(recent, before):
            kind, title = "growing", f"{PREFIX} {invoices[0].customer_name or customer} is buying more"
            body = (f"Sales in the last 90 days are {recent:,.0f} against {before:,.0f} before. Thank them, offer the "
                    "wider range, and ask whether a fellow retailer or distributor would benefit too.")
        else:
            continue
        if frappe.db.exists("ToDo", {"reference_type": "Customer", "reference_name": customer, "status": "Open",
                                     "description": ["like", f"%{PREFIX}%"]}):
            continue
        todo = frappe.get_doc({
            "doctype": "ToDo", "status": "Open", "priority": "High" if kind == "late" else "Medium",
            "description": f"<b>{html.escape(title[:200])}</b><br>{html.escape(body)}",
            "date": add_days(today, 1), "allocated_to": user, "reference_type": "Customer",
            "reference_name": customer,
        })
        if frappe.get_meta("ToDo").has_field("rsa_company"):
            todo.rsa_company = company
        todo.insert(ignore_permissions=True)
        created[kind] += 1
    summary = f"{created['late']} late customer(s) and {created['growing']} growing customer(s) to call"
    log_activity(company, "customer_checkins", None, summary, actor_type="agent", agent="Customers",
                 policy_outcome="automatic (tasks for a person only)")
    return summary
