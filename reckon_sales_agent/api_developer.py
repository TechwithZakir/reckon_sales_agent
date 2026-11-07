"""Developers tab of Capture Studio: outgoing webhooks, and where the API lives. Everything is limited to the session's Company."""

from __future__ import annotations

import secrets

import frappe
from frappe import _

from reckon_sales_agent.api_studio import _can_manage
from reckon_sales_agent.campaigns import webhook_events as events
from reckon_sales_agent.campaigns import webhook_service
from reckon_sales_agent.tenant import current_company, get_tenant_doc
from reckon_sales_agent.usage import assert_entitled

PUBLIC_CALLS = [
    ["GET", "api_public.ping", "Check the key works"],
    ["POST", "api_public.person_upsert", "Add or update a person (email or phone, name, tags, consent_statement)"],
    ["GET", "api_public.person", "One person by email or phone"],
    ["POST", "api_public.person_tags", "Add or remove tags (email, add, remove)"],
    ["POST", "api_public.person_unsubscribe", "Stop all campaign email to an address"],
    ["GET", "api_public.segments", "Your segments"],
    ["GET", "api_public.segment_people", "The people in a segment (segment, limit)"],
    ["GET", "api_public.forms", "Your signup forms"],
    ["GET", "api_public.automations", "Your automations"],
    ["POST", "api_automation.trigger", "Start an automation for a person (automation, email or phone, consent_statement)"],
    ["GET", "api_public.events", "What happened to messages (since, type, limit)"],
    ["POST", "api_public.check_email", "Check one address (Valid, Risky, Invalid)"],
]


def _require_manager() -> None:
    if not _can_manage():
        frappe.throw(_("Ask a Sales Agent admin or manager to do this."), frappe.PermissionError)


@frappe.whitelist()
def overview() -> dict:
    """Paths only: the page builds full addresses from the domain it is open on, so a new domain needs no change."""
    company = current_company()
    assert_entitled(company)
    return {"calls": PUBLIC_CALLS, "base": "/api/method/reckon_sales_agent.", "events": events.EVENTS, "mcp": "/api/method/reckon_sales_agent.api_mcp.rpc",
            "can_manage": _can_manage()}


@frappe.whitelist()
def webhooks() -> list[dict]:
    company = current_company()
    assert_entitled(company)
    rows = frappe.get_all("Sales Webhook Subscription", filters={"company": company},
                          fields=["name", "description", "url", "active", "events", "last_status", "last_error", "last_sent_at", "failures"],
                          order_by="modified desc", limit=100)
    for row in rows:
        row["last_sent_at"] = str(row.last_sent_at or "")
        row["events"] = events.clean_events(row.events)
    return rows


@frappe.whitelist(methods=["POST"])
def save_webhook(data) -> dict:
    """Create or change a subscription. A new one gets a signing secret, shown once in the answer."""
    _require_manager()
    import json

    company = current_company()
    assert_entitled(company)
    values = data if isinstance(data, dict) else json.loads(data or "{}")
    doc = get_tenant_doc("Sales Webhook Subscription", values["name"], "write") if values.get("name") else frappe.new_doc("Sales Webhook Subscription")
    shown = None
    if doc.is_new():
        doc.company = company
        shown = secrets.token_hex(24)
        doc.secret = shown
    doc.description = values.get("description")
    doc.url = values.get("url")
    doc.events = ", ".join(events.clean_events(values.get("events")))
    doc.active = 1 if values.get("active", 1) in (1, "1", True, "true") else 0
    doc.save()
    return {"name": doc.name, "secret": shown}


@frappe.whitelist(methods=["POST"])
def new_secret(name: str) -> str:
    """A new signing secret (the old one stops working). Shown once."""
    _require_manager()
    doc = get_tenant_doc("Sales Webhook Subscription", name, "write")
    shown = secrets.token_hex(24)
    doc.secret = shown
    doc.save()
    return shown


@frappe.whitelist(methods=["POST"])
def delete_webhook(name: str) -> None:
    _require_manager()
    frappe.delete_doc("Sales Webhook Subscription", get_tenant_doc("Sales Webhook Subscription", name, "delete").name)


@frappe.whitelist(methods=["POST"])
def test_webhook(name: str) -> str:
    """Send one test call now and say what came back."""
    _require_manager()
    get_tenant_doc("Sales Webhook Subscription", name, "write")
    return webhook_service.send_test(name)
