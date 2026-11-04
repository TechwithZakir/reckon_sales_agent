"""Brevo's transactional webhook: bounces, spam reports and unsubscribes reach the do-not-contact list.

Brevo does not sign its webhook payloads, so the request must carry the Company's webhook secret in the notify URL
(``?company=<Company>&key=<secret>``). The check is constant-time, and a Company with no secret set refuses everything.
"""

import hmac
import json

import frappe
from werkzeug.wrappers import Response

from reckon_sales_agent.api_twilio import _company_settings, _deny


@frappe.whitelist(allow_guest=True, methods=["POST"])
def events(company: str | None = None, key: str | None = None):
    from reckon_sales_agent.agents.engagement import normalize_email_events
    from reckon_sales_agent.agents.engagement_agent import apply_email_event
    from reckon_sales_agent.providers.brevo import normalize_events

    settings = _company_settings(company)
    expected = settings.get_password("brevo_webhook_secret", raise_exception=False) if settings and settings.get(
        "brevo_webhook_secret") else ""
    if not expected or not key or not hmac.compare_digest(str(key), expected):
        return _deny()
    try:
        items = json.loads(frappe.request.get_data() or b"[]")
    except ValueError:
        return Response("invalid JSON", status=400, mimetype="text/plain")
    frappe.set_user("Administrator")
    handled = 0
    for event in normalize_email_events(normalize_events(items))[:1000]:
        try:
            handled += 1 if apply_email_event(event) else 0
            frappe.db.commit()
        except Exception:
            frappe.db.rollback()
            frappe.log_error(title="Sales Agent Brevo event failed")
    return Response(json.dumps({"ok": True, "handled": handled}), mimetype="application/json")
