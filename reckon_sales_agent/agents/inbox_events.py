"""Live inbox: tell the Company's team the moment a conversation changes, so Conversations updates without a reload.

``notify_inbox`` publishes one realtime event per team member. The page refreshes the affected lead, and keeps a
slow poll only as a fallback if the live connection drops. A failed notification never fails the change itself.
"""

from __future__ import annotations

EVENT = "rsa_inbox"


def recipients(company: str) -> list[str]:
    import frappe

    if not frappe.db.exists("DocType", "Tenant User Assignment"):
        return []
    return sorted(set(frappe.get_all("Tenant User Assignment", filters={"company": company, "active": 1},
                                     pluck="user", limit=500)))


def notify_inbox(company: str | None, prospect: str | None = None) -> None:
    import frappe

    if not company:
        return
    for user in recipients(company):
        try:
            frappe.publish_realtime(EVENT, {"company": company, "prospect": prospect}, user=user, after_commit=True)
        except Exception:  # realtime is a convenience: the change is already saved
            frappe.log_error(title="Sales Agent live inbox notification failed")
