"""Do-not-contact list, checked before discovery storage and before every send."""

from __future__ import annotations

import frappe

from reckon_sales_agent.discovery.normalize import value_hash


def is_suppressed(company: str, *, email: str | None = None, phone: str | None = None,
                  website: str | None = None, channel: str = "Email") -> bool:
    hashes = []
    if email:
        hashes.append(value_hash("Email", email))
        hashes.append(value_hash("Domain", email.split("@")[-1]))
    if phone:
        hashes.append(value_hash("Phone", phone))
    if website:
        hashes.append(value_hash("Domain", website))
    hashes = [h for h in hashes if h]
    if not hashes:
        return False
    return bool(frappe.db.exists("Sales Suppression Entry", {
        "company": company,
        "value_hash": ["in", hashes],
        "active": 1,
        "channel": ["in", ["All", channel]],
    }))


def suppress(company: str, entry_type: str, value: str, reason: str, source: str) -> None:
    """Idempotently add an active suppression entry."""
    digest = value_hash(entry_type, value)
    if not digest:
        return
    existing = frappe.db.get_value("Sales Suppression Entry", {"company": company, "value_hash": digest})
    if existing:
        frappe.db.set_value("Sales Suppression Entry", existing, {"active": 1, "reason": reason})
        return
    frappe.get_doc({
        "doctype": "Sales Suppression Entry",
        "company": company,
        "entry_type": entry_type,
        "value": value,
        "reason": reason,
        "channel": "All",
        "source": source,
    }).insert(ignore_permissions=True)
