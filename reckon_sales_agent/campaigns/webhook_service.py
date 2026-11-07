"""Outgoing webhooks on the Frappe side: find the Company's subscriptions for an event and deliver to them in the background.

A delivery never slows or breaks the thing that caused it: ``emit`` only queues, and every failure is written on the subscription.
Addresses are checked as public https addresses before each call, redirects are not followed, and a subscription that fails
ten times in a row is switched off.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import now_datetime

from reckon_sales_agent.campaigns import webhook_events as events

CACHE_SECONDS = 60


def _subscriptions(company: str) -> list[dict]:
    key = f"rsa_whk:{company}"
    cached = frappe.cache.get_value(key)
    if cached is not None:
        return cached
    rows = frappe.get_all("Sales Webhook Subscription", filters={"company": company, "active": 1}, fields=["name", "events"], limit=50)
    value = [{"name": r.name, "events": r.events or ""} for r in rows]
    frappe.cache.set_value(key, value, expires_in_sec=CACHE_SECONDS)
    return value


def forget(company: str) -> None:
    frappe.cache.delete_value(f"rsa_whk:{company}")


def emit(company: str, event: str, data: dict) -> int:
    """Queue a delivery to every active subscription of the Company that wants this event. Returns how many were queued."""
    queued = 0
    for sub in _subscriptions(company):
        if events.wants(sub["events"], event):
            frappe.enqueue("reckon_sales_agent.campaigns.webhook_service.deliver", queue="short", enqueue_after_commit=True,
                           subscription=sub["name"], hook_event=event, payload=json.dumps(data, default=str, ensure_ascii=False))
            queued += 1
    return queued


def person_data(prospect: str) -> dict:
    row = frappe.db.get_value("Sales Prospect", prospect, ["email", "phone", "contact_name", "business_name", "tags"], as_dict=True) or {}
    return {"id": prospect, "email": row.get("email") or "", "phone": row.get("phone") or "",
            "name": row.get("contact_name") or row.get("business_name") or "", "tags": row.get("tags") or ""}


def emit_person(company: str, event: str, prospect: str, **extra) -> None:
    """A person-centred event (signup, tag, automation). Never raises: a webhook must not break what happened."""
    try:
        if _subscriptions(company):
            emit(company, event, {"person": person_data(prospect), **extra})
    except Exception:
        frappe.log_error(title="Sales Agent webhook failed to queue", message=f"{event} for {prospect}")


def emit_communication(message, event_type: str) -> None:
    """Called for every communication event; only the ones a subscription wants cost anything."""
    event = events.FROM_COMMUNICATION.get(event_type)
    if not event:
        return
    try:
        if not _subscriptions(message.company):
            return
        emit(message.company, event, {"person": person_data(message.prospect), "message": message.name, "campaign": message.campaign,
                                      "channel": message.get("channel") or "Email", "subject": message.get("subject") or ""})
    except Exception:
        frappe.log_error(title="Sales Agent webhook failed to queue", message=f"{event_type} for {message.name}")


def deliver(subscription: str, hook_event: str, payload: str) -> str:
    """One call. Returns what happened ('200', 'refused', 'failed: Timeout'); it is also stored on the subscription."""
    import requests

    event = hook_event  # (frappe.enqueue reserves the name ``event``)

    from reckon_sales_agent.research.url_safety import validate_url

    sub = frappe.get_doc("Sales Webhook Subscription", subscription)
    if not sub.active:
        return "inactive"
    result = "failed"
    ok = False
    try:
        url = events.safe_url(sub.url)
        if not url:
            raise ValueError("address")
        validate_url(url)
        body = json.dumps({"event": event, "at": str(now_datetime()), "data": json.loads(payload or "{}")}, ensure_ascii=False).encode()
        headers = {"Content-Type": "application/json", "X-Reckon-Event": event}
        secret = sub.get_password("secret", raise_exception=False)
        if secret:
            headers["X-Reckon-Signature"] = events.sign(secret, body)
        response = requests.post(url, data=body, headers=headers, timeout=10, allow_redirects=False)
        ok = 200 <= response.status_code < 300
        result = str(response.status_code)
    except Exception as exc:
        result = f"failed: {type(exc).__name__}"
    failures = 0 if ok else (sub.failures or 0) + 1
    changes = {"last_status": result[:60], "last_sent_at": now_datetime(), "failures": failures,
               "last_error": None if ok else f"{event}: {result}"[:140]}
    if failures >= events.MAX_FAILURES:
        changes["active"] = 0
        forget(sub.company)
    sub.db_set(changes)
    frappe.db.commit()
    return result


def send_test(subscription: str) -> str:
    sub = frappe.get_doc("Sales Webhook Subscription", subscription)
    return deliver(sub.name, "test", json.dumps({"message": "This is a test from Reckon Sales Agent."}))
