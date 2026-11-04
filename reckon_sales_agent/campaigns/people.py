"""Who engaged with a Company's campaigns: the Frappe side of ``campaigns.timeline``.

One query returns every communication event with its message's channel and step and the person (prospect) it belongs to.
The Studio API and the Agent Studio planner both read people through it.
"""

from __future__ import annotations

import frappe

from reckon_sales_agent.campaigns import timeline


def events(company: str, campaign: str | None = None, since: str | None = None, limit: int = 50000) -> list[dict]:
    """Communication events, oldest first."""
    conditions, values = ["e.company = %s"], [company]
    if campaign:
        conditions.append("e.campaign = %s")
        values.append(campaign)
    if since:
        conditions.append("e.event_time >= %s")
        values.append(since)
    rows = frappe.db.sql(
        f"""select e.event_type, coalesce(m.channel, e.channel) as channel, m.step_no, m.variant, e.message, e.member, e.campaign,
                   e.event_time, e.detail, mem.prospect
            from `tabSales Communication Event` e
            left join `tabSales Outreach Message` m on m.name = e.message
            left join `tabSales Campaign Member` mem on mem.name = e.member
            where {' and '.join(conditions)} order by e.event_time asc limit {int(limit)}""",
        values, as_dict=True)
    for row in rows:
        row["event_time"] = str(row["event_time"] or "")
    return rows


def by_person(rows: list[dict]) -> dict[str, list[dict]]:
    people: dict[str, list[dict]] = {}
    for event in rows:
        if event.get("prospect"):
            people.setdefault(event["prospect"], []).append(event)
    return people


def hot_people(rows: list[dict]) -> list[str]:
    """The prospects whose engagement is hot: a positive reply, a meeting request, or repeated clicks."""
    return [p for p, mine in by_person(rows).items() if timeline.summarize_person(mine)["temperature"] == "Hot"]
