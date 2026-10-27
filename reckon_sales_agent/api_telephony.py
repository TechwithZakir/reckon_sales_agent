"""Telephony endpoints: click-to-call from the Agent Studio, and signed call events from the Company's PBX."""

from __future__ import annotations

import json

import frappe

from reckon_sales_agent.tenant import current_company, get_tenant_doc


@frappe.whitelist()
def call(prospect: str) -> str:
    from reckon_sales_agent.telephony import click_to_call

    doc = get_tenant_doc("Sales Prospect", prospect, "read")
    return click_to_call(current_company(), frappe.session.user, doc.name)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def call_event() -> dict:
    """Call events from the PBX, signed with the Company's call-events secret (header X-Reckon-Signature)."""
    from reckon_sales_agent.agents.engagement import verify_signature
    from reckon_sales_agent.telephony import apply_event

    body = frappe.request.get_data() or b""
    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        frappe.local.response.http_status_code = 400
        return {"ok": False, "error": "invalid JSON"}
    company = str(payload.get("company") or "")
    if not company or not frappe.db.exists("Sales Agent Settings", company):
        frappe.local.response.http_status_code = 401
        return {"ok": False, "error": "unknown company"}
    settings = frappe.get_doc("Sales Agent Settings", company)
    secret = settings.get_password("telephony_webhook_secret", raise_exception=False)
    if not verify_signature(secret, body, frappe.get_request_header("X-Reckon-Signature")):
        frappe.local.response.http_status_code = 401
        return {"ok": False, "error": "invalid signature"}
    frappe.set_user("Administrator")  # verified PBX event: act as the system
    events = payload.get("events") if isinstance(payload.get("events"), list) else [payload]
    written = 0
    for event in events[:100]:
        try:
            apply_event(company, event)
            written += 1
        except Exception:
            frappe.db.rollback()
            frappe.log_error(title="Sales Agent call event failed")
    frappe.db.commit()
    return {"ok": True, "written": written}
