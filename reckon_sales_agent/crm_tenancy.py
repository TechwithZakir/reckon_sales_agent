"""Company (tenant) ownership for native Frappe CRM records.

Reckon SaaS tenants are Companies on one shared site, but Frappe CRM's own
DocTypes carry no Company. This module adds a server-managed ``rsa_company``
field to them and enforces it through permission hooks, so one tenant can
never list, open, link or modify another tenant's CRM records.

Scoping is active only when ``reckon_saas_platform`` is installed. Without the
parent platform (a plain development site) CRM behaves exactly as upstream.
"""

from __future__ import annotations

import frappe
from frappe import _

COMPANY_FIELD = "rsa_company"

# DocType -> field the Company column is placed after.
SCOPED_DOCTYPES = {
    "CRM Lead": "status",
    "CRM Deal": "status",
    "CRM Organization": "organization_name",
    "CRM Task": "status",
}

# Links whose target must belong to the same Company as the record itself.
SCOPED_LINKS = {
    "CRM Deal": {"organization": "CRM Organization", "lead": "CRM Lead"},
}

WRITE_PERMISSIONS = {"create", "write", "delete", "submit", "cancel", "amend"}


def is_scoping_active() -> bool:
    return "reckon_saas_platform" in frappe.get_installed_apps()


def _tenant_security():
    from reckon_saas_platform import tenant_security

    return tenant_security


def _can_bypass(user: str | None = None) -> bool:
    return _tenant_security().user_can_bypass_tenant(user or frappe.session.user)


def get_tenant_company(user: str | None = None) -> str | None:
    """The user's single active Company, or None when it cannot be resolved."""
    tenant_security = _tenant_security()
    try:
        return tenant_security.require_tenant(user=user or frappe.session.user).company
    except tenant_security.TenantResolutionError:
        return None


def get_query_conditions(user: str | None = None, doctype: str | None = None) -> str:
    """``permission_query_conditions`` for scoped CRM DocTypes.

    Fails closed: a tenant user without one resolvable Company sees nothing, and
    so does everyone if the Company column is missing.
    """
    if doctype not in SCOPED_DOCTYPES or not is_scoping_active():
        return ""
    user = user or frappe.session.user
    if _can_bypass(user):
        return ""
    company = get_tenant_company(user)
    if not company or not frappe.db.has_column(doctype, COMPANY_FIELD):
        return "1=0"
    return f"`tab{doctype}`.`{COMPANY_FIELD}` = {frappe.db.escape(company)}"


def has_permission(
    doc,
    user: str | None = None,
    permission_type: str | None = None,
    ptype: str | None = None,
    debug: bool = False,
) -> bool:
    """``has_permission`` for scoped CRM DocTypes."""
    if doc.doctype not in SCOPED_DOCTYPES or not is_scoping_active():
        return True
    user = user or frappe.session.user
    if _can_bypass(user):
        return True
    company = get_tenant_company(user)
    if not company:
        return False
    if doc.is_new():
        return doc.get(COMPANY_FIELD) in (None, "", company)
    stored = frappe.db.get_value(doc.doctype, doc.name, COMPANY_FIELD)
    if stored != company:
        return False
    permission_type = ptype or permission_type
    if permission_type in WRITE_PERMISSIONS:
        return doc.get(COMPANY_FIELD) == company
    return True


def _record_company(doctype: str, name: str | None) -> str | None:
    if not name or not frappe.db.exists(doctype, name):
        return None
    return frappe.db.get_value(doctype, name, COMPANY_FIELD)


def _inherited_company(doc) -> str | None:
    """Company implied by the record's parent (Task reference, Deal lead/organization)."""
    if doc.doctype == "CRM Task":
        if doc.get("reference_doctype") in SCOPED_DOCTYPES:
            return _record_company(doc.reference_doctype, doc.get("reference_docname"))
        return None
    for fieldname, target in SCOPED_LINKS.get(doc.doctype, {}).items():
        company = _record_company(target, doc.get(fieldname))
        if company:
            return company
    return None


def bind_company(doc, method=None) -> None:
    """``before_insert``: stamp the creator's Company on a new CRM record.

    Tenant users always get their own Company; a different value is rejected.
    System users and background jobs (email-to-lead, imports) inherit the
    parent record's Company when there is one, otherwise the record stays
    unowned and therefore invisible to every tenant.
    """
    if doc.doctype not in SCOPED_DOCTYPES or not is_scoping_active():
        return
    if _can_bypass():
        if not doc.get(COMPANY_FIELD):
            doc.set(COMPANY_FIELD, _inherited_company(doc))
        return
    company = get_tenant_company()
    if not company:
        frappe.throw(_("You have no active Company assignment."), frappe.PermissionError)
    if doc.get(COMPANY_FIELD) and doc.get(COMPANY_FIELD) != company:
        frappe.throw(_("CRM records can only be created for your own Company."), frappe.PermissionError)
    doc.set(COMPANY_FIELD, company)


def validate_company(doc, method=None) -> None:
    """``validate``: Company is immutable once set and linked records must share it."""
    if doc.doctype not in SCOPED_DOCTYPES or not is_scoping_active():
        return
    company = doc.get(COMPANY_FIELD)
    if not doc.is_new():
        stored = frappe.db.get_value(doc.doctype, doc.name, COMPANY_FIELD)
        if stored and stored != company:
            frappe.throw(_("Company cannot be changed after it is set."), frappe.PermissionError)
        if not stored and company and not _can_bypass():
            frappe.throw(_("Only administrators can assign a Company to an unowned record."),
                         frappe.PermissionError)
    links = dict(SCOPED_LINKS.get(doc.doctype, {}))
    if doc.doctype == "CRM Task" and doc.get("reference_doctype") in SCOPED_DOCTYPES:
        links["reference_docname"] = doc.reference_doctype
    for fieldname, target in links.items():
        value = doc.get(fieldname)
        if value and _record_company(target, value) != company:
            frappe.throw(
                _("{0} {1} belongs to a different Company.").format(_(target), value),
                frappe.PermissionError,
            )


def find_organization(organization_name: str, company: str | None) -> str | None:
    """Tenant-scoped replacement for CRM's global organization-name lookup."""
    if not organization_name:
        return None
    return frappe.db.get_value(
        "CRM Organization",
        {"organization_name": organization_name, COMPANY_FIELD: company},
        "name",
    )


def unique_organization_name(organization_name: str, company: str | None) -> str:
    """Document name for a new CRM Organization.

    CRM names organizations after their name, which is unique site-wide. A second
    tenant's "Acme Ltd" gets a Company-qualified name instead of a duplicate
    error that would reveal the other tenant's customer.
    """
    if not frappe.db.exists("CRM Organization", organization_name) or not company:
        return organization_name
    suffix = frappe.db.get_value("Company", company, "abbr") or company
    candidate = f"{organization_name} - {suffix}"
    counter = 2
    while frappe.db.exists("CRM Organization", candidate):
        candidate = f"{organization_name} - {suffix}-{counter}"
        counter += 1
    return candidate
