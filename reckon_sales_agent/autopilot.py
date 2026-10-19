"""Autopilot: approve strong prospects without waiting for a human.

Off by default. A prospect is auto-approved only when every rule in the
Company's settings holds; anything borderline, possibly duplicated or
suppressed stays in the review queue for a person. Each decision is audited.
"""

from __future__ import annotations


def auto_approval_decision(prospect: dict, settings: dict, approved_today: int) -> tuple[bool, str]:
    """(approve?, reason). Pure: no Frappe imports."""
    if not settings.get("auto_approve_enabled"):
        return False, "Autopilot is off."
    if prospect.get("review_status") != "Pending":
        return False, "Already reviewed."
    if prospect.get("qualification_status") != "Qualified":
        return False, "Not qualified."
    if prospect.get("do_not_contact") or prospect.get("contactability") == "Suppressed":
        return False, "Do-not-contact."
    if prospect.get("possible_duplicate_of"):
        return False, "Possible duplicate needs a human."
    if float(prospect.get("fit_score") or 0) < float(settings.get("auto_approve_min_fit") or 0):
        return False, "Fit score below the autopilot minimum."
    if float(prospect.get("evidence_confidence") or 0) < float(settings.get("auto_approve_min_evidence") or 0):
        return False, "Evidence below the autopilot minimum."
    if float(prospect.get("deal_probability") or 0) < float(settings.get("auto_approve_min_probability") or 0):
        return False, "Deal probability below the autopilot minimum."
    if settings.get("auto_approve_require_contact") and not (prospect.get("email") or prospect.get("phone")):
        return False, "No contact channel."
    if approved_today >= int(settings.get("auto_approve_daily_cap") or 0):
        return False, "Daily autopilot cap reached."
    return True, (f"Auto-approved: fit {prospect.get('fit_score')}, evidence {prospect.get('evidence_confidence')}, "
                  f"probability {prospect.get('deal_probability') or 0}%.")


def maybe_auto_approve(prospect_name: str) -> bool:
    import frappe
    from frappe.utils import nowdate

    from reckon_sales_agent.usage import get_settings, log_activity

    prospect = frappe.get_doc("Sales Prospect", prospect_name)
    settings = get_settings(prospect.company)
    approved_today = frappe.db.count("Sales Agent Activity", {
        "company": prospect.company, "action": "prospect_auto_approved",
        "creation": [">=", f"{nowdate()} 00:00:00"],
    })
    approve, reason = auto_approval_decision(prospect.as_dict(), settings.as_dict(), approved_today)
    if not approve:
        return False
    prospect.db_set({"review_status": "Approved", "auto_approved": 1, "review_notes": reason})
    log_activity(prospect.company, "prospect_auto_approved", prospect, reason, "agent")
    if settings.auto_sync_to_crm:
        from reckon_sales_agent.crm_sync import sync_to_crm

        try:
            sync_to_crm(frappe.get_doc("Sales Prospect", prospect.name))
        except Exception:
            frappe.log_error(title="Sales Agent auto CRM sync failed", reference_doctype="Sales Prospect",
                             reference_name=prospect.name)
    return True
