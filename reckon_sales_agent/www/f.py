"""The short address of a hosted signup form: /f/<key> sends the visitor to the form's page."""

import frappe

no_cache = 1


def get_context(context):
    slug = "".join(ch for ch in str(frappe.form_dict.get("slug") or "").lower()[:20] if ch.isalnum())
    if not slug:
        raise frappe.DoesNotExistError
    frappe.local.flags.redirect_location = f"/api/method/reckon_sales_agent.api_capture.page?slug={slug}"
    raise frappe.Redirect
