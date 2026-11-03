"""WhatsApp Embedded Signup: a customer connects their own WhatsApp number in one step, with no tokens copied by hand.

The customer signs in with Facebook inside the Integrations page and picks or creates a number. Meta then gives us a
short-lived code plus the WhatsApp Business Account (WABA) and phone number IDs. This module turns that into a
WhatsApp Account for the customer's Company, subscribes the WABA to our app so its messages reach the webhook, and
points the Company's WhatsApp settings at the new account.

Needs the system provider's setup: a Meta app that is a Tech Provider app, with an Embedded Signup configuration, and
the configuration ID in Sales Agent Platform Settings.
"""

from __future__ import annotations

import re

API = "https://graph.facebook.com/v23.0/"
ID = re.compile(r"^\d{5,25}$")


def check_ids(code: str, waba_id: str, phone_number_id: str) -> None:
    """Raise a ValidationError when the values Meta sent us are not what a signup returns."""
    import frappe
    from frappe import _

    if not (code or "").strip() or len(code) > 500:
        frappe.throw(_("The sign-in code is missing. Start the WhatsApp connection again."))
    if not ID.match(waba_id or "") or not ID.match(phone_number_id or ""):
        frappe.throw(_("Meta did not return the WhatsApp account and number. Finish the steps in Meta, then try again."))


def exchange_code(code: str) -> str:
    """The code becomes a business token for the customer's WhatsApp Business Account (valid for us to use)."""
    import frappe

    from reckon_sales_agent.agents.social_connect import _get
    from reckon_sales_agent.usage import platform_settings

    platform = platform_settings()
    secret = platform.get_password("meta_app_secret", raise_exception=False) if platform.get("meta_app_secret") else ""
    if not (platform.get("meta_app_id") and secret):
        frappe.throw(frappe._("The system provider has not set up the Meta app yet."))
    data = _get(API + "oauth/access_token", params={"client_id": platform.get("meta_app_id"), "client_secret": secret,
                                                    "code": code})
    token = data.get("access_token")
    if not token:
        frappe.throw(frappe._("Meta did not give a token. Try the WhatsApp connection again."))
    return token


def finish(company: str, code: str, waba_id: str, phone_number_id: str) -> str:
    """Connect a customer's number to their Company. Returns the WhatsApp Account's name."""
    import frappe
    from frappe import _

    from reckon_sales_agent.agents.social_connect import _get
    from reckon_sales_agent.usage import platform_settings

    if "frappe_whatsapp" not in frappe.get_installed_apps():
        frappe.throw(_("Install the Frappe WhatsApp app (frappe_whatsapp) on this site first."))
    check_ids(code, waba_id, phone_number_id)
    taken = frappe.db.get_value("WhatsApp Account", {"phone_id": phone_number_id}, "name")
    if taken:
        owner = frappe.db.get_value("Sales Agent Settings", {"whatsapp_account": taken}, "name")
        if owner and owner != company:
            frappe.throw(_("This WhatsApp number is already connected to another Company."))

    token = exchange_code(code)
    # Our app receives this WABA's messages and status updates (the webhook is set once, on the Meta app).
    _get(API + f"{waba_id}/subscribed_apps", method="POST", params={"access_token": token})

    platform = platform_settings()
    verify = platform.get_password("meta_verify_token", raise_exception=False) if platform.get("meta_verify_token") else ""
    account = taken or frappe.get_doc({
        "doctype": "WhatsApp Account",
        "account_name": f"{company} WhatsApp"[:140],
        "phone_id": phone_number_id,
        "business_id": waba_id,
        "app_id": platform.get("meta_app_id") or "",
        "token": token,
        "webhook_verify_token": verify,
        "status": "Active",
    }).insert(ignore_permissions=True).name
    if taken:  # a number we already know: refresh its token from this signup
        frappe.db.set_value("WhatsApp Account", taken, {"token": token, "business_id": waba_id, "status": "Active"})

    settings = frappe.get_doc("Sales Agent Settings", company)
    settings.whatsapp_account = account
    settings.whatsapp_enabled = 1
    settings.save(ignore_permissions=True)
    return account
