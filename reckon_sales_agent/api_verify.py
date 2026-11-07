"""Clean list: address checking for Capture Studio. Everything is limited to the session's Company."""

from __future__ import annotations

import frappe
from frappe import _

from reckon_sales_agent.api_studio import _can_manage
from reckon_sales_agent.campaigns import verify, verify_service
from reckon_sales_agent.tenant import current_company
from reckon_sales_agent.usage import assert_entitled, get_settings


@frappe.whitelist()
def summary() -> dict:
    company = current_company()
    assert_entitled(company)
    settings = get_settings(company)
    provider = settings.get("verify_provider") or "Built-in only"
    has_key = bool(settings.get("zerobounce_api_key"))
    return {**verify_service.summary(company), "provider": provider, "provider_ready": provider == "Built-in only" or has_key,
            "risky": verify_service.examples(company, verify.RISKY, 15), "invalid": verify_service.examples(company, verify.INVALID, 15)}


@frappe.whitelist(methods=["POST"])
def check_all(scope: str = "unchecked") -> int:
    """Queue a background check of the Company's addresses. Returns how many are waiting."""
    if not _can_manage():
        frappe.throw(_("Ask a Sales Agent admin or manager to do this."), frappe.PermissionError)
    company = current_company()
    assert_entitled(company)
    return verify_service.start(company, scope)


@frappe.whitelist(methods=["POST"])
def check_one(email: str) -> dict:
    """Check a single address now, without saving it anywhere."""
    company = current_company()
    assert_entitled(company)
    return verify_service.check_email(email, get_settings(company))
