from __future__ import annotations

import json
from pathlib import Path

import frappe

from reckon_sales_agent.constants import LEAD_SOURCE, SAAS_ROLES, WORKSPACE_SIDEBAR
from reckon_sales_agent.crm_tenancy import (
    COMPANY_FIELD,
    DATA_DOCTYPES,
    EXTERNAL_COMPANY_FIELDS,
    SCOPED_DOCTYPES,
    inherited_company,
    is_scoping_active,
)

# CRM data backfilled record by record, parents first so children can inherit.
RECORD_BACKFILL_ORDER = (
    "CRM Organization",
    "CRM Lead",
    "CRM Deal",
    "Contact",
    "Address",
    "CRM Product",
    "CRM Task",
    "FCRM Note",
    "CRM Call Log",
    "CRM Notification",
    "CRM Sales Hierarchy",
    "CRM Telephony Agent",
    "CRM Invitation",
)

# Large Frappe core tables, backfilled in bulk from the record they reference.
REFERENCE_COLUMNS = {
    "Communication": ("reference_doctype", "reference_name"),
    "Comment": ("reference_doctype", "reference_name"),
    "ToDo": ("reference_type", "reference_name"),
    "File": ("attached_to_doctype", "attached_to_name"),
}


SIDEBAR_FILE = Path(__file__).parent / "workspace_sidebar" / "sales_agent.json"


def after_install() -> None:
    after_migrate()


def after_migrate() -> None:
    setup_roles()
    ensure_crm_company_fields()
    ensure_shared_lead_source()
    ensure_workspace_sidebar()
    from reckon_sales_agent.access import backfill_users

    backfill_users()


def setup_roles() -> None:
    for role in SAAS_ROLES:
        if not frappe.db.exists("Role", role):
            frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1, "is_custom": 1}).insert(
                ignore_permissions=True)


def ensure_shared_lead_source() -> None:
    """A shared (unowned) "Sales Agent" lead source every Company can pick."""
    if frappe.db.exists("DocType", "CRM Lead Source") and not frappe.db.exists("CRM Lead Source", LEAD_SOURCE):
        frappe.get_doc({"doctype": "CRM Lead Source", "source_name": LEAD_SOURCE,
                        "details": "Prospects found and approved through Reckon Sales Agent."}).insert(
            ignore_permissions=True)


def ensure_workspace_sidebar() -> None:
    """Frappe v16 left rail, kept in step with the shipped file."""
    if not frappe.db.exists("DocType", "Workspace Sidebar"):
        return
    definition = json.loads(SIDEBAR_FILE.read_text(encoding="utf-8"))
    definition["items"] = [
        item for item in definition["items"]
        if item["type"] != "Link" or frappe.db.exists(item["link_type"], item["link_to"])
    ]
    if frappe.db.exists("Workspace Sidebar", WORKSPACE_SIDEBAR):
        sidebar = frappe.get_doc("Workspace Sidebar", WORKSPACE_SIDEBAR)
        sidebar.set("items", definition["items"])
        sidebar.header_icon = definition["header_icon"]
        sidebar.save(ignore_permissions=True)
    else:
        frappe.get_doc(definition).insert(ignore_permissions=True, ignore_links=True)


def ensure_crm_company_fields() -> None:
    """Add the read-only Company field to scoped DocTypes and backfill old records."""
    if not frappe.db.exists("DocType", "Company"):
        return
    for doctype, insert_after in SCOPED_DOCTYPES.items():
        if not frappe.db.exists("DocType", doctype):
            continue
        if not frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": COMPANY_FIELD}):
            field = {
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
            }
            if insert_after:
                field["insert_after"] = insert_after
            frappe.get_doc(field).insert(ignore_permissions=True)
        frappe.clear_cache(doctype=doctype)
    if is_scoping_active():
        backfill_crm_companies()


def _has_column(doctype: str, column: str) -> bool:
    try:
        return frappe.db.has_column(doctype, column)
    except Exception:
        return False  # single or virtual DocType without a table


def _owner_company(owner: str, cache: dict[str, str | None]) -> str | None:
    from reckon_saas_platform.tenant_security import get_user_companies

    if owner not in cache:
        companies = get_user_companies(owner)
        cache[owner] = companies[0] if len(companies) == 1 else None
    return cache[owner]


def backfill_crm_companies() -> dict[str, int]:
    """Give unowned data records a Company where it is unambiguous.

    Records inherit from what they are attached or linked to; anything else
    takes the owner's single active Company. Master lists are left alone, so
    their existing entries stay shared defaults. Data records that still have
    no Company stay hidden from tenants and are counted in the Error Log.
    """
    owners: dict[str, str | None] = {}
    for doctype in RECORD_BACKFILL_ORDER:
        if not _has_column(doctype, COMPANY_FIELD):
            continue
        for name in frappe.get_all(doctype, filters={COMPANY_FIELD: ["is", "not set"]}, pluck="name"):
            doc = frappe.get_doc(doctype, name)
            company = inherited_company(doc) or _owner_company(doc.owner, owners)
            if company:
                frappe.db.set_value(doctype, name, COMPANY_FIELD, company, update_modified=False)

    for doctype, (doctype_column, name_column) in REFERENCE_COLUMNS.items():
        if _has_column(doctype, COMPANY_FIELD):
            _backfill_from_references(doctype, doctype_column, name_column)
            _backfill_from_owners(doctype, owners)

    unresolved = {}
    for doctype in DATA_DOCTYPES:
        if _has_column(doctype, COMPANY_FIELD):
            count = frappe.db.count(doctype, {COMPANY_FIELD: ["is", "not set"]})
            if count:
                unresolved[doctype] = count
    if unresolved:
        frappe.log_error(
            title="CRM Company Backfill Incomplete",
            message="Records without a Company are hidden from tenant users: "
            + ", ".join(f"{doctype}: {count}" for doctype, count in unresolved.items()),
        )
    return unresolved


def _backfill_from_references(doctype: str, doctype_column: str, name_column: str) -> None:
    targets = frappe.db.sql(
        f"""select distinct `{doctype_column}` from `tab{doctype}`
        where ifnull(`{COMPANY_FIELD}`, '') = '' and ifnull(`{doctype_column}`, '') != ''""",
        pluck=True,
    )
    for target in targets:
        if target == "Company":
            frappe.db.sql(
                f"""update `tab{doctype}` set `{COMPANY_FIELD}` = `{name_column}`
                where `{doctype_column}` = 'Company' and ifnull(`{COMPANY_FIELD}`, '') = ''"""
            )
            continue
        if not frappe.db.exists("DocType", target):
            continue
        field = (
            COMPANY_FIELD
            if target in SCOPED_DOCTYPES
            else EXTERNAL_COMPANY_FIELDS.get(target, "company")
        )
        if not _has_column(target, field):
            continue
        frappe.db.sql(
            f"""update `tab{doctype}` child
            join `tab{target}` parent on parent.name = child.`{name_column}`
            set child.`{COMPANY_FIELD}` = parent.`{field}`
            where child.`{doctype_column}` = %s
                and ifnull(child.`{COMPANY_FIELD}`, '') = ''
                and ifnull(parent.`{field}`, '') != ''""",
            target,
        )


def _backfill_from_owners(doctype: str, owners: dict[str, str | None]) -> None:
    for owner in frappe.db.sql(
        f"select distinct owner from `tab{doctype}` where ifnull(`{COMPANY_FIELD}`, '') = ''",
        pluck=True,
    ):
        company = _owner_company(owner, owners)
        if company:
            frappe.db.sql(
                f"""update `tab{doctype}` set `{COMPANY_FIELD}` = %s
                where owner = %s and ifnull(`{COMPANY_FIELD}`, '') = ''""",
                (company, owner),
            )
