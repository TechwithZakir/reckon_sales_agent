from __future__ import annotations

import frappe

from reckon_sales_agent.qualification.scoring import score
from reckon_sales_agent.usage import log_activity


def qualify_prospect(prospect_name: str) -> str:
    """Score a prospect from its latest research; human overrides stay in force."""
    prospect = frappe.get_doc("Sales Prospect", prospect_name)
    facts = []
    if prospect.latest_research:
        facts = [row.as_dict() for row in frappe.get_doc("Sales Research Report", prospect.latest_research).facts]
    profile_name = None
    if prospect.discovery_campaign:
        profile_name = frappe.db.get_value("Sales Discovery Campaign", prospect.discovery_campaign,
                                           "qualification_profile")
    profile_name = profile_name or frappe.db.get_value(
        "Sales Qualification Profile", {"company": prospect.company}, "name", order_by="creation asc")
    profile = frappe.get_doc("Sales Qualification Profile", profile_name).as_dict() if profile_name else None

    result = score(prospect.as_dict(), facts, profile)
    previous_override = None
    if prospect.latest_qualification:
        previous_override = frappe.db.get_value(
            "Sales Qualification", prospect.latest_qualification,
            ["override_result", "override_reason", "overridden_by"], as_dict=True)
    qualification = frappe.get_doc({
        "doctype": "Sales Qualification",
        "company": prospect.company,
        "prospect": prospect.name,
        "profile": profile_name,
        **result,
    })
    if previous_override and previous_override.override_result:
        qualification.update(previous_override)
    qualification.insert(ignore_permissions=True)
    prospect.db_set({
        "latest_qualification": qualification.name,
        "qualification_status": qualification.override_result or result["result"],
        "fit_score": result["fit_score"],
        "buying_signal_score": result["buying_signal_score"],
        "evidence_confidence": result["evidence_confidence"],
        "contactability": result["contactability"],
    })
    log_activity(prospect.company, "qualified", prospect,
                 f"{result['result']} (fit {result['fit_score']}, {result['scoring_version']})", "system")
    return qualification.name
