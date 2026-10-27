"""Signals agent: re-checks approved leads every month for new buying signals.

Weekly it re-researches up to 20 approved leads whose research is older than 30 days and that are not in a
running sequence (their website again: hiring, a new depot or branch, new brands, expansion news). Before the
research it keeps the lead's buying-signal score; when the new score is 15 points or more higher, the lead is
raised in the Needs-you inbox so a person can start outreach (starting a campaign stays a person's decision).
Tenders on e-GP are not checked (no public API).
``signal_raised`` is pure.
"""

from __future__ import annotations

RISE = 15
STALE_DAYS = 30
BATCH = 20


def signal_raised(previous: int | None, current: int | None) -> bool:
    return previous is not None and current is not None and int(current) - int(previous) >= RISE


# --------------------------------------------------------------------------- Frappe side


def recheck(company: str) -> str:
    import frappe
    from frappe.utils import add_days, now_datetime, nowdate

    from reckon_sales_agent.jobs import enqueue_research
    from reckon_sales_agent.usage import log_activity

    busy = set(frappe.get_all("Sales Campaign Member", filters={"company": company, "status": "Active"},
                              pluck="prospect", limit=50000))
    rows = frappe.get_all("Sales Prospect", filters={
        "company": company, "review_status": "Approved", "do_not_contact": 0, "website": ["is", "set"],
        "merged_into": ["is", "not set"], "modified": ["<", add_days(nowdate(), -STALE_DAYS)]},
        fields=["name", "buying_signal_score"], order_by="modified asc", limit=BATCH * 3)
    picked = [r for r in rows if r.name not in busy][:BATCH]
    for row in picked:
        frappe.db.set_value("Sales Prospect", row.name, {"previous_buying_score": row.buying_signal_score or 0,
                                                         "signal_checked_on": now_datetime(), "signal_seen": 0},
                            update_modified=False)
    if picked:
        enqueue_research(company, [r.name for r in picked])
    log_activity(company, "signals_recheck", None, f"Re-checking {len(picked)} approved lead(s) for new signals",
                 actor_type="agent", agent="Research", policy_outcome="automatic (research only)")
    return f"{len(picked)} lead(s) re-checked"


def new_signals(company: str, limit: int = 20) -> list[dict]:
    import frappe

    if not frappe.db.has_column("Sales Prospect", "signal_checked_on"):
        return []
    rows = frappe.get_all("Sales Prospect", filters={"company": company, "signal_seen": 0,
                                                     "signal_checked_on": ["is", "set"]},
                          fields=["name", "business_name", "city", "buying_signal_score", "previous_buying_score"],
                          limit=500)
    return [r for r in rows if signal_raised(r.previous_buying_score, r.buying_signal_score)][:limit]


def mark_seen(company: str, prospects: list[str]) -> int:
    import frappe

    for name in prospects:
        if frappe.db.get_value("Sales Prospect", name, "company") == company:
            frappe.db.set_value("Sales Prospect", name, "signal_seen", 1, update_modified=False)
    return len(prospects)
