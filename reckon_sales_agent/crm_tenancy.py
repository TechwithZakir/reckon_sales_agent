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
    "Contact": "company_name",
    "CRM Task": "status",
    "FCRM Note": "title",
    "CRM Call Log": "status",
}

# Records attached to a Lead or Deal through reference_doctype/reference_docname.
REFERENCE_DOCTYPES = frozenset({"CRM Task", "FCRM Note", "CRM Call Log"})

# Links whose target must belong to the same Company as the record itself.
SCOPED_LINKS = {
    "CRM Deal": {"organization": "CRM Organization", "lead": "CRM Lead"},
    "CRM Call Log": {"note": "FCRM Note"},
}

# Company owner of non-CRM records a Contact can be linked to. Distribution adds
# ``rd_company`` to Customer and Supplier; the column is checked before use.
EXTERNAL_COMPANY_FIELDS = {"Customer": "rd_company", "Supplier": "rd_company"}

WRITE_PERMISSIONS = {"create", "write", "delete", "submit", "cancel", "amend"}


def is_scoping_active() -> bool:
    return "reckon_saas_platform" in frappe.get_installed_apps()


def _tenant_security():
    from reckon_saas_platform import tenant_security

    return tenant_security


def _can_bypass(user: str | None = None) -> bool:
    return _tenant_security().user_can_bypass_tenant(user or frappe.session.user)


def _is_system_actor(user: str | None = None) -> bool:
    """Administrators, plus Guest requests such as telephony webhooks and web forms."""
    user = user or frappe.session.user
    return user == "Guest" or _can_bypass(user)


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


def get_record_company(doctype: str, name: str | None) -> str | None:
    """Company owning any record a CRM record can point at, if known."""
    if not name:
        return None
    field = COMPANY_FIELD if doctype in SCOPED_DOCTYPES else EXTERNAL_COMPANY_FIELDS.get(doctype)
    if not field or not frappe.db.has_column(doctype, field) or not frappe.db.exists(doctype, name):
        return None
    return frappe.db.get_value(doctype, name, field)


def _linked_records(doc) -> list[tuple[str, str]]:
    """(doctype, name) of every Company-owned record this one points at."""
    links = [
        (target, doc.get(fieldname))
        for fieldname, target in SCOPED_LINKS.get(doc.doctype, {}).items()
        if doc.get(fieldname)
    ]
    if doc.doctype in REFERENCE_DOCTYPES and doc.get("reference_doctype") in SCOPED_DOCTYPES:
        if doc.get("reference_docname"):
            links.append((doc.reference_doctype, doc.reference_docname))
    if doc.doctype == "CRM Deal":
        links += [("Contact", row.get("contact")) for row in doc.get("contacts") or [] if row.get("contact")]
    if doc.doctype == "Contact":
        owned = set(SCOPED_DOCTYPES) | set(EXTERNAL_COMPANY_FIELDS)
        links += [
            (row.get("link_doctype"), row.get("link_name"))
            for row in doc.get("links") or []
            if row.get("link_doctype") in owned and row.get("link_name")
        ]
    return links


def inherited_company(doc) -> str | None:
    """Company implied by the records this one is attached or linked to."""
    for doctype, name in _linked_records(doc):
        if doctype == "Contact" and doc.doctype == "CRM Deal":
            continue  # a Deal's Company comes from its lead or organization, not contacts
        company = get_record_company(doctype, name)
        if company:
            return company
    if doc.doctype == "Contact" and doc.name and not doc.is_new():
        deals = frappe.get_all(
            "CRM Contacts", filters={"contact": doc.name, "parenttype": "CRM Deal"}, pluck="parent"
        )
        companies = {get_record_company("CRM Deal", deal) for deal in deals} - {None}
        if len(companies) == 1:
            return companies.pop()
    return None


def bind_company(doc, method=None) -> None:
    """``before_insert``: stamp the creator's Company on a new CRM record.

    Tenant users always get their own Company; a different value is rejected.
    System users, background jobs and Guest webhooks inherit the Company of the
    record they are attached to, otherwise the record stays unowned and
    therefore invisible to every tenant.
    """
    if doc.doctype not in SCOPED_DOCTYPES or not is_scoping_active():
        return
    if _is_system_actor():
        if not doc.get(COMPANY_FIELD):
            doc.set(COMPANY_FIELD, inherited_company(doc))
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
    for doctype, name in _linked_records(doc):
        owner = get_record_company(doctype, name)
        if doctype in EXTERNAL_COMPANY_FIELDS and owner is None:
            continue  # Customer/Supplier without Distribution's ownership column
        if doctype == "Contact" and owner is None and company and _is_system_actor():
            # Upstream creates conversion contacts before linking them to the
            # Deal, so a contact created by a system user arrives unowned.
            frappe.db.set_value("Contact", name, COMPANY_FIELD, company, update_modified=False)
            continue
        if owner != company:
            frappe.throw(
                _("{0} {1} belongs to a different Company.").format(_(doctype), name),
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


def find_contact_by_email(email: str, company: str | None) -> str | None:
    """Tenant-scoped replacement for CRM's global contact-by-email lookup."""
    if not email:
        return None
    for contact in frappe.get_all(
        "Contact Email", filters={"email_id": email, "parenttype": "Contact"}, pluck="parent"
    ):
        if get_record_company("Contact", contact) == company:
            return contact
    return None


def assert_same_company(doctype: str, name: str, company: str | None) -> None:
    if get_record_company(doctype, name) != company:
        frappe.throw(
            _("{0} {1} belongs to a different Company.").format(_(doctype), name),
            frappe.PermissionError,
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
