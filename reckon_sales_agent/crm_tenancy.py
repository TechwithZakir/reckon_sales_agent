"""Company (tenant) ownership for Frappe CRM records.

Reckon SaaS tenants are Companies on one shared site, but Frappe CRM's own
DocTypes carry no Company. This module adds a server-managed ``rsa_company``
field and enforces it through permission hooks, so one tenant can never list,
open, link or modify another tenant's CRM records.

Every CRM DocType falls in one of three groups:

- **Data** (``DATA_DOCTYPES``): strictly per Company. Records without a
  Company are invisible to every tenant.
- **Master lists** (``MASTER_DOCTYPES``): each Company maintains its own
  entries; unowned entries (CRM's seeded defaults) are shared read-only.
- **Site configuration** (``VENDOR_CONFIG_DOCTYPES``): one copy per site that
  tenants may read but only vendor administrators may change.

Child tables follow their parent. Scoping is active only when
``reckon_saas_platform`` is installed; without it CRM behaves as upstream.
"""

from __future__ import annotations

import frappe
from frappe import _

COMPANY_FIELD = "rsa_company"

# DocType -> field the Company column is placed after (None: end of form).
DATA_DOCTYPES = {
    "CRM Lead": "status",
    "CRM Deal": "status",
    "CRM Organization": "organization_name",
    "Contact": "company_name",
    "Address": "address_title",
    "CRM Task": "status",
    "FCRM Note": "title",
    "CRM Call Log": "status",
    "CRM Notification": None,
    "CRM Product": "product_name",
    "CRM Sales Hierarchy": None,
    "CRM Telephony Agent": "user",
    "CRM Invitation": None,
    "Communication": None,
    "Comment": None,
    "ToDo": None,
    "File": None,
}
MASTER_DOCTYPES = {
    "CRM Territory": "territory_name",
    "CRM Industry": "industry",
    "CRM Lead Source": "source_name",
    "CRM Lost Reason": "lost_reason",
    "CRM Holiday List": "holiday_list_name",
    "CRM Service Level Agreement": "sla_name",
    "CRM Dashboard": "title",
    "CRM View Settings": None,
}
SCOPED_DOCTYPES = {**DATA_DOCTYPES, **MASTER_DOCTYPES}

VENDOR_CONFIG_DOCTYPES = frozenset(
    {
        "FCRM Settings",
        "CRM Twilio Settings",
        "CRM Exotel Settings",
        "ERPNext CRM Settings",
        "CRM Global Settings",
        "CRM Fields Layout",
        "CRM Form Script",
        "CRM Lead Status",
        "CRM Deal Status",
        "CRM Communication Status",
    }
)

# Records named after a field, which is unique site-wide.
NAME_FIELDS = {
    "CRM Organization": "organization_name",
    "CRM Product": "product_code",
    "CRM Territory": "territory_name",
    "CRM Industry": "industry",
    "CRM Lead Source": "source_name",
    "CRM Lost Reason": "lost_reason",
    "CRM Holiday List": "holiday_list_name",
    "CRM Service Level Agreement": "sla_name",
    "CRM Dashboard": "title",
}

# Unowned records still readable by tenants, beyond master lists.
SHARED_UNOWNED = {"File": "is_folder = 1"}

# Company owner of non-CRM records. Distribution adds ``rd_company`` to these;
# any other DocType is owned through a standard ``company`` column if it has one.
EXTERNAL_COMPANY_FIELDS = {
    "Customer": "rd_company",
    "Supplier": "rd_company",
    "Item": "rd_company",
    "Item Price": "rd_company",
    "Price List": "rd_company",
}

# Links that never imply Company ownership.
IGNORED_LINK_TARGETS = frozenset({"User", "DocType", "Role", "Currency"})

# References stored in plain Data fields rather than Dynamic Links.
DATA_REFERENCE_FIELDS = {"File": ("attached_to_doctype", "attached_to_name")}

# Unowned records of these DocTypes are adopted when a system user links them.
ADOPTABLE_DOCTYPES = frozenset({"Contact", "Address"})

READ_PERMISSIONS = {None, "", "read", "select", "print", "email", "report", "export", "share"}


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


# Permission hooks


def get_query_conditions(user: str | None = None, doctype: str | None = None) -> str:
    """``permission_query_conditions`` for scoped DocTypes.

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
    column = f"`tab{doctype}`.`{COMPANY_FIELD}`"
    condition = f"{column} = {frappe.db.escape(company)}"
    shared = "1=1" if doctype in MASTER_DOCTYPES else SHARED_UNOWNED.get(doctype)
    if shared:
        shared = shared if shared == "1=1" else f"`tab{doctype}`.{shared}"
        condition = f"({condition} or (ifnull({column}, '') = '' and {shared}))"
    return condition


def _is_shared_unowned(doc) -> bool:
    if doc.doctype in MASTER_DOCTYPES:
        return True
    return doc.doctype == "File" and bool(doc.get("is_folder"))


def has_permission(
    doc,
    user: str | None = None,
    permission_type: str | None = None,
    ptype: str | None = None,
    debug: bool = False,
) -> bool:
    """``has_permission`` for scoped DocTypes."""
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
    permission_type = ptype or permission_type
    stored = frappe.db.get_value(doc.doctype, doc.name, COMPANY_FIELD)
    if not stored and _is_shared_unowned(doc):
        return permission_type in READ_PERMISSIONS
    if stored != company:
        return False
    if permission_type not in READ_PERMISSIONS:
        return doc.get(COMPANY_FIELD) == company
    return True


def has_config_permission(
    doc,
    user: str | None = None,
    permission_type: str | None = None,
    ptype: str | None = None,
    debug: bool = False,
) -> bool:
    """Site-wide CRM configuration: tenants may read it, only vendors change it."""
    if not is_scoping_active() or _can_bypass(user or frappe.session.user):
        return True
    return (ptype or permission_type) in READ_PERMISSIONS


# Ownership of linked records


def get_record_company(doctype: str, name: str | None) -> str | None:
    """Company owning a record, if it is Company-owned at all."""
    if not name or not doctype or doctype in IGNORED_LINK_TARGETS:
        return None
    if doctype == "Company":
        return name  # e.g. a Company's own address or contact
    if doctype in SCOPED_DOCTYPES:
        field = COMPANY_FIELD
    elif doctype in EXTERNAL_COMPANY_FIELDS:
        field = EXTERNAL_COMPANY_FIELDS[doctype]
    else:
        field = "company"
    try:
        if not frappe.db.has_column(doctype, field) or not frappe.db.exists(doctype, name):
            return None
    except Exception:
        return None  # single or virtual DocType without a table
    return frappe.db.get_value(doctype, name, field) or None


def _row_links(meta, row):
    for df in meta.get_link_fields():
        value = row.get(df.fieldname)
        if value and df.fieldname != COMPANY_FIELD and df.options not in IGNORED_LINK_TARGETS:
            yield df.options, value
    for df in meta.get_dynamic_link_fields():
        doctype, value = row.get(df.options), row.get(df.fieldname)
        if doctype and value and doctype not in IGNORED_LINK_TARGETS:
            yield doctype, value


def linked_records(doc) -> list[tuple[str, str]]:
    """(doctype, name) of every record this one links to, child tables included."""
    meta = frappe.get_meta(doc.doctype)
    links = list(_row_links(meta, doc))
    if doc.doctype in DATA_REFERENCE_FIELDS:
        doctype_field, name_field = DATA_REFERENCE_FIELDS[doc.doctype]
        if doc.get(doctype_field) and doc.get(name_field):
            links.append((doc.get(doctype_field), doc.get(name_field)))
    for table in meta.get_table_fields():
        child_meta = frappe.get_meta(table.options)
        for row in doc.get(table.fieldname) or []:
            links.extend(_row_links(child_meta, row))
    return links


def inherited_company(doc) -> str | None:
    """Company implied by the records this one is attached or linked to.

    Master lists never confer ownership, and a Deal's Company comes from its
    lead or organization rather than from its contacts.
    """
    for doctype, name in linked_records(doc):
        if doctype in MASTER_DOCTYPES:
            continue
        if doctype in ADOPTABLE_DOCTYPES and doc.doctype not in ADOPTABLE_DOCTYPES:
            continue
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


# Document events


def bind_company(doc, method=None) -> None:
    """``before_insert``: stamp the creator's Company on a new record.

    Tenant users always get their own Company; a different value is rejected.
    System users, background jobs and Guest webhooks inherit the Company of the
    record they are attached to. Otherwise a data record stays unowned and
    invisible to tenants, and a master-list entry becomes a shared default.
    """
    if doc.doctype not in SCOPED_DOCTYPES or not is_scoping_active():
        return
    if _is_system_actor():
        if not doc.get(COMPANY_FIELD) and doc.doctype in DATA_DOCTYPES:
            doc.set(COMPANY_FIELD, inherited_company(doc))
        return
    company = get_tenant_company()
    if not company:
        frappe.throw(_("You have no active Company assignment."), frappe.PermissionError)
    if doc.get(COMPANY_FIELD) and doc.get(COMPANY_FIELD) != company:
        frappe.throw(_("Records can only be created for your own Company."), frappe.PermissionError)
    doc.set(COMPANY_FIELD, company)


def validate_company(doc, method=None) -> None:
    """``validate``: Company is immutable once set and linked records must share it."""
    if doc.doctype not in SCOPED_DOCTYPES or not is_scoping_active():
        return
    if not doc.is_new():
        stored = frappe.db.get_value(doc.doctype, doc.name, COMPANY_FIELD)
        if stored and stored != doc.get(COMPANY_FIELD):
            frappe.throw(_("Company cannot be changed after it is set."), frappe.PermissionError)
        if not stored and doc.get(COMPANY_FIELD) and not _can_bypass():
            frappe.throw(_("Only administrators can assign a Company to an unowned record."),
                         frappe.PermissionError)
    if not doc.get(COMPANY_FIELD) and doc.doctype in DATA_DOCTYPES and _is_system_actor():
        # Emails and attachments are often linked to their record after insert.
        doc.set(COMPANY_FIELD, inherited_company(doc))
    assert_links_in_company(doc, doc.get(COMPANY_FIELD))


def assert_links_in_company(doc, company: str | None) -> None:
    """Every record ``doc`` links to must belong to ``company`` (or be shared/unowned)."""
    for doctype, name in linked_records(doc):
        owner = get_record_company(doctype, name)
        if owner == company:
            continue
        if doctype in MASTER_DOCTYPES and owner is None:
            continue  # shared default entry
        if doctype not in SCOPED_DOCTYPES and owner is None:
            continue  # not Company-owned
        if doctype in ADOPTABLE_DOCTYPES and owner is None and company and _is_system_actor():
            # Upstream creates conversion contacts before linking them, so a
            # contact created by a system user arrives unowned.
            frappe.db.set_value(doctype, name, COMPANY_FIELD, company, update_modified=False)
            continue
        frappe.throw(
            _("{0} {1} belongs to a different Company.").format(_(doctype), name),
            frappe.PermissionError,
        )


def set_tenant_name(doc, method=None) -> None:
    """``autoname`` for field-named DocTypes: avoid cross-tenant name clashes.

    These records are named after a field that is unique site-wide. A second
    tenant's "Acme Ltd" gets a Company-qualified name instead of a duplicate
    error that would reveal the other tenant's record.
    """
    field = NAME_FIELDS.get(doc.doctype)
    if not field or not is_scoping_active() or not doc.get(field):
        return
    doc.name = unique_name(doc.doctype, doc.get(field), doc.get(COMPANY_FIELD))


def unique_name(doctype: str, base: str, company: str | None) -> str:
    if not frappe.db.exists(doctype, base) or not company:
        return base
    suffix = frappe.db.get_value("Company", company, "abbr") or company
    candidate = f"{base} - {suffix}"
    counter = 2
    while frappe.db.exists(doctype, candidate):
        candidate = f"{base} - {suffix}-{counter}"
        counter += 1
    return candidate


# Scoped lookups replacing CRM's site-wide ones


def find_organization(organization_name: str, company: str | None) -> str | None:
    if not organization_name:
        return None
    return frappe.db.get_value(
        "CRM Organization",
        {"organization_name": organization_name, COMPANY_FIELD: company},
        "name",
    )


def find_contact_by_email(email: str, company: str | None) -> str | None:
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
