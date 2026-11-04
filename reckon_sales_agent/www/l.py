"""The short link in a campaign message: /l/<code> records the click and sends the visitor on."""

import frappe

no_cache = 1


def get_context(context):
    from reckon_sales_agent.campaigns.track_links import clicked

    code = str(frappe.form_dict.get("code") or "")[:32]
    destination = None
    try:
        destination = clicked(code, frappe.get_request_header("User-Agent"))
    except Exception:
        frappe.db.rollback()
        frappe.log_error(title="Sales Agent click tracking failed")
    if not destination:
        raise frappe.DoesNotExistError
    frappe.local.flags.redirect_location = destination
    raise frappe.Redirect
