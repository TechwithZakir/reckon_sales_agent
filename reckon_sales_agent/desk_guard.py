"""Desk navigation boundary for Sales Agent tenant users.

Runs as ``before_request`` after the platform subscription gate and never
writes. Tenant users of the Sales Agent may open its pages and DocTypes in
Desk (plus whatever their other subscribed modules allow); other Desk routes
redirect to the Sales Agent home. The CRM app at ``/crm`` is not a Desk route
and stays reachable. Data isolation does not depend on this guard: the
Company permission hooks enforce it on every read and write.
"""

from __future__ import annotations

from urllib.parse import unquote

import frappe

from reckon_sales_agent.constants import (
    ALLOWED_DOCTYPES,
    ALLOWED_PAGES,
    HOME_ROUTE,
    LOOKUP_ONLY_DOCTYPES,
    MODULE_KEY,
)

DESK_PREFIXES = ("/app", "/desk")


def get_scope(user: str | None = None) -> set[str] | None:
    """Desk routes the user may open, or None when the user is not a Sales Agent tenant."""
    user = user or frappe.session.user
    if not user or user in {"Guest", "Administrator"}:
        return None
    from reckon_saas_platform.saas import get_company_module_keys
    from reckon_saas_platform.tenant_security import get_user_companies, user_can_bypass_tenant

    if user_can_bypass_tenant(user):
        return None
    companies = get_user_companies(user)
    if len(companies) != 1:
        return None
    modules = get_company_module_keys(companies[0])
    if MODULE_KEY not in modules:
        return None
    pages, doctypes = set(ALLOWED_PAGES), set(ALLOWED_DOCTYPES) - LOOKUP_ONLY_DOCTYPES
    from reckon_saas_platform.module_registry import get_saas_modules

    for module in get_saas_modules():
        if module.get("key") in modules and module.get("key") != MODULE_KEY:
            pages.update(module.get("desk_pages") or [])
            doctypes.update(module.get("desk_doctypes") or [])
    return pages | {frappe.scrub(dt).replace("_", "-") for dt in doctypes} | {"query-report"}


def restrict_sales_agent_desk_request() -> None:
    """``before_request`` hook."""
    frappe.flags.sales_agent_redirect = None
    if getattr(frappe.flags, "saas_gate_blocked", False):
        return
    request = getattr(frappe.local, "request", None)
    path = (request.path or "") if request else ""
    if not path.startswith(DESK_PREFIXES):
        return
    scope = get_scope()
    if scope is None:
        return
    route = unquote(path.split("/", 3)[2]) if path.count("/") >= 2 else ""
    if not route or route not in scope:
        frappe.flags.sales_agent_redirect = HOME_ROUTE


def redirect_sales_agent_desk_response(response, request) -> None:
    """``after_request`` hook: the subscription gate's redirect always wins."""
    location = getattr(frappe.flags, "sales_agent_redirect", None)
    if not location or response is None or getattr(frappe.flags, "saas_gate_redirect", None):
        return
    response.status_code = 302
    response.headers["Location"] = location
    response.set_data(b"")


def get_user_home_page(user: str):
    """``get_website_user_home_page`` hook, chained with other modules' hooks.

    Frappe only calls the last registered hook, so each module chains to the
    others. The flag stops another chaining module from calling back into this
    one while it is chaining (which would recurse forever).
    """
    if getattr(frappe.flags, "sales_agent_home_chain", False):
        return None
    if get_scope(user) is not None:
        from reckon_saas_platform.saas_gate import is_user_gated

        return "reckonerp-subscription" if is_user_gated(user) else HOME_ROUTE.lstrip("/")
    own = "reckon_sales_agent.desk_guard.get_user_home_page"
    frappe.flags.sales_agent_home_chain = True
    try:
        for hook in frappe.get_hooks("get_website_user_home_page") or []:
            if hook != own:
                result = frappe.get_attr(hook)(user)
                if result:
                    return result
    finally:
        frappe.flags.sales_agent_home_chain = False
    return None
