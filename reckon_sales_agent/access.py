"""Roles for Sales Agent tenant users, from their Tenant User Assignment.

The assignment's ``role_profile`` decides the Frappe roles. Sync runs on
assignment save and on migrate, never per request. Only Companies that
subscribe to the Sales Agent module are touched.
"""

from __future__ import annotations

import frappe
from frappe import _

from reckon_sales_agent.constants import MANAGED_ROLES, MODULE_KEY, PROFILE_ROLES, SAAS_ROLES


def company_uses_sales_agent(company: str | None) -> bool:
    if not company:
        return False
    from reckon_saas_platform.saas import get_company_module_keys

    return MODULE_KEY in get_company_module_keys(company)


def _profile_for(user: str, row) -> str | None:
    """The person's role profile in this module, or ``None`` when the company's team page did not give them it."""
    try:
        from reckon_saas_platform.team import module_profile
    except ImportError:  # an older platform: one role profile for every module
        return row.role_profile
    access = module_profile(user, row.company, MODULE_KEY, row.role_profile)
    return access["role_profile"] if access else None


def sync_tenant_user_access(doc, method=None) -> None:
    """Tenant User Assignment ``on_update``."""
    if company_uses_sales_agent(doc.get("company")):
        sync_user(doc.get("user"))


def sync_user(user: str | None) -> None:
    if not user or user in {"Guest", "Administrator"} or not frappe.db.exists("User", user):
        return
    assignments = frappe.get_all("Tenant User Assignment", filters={"user": user, "active": 1},
                                 fields=["company", "role_profile"])
    ours = [row for row in assignments if company_uses_sales_agent(row.company)]
    wanted = set()
    for row in ours:
        profile = _profile_for(user, row)
        if profile is None:
            continue  # the company's team page did not give this person Sales Agent
        wanted.update(
            role for role in PROFILE_ROLES.get(profile, PROFILE_ROLES["Sales User"]) if frappe.db.exists("Role", role)
        )
    current = set(frappe.get_roles(user))
    user_doc = frappe.get_doc("User", user)
    # CRM roles may come from another module too; only remove our own when others are present.
    removable = MANAGED_ROLES if len(ours) == len(assignments) else set(SAAS_ROLES)
    stale = (current & removable) - wanted
    if stale:
        user_doc.remove_roles(*sorted(stale))
    missing = wanted - current
    if missing:
        user_doc.add_roles(*sorted(missing))


def backfill_users() -> None:
    if not frappe.db.exists("DocType", "Tenant User Assignment"):
        return
    for user in sorted(set(frappe.get_all("Tenant User Assignment", filters={"active": 1}, pluck="user"))):
        try:
            sync_user(user)
        except Exception:
            frappe.log_error(title=_("Sales Agent user sync failed"))
