"""Backend for the Conversations page: every lead's thread across channels, and AI replies to approve."""

from __future__ import annotations

import json

import frappe
from frappe import _

from reckon_sales_agent.tenant import current_company, get_tenant_doc


@frappe.whitelist()
def threads() -> list[dict]:
    from reckon_sales_agent.agents.omni import threads as list_threads

    return list_threads(current_company())


@frappe.whitelist()
def thread(prospect: str) -> dict:
    from reckon_sales_agent.agents.omni import timeline

    doc = get_tenant_doc("Sales Prospect", prospect, "read")
    drafts = frappe.get_all("Sales Outreach Message", filters={"prospect": prospect, "status": "Draft"},
                            fields=["name", "channel", "recipient", "subject", "body", "error", "is_reply"],
                            order_by="creation desc", limit=10)
    return {
        "prospect": {k: doc.get(k) for k in ("name", "business_name", "email", "phone", "city", "website",
                                             "crm_lead", "source_type", "consent_source", "do_not_contact")},
        "timeline": timeline(prospect),
        "drafts": drafts,
    }


@frappe.whitelist()
def suggest(prospect: str, instruction: str | None = None) -> str:
    from reckon_sales_agent.agents.omni import draft_reply
    from reckon_sales_agent.usage import assert_entitled

    doc = get_tenant_doc("Sales Prospect", prospect, "write")
    assert_entitled(doc.company)
    return draft_reply(doc.name, reason="the salesperson asked for a reply", instruction=(instruction or "")[:500])


@frappe.whitelist()
def approve_and_send(message: str) -> str:
    """Approve one draft and send it now (within limits; dry run when sending is off)."""
    from reckon_sales_agent import api
    from reckon_sales_agent.campaigns.engine import send_message

    doc = get_tenant_doc("Sales Outreach Message", message, "write")
    api.approve_messages(json.dumps([doc.name]))
    sent = send_message(frappe.get_doc("Sales Outreach Message", doc.name))
    status = frappe.db.get_value("Sales Outreach Message", doc.name, "status")
    if not sent and status == "Approved":
        return _("Approved; it goes out when the daily limit allows.")
    return status


@frappe.whitelist()
def discard(message: str) -> None:
    doc = get_tenant_doc("Sales Outreach Message", message, "write")
    if doc.status != "Draft":
        frappe.throw(_("Only drafts can be discarded."))
    doc.db_set({"status": "Cancelled", "error": "Discarded by a person"})
