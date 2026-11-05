"""One-click unsubscribe headers on campaign email (RFC 8058), for every way an email can leave.

The provider paths (Brevo, SendGrid) put the headers in their API request. Mail sent through the site's own email account
is written into the Email Queue first, so a hook adds the headers to the queued message just before it is saved.
"""

from __future__ import annotations

import frappe
from frappe.utils import get_url

from reckon_sales_agent.campaigns import pacing


def unsubscribe_url_for(message) -> str:
    """The recipient's own unsubscribe link (the one in the email footer), or "" when the message has no campaign member."""
    member = message.get("member")
    token = frappe.db.get_value("Sales Campaign Member", member, "unsubscribe_token") if member else None
    return get_url(f"/api/method/reckon_sales_agent.api.unsubscribe?token={token}") if token else ""


def headers_for(message) -> dict:
    return pacing.unsubscribe_headers(unsubscribe_url_for(message))


def add_to_queued_email(doc, method=None) -> None:
    """Email Queue before_insert: campaign email sent through the site's own account carries the headers too."""
    if not doc.get("message"):
        return
    reference_doctype, reference_name = doc.get("reference_doctype"), doc.get("reference_name")
    if reference_doctype != "Sales Outreach Message" and doc.get("communication"):
        row = frappe.db.get_value("Communication", doc.communication, ["reference_doctype", "reference_name"], as_dict=True)
        reference_doctype, reference_name = (row.reference_doctype, row.reference_name) if row else (None, None)
    if reference_doctype != "Sales Outreach Message" or not reference_name:
        return
    try:
        message = frappe.db.get_value("Sales Outreach Message", reference_name, ["member", "is_reply"], as_dict=True)
        if not message or message.get("is_reply"):
            return  # an answer to someone who wrote to us is not bulk mail
        doc.message = pacing.add_headers_to_mime(doc.message, headers_for(frappe._dict(member=message.member)))
    except Exception:
        frappe.log_error(title="Sales Agent unsubscribe header failed")  # the email must still go out
