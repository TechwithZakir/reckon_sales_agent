"""Day-one setup for a new Sales Agent company.

Called by the platform's tenant seed job as ``run_sales_agent_seed(company, seed_version)``.
Every step is get-or-create, so a retry is safe. Nothing is enabled that could
contact anyone: outbound sending stays off and human approval stays on.
"""

from __future__ import annotations

import frappe


def run_sales_agent_seed(company: str, seed_version: str) -> dict:
    created: list[str] = []
    if not frappe.db.exists("Sales Agent Settings", company):
        frappe.get_doc({
            "doctype": "Sales Agent Settings",
            "company": company,
            "enabled": 1,
            "outbound_enabled": 0,
            "human_approval_required": 1,
            "sender_name": company,
        }).insert(ignore_permissions=True)
        created.append("Sales Agent Settings")

    profile = frappe.db.get_value("Sales Qualification Profile", {"company": company})
    if not profile:
        profile = frappe.get_doc({
            "doctype": "Sales Qualification Profile",
            "company": company,
            "profile_name": "Default B2B profile",
            "need_keywords": "hiring\nnew branch\nexpansion\ntender\nnow open\nহায়ারিং",
            "fit_keywords": "distributor\nwholesale\nretail\nmanufacturer\nimporter",
        }).insert(ignore_permissions=True).name
        created.append("Sales Qualification Profile")

    for name, kind, enabled in (("Demo data", "fixture", 1), ("CSV import", "manual_import", 0),
                                ("Google Places", "google_places_api", 0)):
        if not frappe.db.exists("Sales Source Connector", {"company": company, "connector_type": kind}):
            frappe.get_doc({
                "doctype": "Sales Source Connector",
                "company": company,
                "connector_name": name,
                "connector_type": kind,
                "enabled": enabled,
                "policy_reviewed": 1 if kind == "fixture" else 0,
            }).insert(ignore_permissions=True)
            created.append(f"Connector {name}")
    return {"company": company, "seed_version": seed_version, "profile": profile, "created": created}
