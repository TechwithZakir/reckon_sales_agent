"""Settings, SaaS entitlement, plan quotas and the audit trail.

Every billable or outbound operation calls :func:`assert_entitled` and
:func:`reserve` on the server; nothing here trusts client-supplied values.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import nowdate

from reckon_sales_agent.constants import (
    DEFAULT_LIMITS,
    MODULE_KEY,
    PLATFORM_SETTINGS,
    USAGE_LIMIT_FIELDS,
)


class QuotaExceeded(frappe.ValidationError):
    pass


class NotEntitled(frappe.PermissionError):
    pass


def platform_settings():
    return frappe.get_cached_doc(PLATFORM_SETTINGS)


def get_settings(company: str):
    """The Company's Sales Agent Settings, created with safe defaults if missing."""
    if not frappe.db.exists("Sales Agent Settings", company):
        frappe.get_doc({"doctype": "Sales Agent Settings", "company": company}).insert(ignore_permissions=True)
    return frappe.get_doc("Sales Agent Settings", company)


def assert_entitled(company: str) -> None:
    """Fail closed unless the Company has an active Sales Agent subscription."""
    try:
        from reckon_saas_platform.saas import is_subscription_active
    except ImportError:
        frappe.throw(_("Reckon SaaS Platform is required for the Sales Agent."), NotEntitled)
    try:
        active = is_subscription_active(company, saas_module=MODULE_KEY)
    except Exception:
        frappe.log_error(title="Sales Agent entitlement check failed")
        active = False
    if not active:
        frappe.throw(_("{0} has no active Sales Agent subscription.").format(company), NotEntitled)
    if not get_settings(company).enabled:
        frappe.throw(_("The Sales Agent is disabled for {0}.").format(company), NotEntitled)


def current_period() -> str:
    return nowdate()[:7]


def get_limit(company: str, usage_type: str) -> int:
    field = USAGE_LIMIT_FIELDS[usage_type]
    value = get_settings(company).get(field)
    if not value:
        value = platform_settings().get(field) or DEFAULT_LIMITS[field]
    return int(value)


def get_used(company: str, usage_type: str, period: str | None = None) -> int:
    rows = frappe.get_all(
        "Sales Usage Ledger",
        filters={"company": company, "usage_type": usage_type, "period": period or current_period()},
        fields=["sum(quantity) as total"],
    )
    return int((rows[0].total if rows else 0) or 0)


def remaining(company: str, usage_type: str) -> int:
    return max(get_limit(company, usage_type) - get_used(company, usage_type), 0)


def reserve(company: str, usage_type: str, quantity: int = 1, reference=None) -> None:
    """Record usage, refusing it when it would exceed the monthly plan limit."""
    if quantity <= 0:
        return
    if get_used(company, usage_type) + quantity > get_limit(company, usage_type):
        frappe.throw(
            _("Monthly {0} limit reached for {1}.").format(_(usage_type), company), QuotaExceeded
        )
    frappe.get_doc(
        {
            "doctype": "Sales Usage Ledger",
            "company": company,
            "usage_type": usage_type,
            "period": current_period(),
            "quantity": quantity,
            "reference_doctype": reference.doctype if reference else None,
            "reference_name": reference.name if reference else None,
        }
    ).insert(ignore_permissions=True)


def usage_summary(company: str) -> dict:
    return {
        usage_type: {"used": get_used(company, usage_type), "limit": get_limit(company, usage_type)}
        for usage_type in USAGE_LIMIT_FIELDS
    }


def log_activity(company: str, action: str, reference=None, summary: str = "", actor_type: str = "user") -> None:
    """Append-only audit record. Never pass secrets or full contact values."""
    frappe.get_doc(
        {
            "doctype": "Sales Agent Activity",
            "company": company,
            "action": action,
            "actor_type": actor_type,
            "actor": frappe.session.user,
            "reference_doctype": reference.doctype if reference else None,
            "reference_name": reference.name if reference else None,
            "summary": (summary or "")[:1000],
            "correlation_id": getattr(frappe.local, "sales_agent_correlation_id", None),
        }
    ).insert(ignore_permissions=True)
