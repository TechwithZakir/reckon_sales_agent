from __future__ import annotations

import frappe

from reckon_sales_agent.crm_tenancy import (
    COMPANY_FIELD,
    SCOPED_DOCTYPES,
    _inherited_company,
    is_scoping_active,
)

# Parents first so Deals and Tasks can inherit their Company during backfill.
BACKFILL_ORDER = ("CRM Organization", "CRM Lead", "CRM Deal", "CRM Task")


def after_install() -> None:
    ensure_crm_company_fields()


def after_migrate() -> None:
    ensure_crm_company_fields()


def ensure_crm_company_fields() -> None:
    """Add the read-only Company field to CRM DocTypes and backfill old records."""
    if not frappe.db.exists("DocType", "Company"):
        return
    for doctype, insert_after in SCOPED_DOCTYPES.items():
        if not frappe.db.exists("DocType", doctype):
            continue
        if not frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": COMPANY_FIELD}):
            frappe.get_doc(
                {
                    "doctype": "Custom Field",
                    "dt": doctype,
                    "fieldname": COMPANY_FIELD,
                    "label": "Company",
                    "fieldtype": "Link",
                    "options": "Company",
                    "read_only": 1,
                    "in_standard_filter": 1,
                    "search_index": 1,
                    "no_copy": 1,
                    "insert_after": insert_after,
                }
            ).insert(ignore_permissions=True)
        frappe.clear_cache(doctype=doctype)
    if is_scoping_active():
        backfill_crm_companies()


def backfill_crm_companies() -> dict[str, int]:
    """Give unowned CRM records a Company where it is unambiguous.

    Deals and Tasks inherit from their lead, organization or reference record;
    anything else takes the owner's single active Company. Records that still
    have no Company stay hidden from tenants and are reported in the Error Log.
    """
    from reckon_saas_platform.tenant_security import get_user_companies

    owner_companies: dict[str, list[str]] = {}
    unresolved: dict[str, int] = {}
    for doctype in BACKFILL_ORDER:
        if not frappe.db.has_column(doctype, COMPANY_FIELD):
            continue
        names = frappe.get_all(doctype, filters={COMPANY_FIELD: ["is", "not set"]}, pluck="name")
        missing = 0
        for name in names:
            doc = frappe.get_doc(doctype, name)
            company = _inherited_company(doc)
            if not company:
                if doc.owner not in owner_companies:
                    owner_companies[doc.owner] = get_user_companies(doc.owner)
                companies = owner_companies[doc.owner]
                company = companies[0] if len(companies) == 1 else None
            if company:
                frappe.db.set_value(doctype, name, COMPANY_FIELD, company, update_modified=False)
            else:
                missing += 1
        if missing:
            unresolved[doctype] = missing
    if unresolved:
        frappe.log_error(
            title="CRM Company Backfill Incomplete",
            message="Records without a Company are hidden from tenant users: "
            + ", ".join(f"{doctype}: {count}" for doctype, count in unresolved.items()),
        )
    return unresolved
