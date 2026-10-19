"""Review decisions and safe sync of approved prospects into native Frappe CRM.

Creates or links a CRM Organization and a CRM Lead in the prospect's own
Company. Existing CRM records are only filled where empty; nothing a user
entered is overwritten. Fields a source only lets us keep temporarily
(``crm_sync`` false in the field policy) are not copied into the CRM.
"""

from __future__ import annotations

import json

import frappe
from frappe import _

from reckon_sales_agent.constants import LEAD_SOURCE
from reckon_sales_agent.crm_tenancy import find_organization
from reckon_sales_agent.usage import log_activity

REVIEW_ACTIONS = {"approve": "Approved", "reject": "Rejected", "defer": "Deferred"}


def review(prospect, action: str, notes: str | None = None, merge_into: str | None = None) -> None:
    if action == "merge":
        if not merge_into or merge_into == prospect.name:
            frappe.throw(_("Choose the prospect to merge into."))
        target = frappe.get_doc("Sales Prospect", merge_into)
        target.check_permission("write")
        if target.company != prospect.company:
            frappe.throw(_("Prospects belong to different Companies."), frappe.PermissionError)
        for field in ("website", "email", "phone", "address", "industry", "city"):
            if not target.get(field) and prospect.get(field):
                target.set(field, prospect.get(field))
        target.save()
        prospect.db_set({"review_status": "Merged", "merged_into": target.name, "review_notes": notes})
        log_activity(prospect.company, "prospect_merged", prospect, f"into {target.name}")
        return
    if action not in REVIEW_ACTIONS:
        frappe.throw(_("Unknown review action."))
    prospect.db_set({"review_status": REVIEW_ACTIONS[action], "review_notes": notes})
    log_activity(prospect.company, f"prospect_{REVIEW_ACTIONS[action].lower()}", prospect, notes or "")
    if action == "approve":
        sync_to_crm(prospect)


def _syncable(prospect) -> dict:
    """Prospect fields the source policy allows into the CRM."""
    provenance = json.loads(prospect.provenance_json or "{}")
    allowed = {}
    for field in ("business_name", "website", "email", "phone", "industry", "city", "address"):
        info = provenance.get(field) or {}
        restricted = info.get("retention_days") and info.get("source") != "company_website"
        if prospect.get(field) and not restricted:
            allowed[field] = prospect.get(field)
    return allowed


def sync_to_crm(prospect) -> str | None:
    if prospect.review_status != "Approved":
        frappe.throw(_("Approve the prospect before syncing it to the CRM."))
    data = _syncable(prospect)
    if not data.get("business_name"):
        frappe.msgprint(_("The business name is only held temporarily under the source's terms; "
                          "research the website first to confirm it before creating a CRM lead."))
        return None

    organization = prospect.crm_organization or find_organization(data["business_name"], prospect.company)
    if not organization:
        org = frappe.get_doc({"doctype": "CRM Organization", "organization_name": data["business_name"],
                              "website": data.get("website"), "rsa_company": prospect.company})
        org.insert()
        organization = org.name
    else:
        org = frappe.get_doc("CRM Organization", organization)
        if not org.website and data.get("website"):
            org.website = data["website"]
            org.save()

    lead_name = prospect.crm_lead
    if not lead_name:
        lead = frappe.get_doc({
            "doctype": "CRM Lead",
            "first_name": data["business_name"][:140],
            "organization": data["business_name"],
            "website": data.get("website"),
            "email": data.get("email"),
            "mobile_no": data.get("phone"),
            "status": _default_lead_status(),
            "source": LEAD_SOURCE if frappe.db.exists("CRM Lead Source", LEAD_SOURCE) else None,
            "rsa_company": prospect.company,
        })
        lead.insert()
        lead_name = lead.name
        frappe.get_doc({
            "doctype": "FCRM Note",
            "title": _("Sales Agent research"),
            "content": _note(prospect),
            "reference_doctype": "CRM Lead",
            "reference_docname": lead_name,
        }).insert()
    prospect.db_set({"crm_organization": organization, "crm_lead": lead_name})
    log_activity(prospect.company, "crm_synced", prospect, f"lead {lead_name}")
    return lead_name


def _default_lead_status() -> str:
    order = "position asc" if frappe.db.has_column("CRM Lead Status", "position") else "creation asc"
    statuses = frappe.get_all("CRM Lead Status", pluck="name", order_by=order, limit=1)
    return statuses[0] if statuses else "New"


def _note(prospect) -> str:
    lines = [f"<p><b>Fit score:</b> {prospect.fit_score or 0} · <b>Buying signal:</b> "
             f"{prospect.buying_signal_score or 0} · <b>Evidence:</b> {prospect.evidence_confidence or 0}</p>"]
    if prospect.latest_research:
        report = frappe.get_doc("Sales Research Report", prospect.latest_research)
        if report.summary:
            lines.append(f"<p>{frappe.utils.escape_html(report.summary)}</p>")
        facts = [row for row in report.facts if not row.is_inference][:10]
        if facts:
            lines.append("<ul>" + "".join(
                f"<li>{frappe.utils.escape_html(row.statement)} "
                f"<small>({frappe.utils.escape_html(row.evidence_url or '')})</small></li>" for row in facts) + "</ul>")
    return "".join(lines)
