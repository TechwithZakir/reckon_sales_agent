"""Company isolation for the Sales Agent's own DocTypes.

Every Sales Agent record has a standard ``company`` field, so the platform's
tenant hooks (``reckon_saas_platform.tenant_security``) filter lists and check
document access. This module adds what the platform cannot know: links to
other Company-owned records (CRM leads, prospects, campaigns) must stay in the
record's own Company.
"""

from __future__ import annotations

import frappe

from reckon_sales_agent.crm_tenancy import assert_links_in_company


def validate_company_document(doc, method=None) -> None:
    """``validate`` for Sales Agent DocTypes."""
    from reckon_saas_platform.tenant_security import (
        validate_tenant_company_immutable,
        validate_tenant_owned_doc,
    )

    if frappe.session.user == "Guest" and doc.flags.ignore_permissions:
        # System writes from Guest endpoints (unsubscribe links): the record's
        # Company comes from the record it belongs to, never from the request.
        if not doc.get("company"):
            frappe.throw(frappe._("Company is required."), frappe.PermissionError)
        validate_tenant_company_immutable(doc)
    else:
        validate_tenant_owned_doc(doc)
    assert_links_in_company(doc, doc.get("company"))


def current_company() -> str:
    """The session user's Company; raises for users without exactly one."""
    from reckon_saas_platform.tenant_security import require_tenant, user_can_bypass_tenant

    if user_can_bypass_tenant():
        company = frappe.form_dict.get("company") or frappe.defaults.get_user_default("Company")
        if not company:
            frappe.throw(frappe._("Choose a Company."), frappe.ValidationError)
        return company
    return require_tenant().company


def is_system_actor() -> bool:
    from reckon_saas_platform.tenant_security import user_can_bypass_tenant

    return frappe.session.user in ("Administrator", "Guest") or user_can_bypass_tenant()


def protect_fields(doc, fields, new_values: dict | None = None) -> None:
    """Server-managed fields: tenant users cannot set them through forms or the API.

    Services change them with ``db_set``/``ignore_permissions`` as the system;
    a tenant save keeps the stored values (or ``new_values`` on insert).
    """
    if is_system_actor() or doc.flags.ignore_permissions:
        return
    if doc.is_new():
        for field in fields:
            doc.set(field, (new_values or {}).get(field))
        return
    for field in fields:
        doc.set(field, doc.get_db_value(field))


def get_tenant_doc(doctype: str, name: str, ptype: str = "read"):
    """Load a Sales Agent record after checking the user may ``ptype`` it."""
    doc = frappe.get_doc(doctype, name)
    doc.check_permission(ptype)
    return doc
