"""How often a periodic agent runs inside the hourly orchestrator (daily or weekly), per Company."""

from __future__ import annotations

DAY = 24
WEEK = 7 * 24


def _key(company: str, job: str) -> str:
    return f"reckon_sales_agent:due:{company}:{job}"


def due(company: str, job: str) -> bool:
    import frappe

    return not frappe.cache.get_value(_key(company, job))


def mark_done(company: str, job: str, hours: int) -> None:
    import frappe

    frappe.cache.set_value(_key(company, job), 1, expires_in_sec=int(hours * 3600) - 300)
