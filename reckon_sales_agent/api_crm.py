"""CRM actions from the copilot: propose a change, see what waits for approval, approve or reject it.

Anyone who can write the lead or deal can propose; only Sales Agent managers can approve. Automatic actions run at
once; everything else waits. See agents/crm_actions.py for the rules.
"""

import json

import frappe
from frappe import _

from reckon_sales_agent.api_studio import _can_manage
from reckon_sales_agent.tenant import current_company
from reckon_sales_agent.usage import assert_entitled


@frappe.whitelist(methods=["POST"])
def propose(ref_doctype: str, ref_name: str, action: str, payload: str | dict = "{}") -> dict:
    """Propose a change to a CRM lead or deal. Automatic actions run now; the rest wait for approval."""
    from reckon_sales_agent.agents.crm_actions import propose as make_proposal

    company = frappe.db.get_value(ref_doctype, ref_name, "rsa_company") if ref_doctype in ("CRM Lead", "CRM Deal") else None
    if not company:
        frappe.throw(_("This record is not linked to a Sales Agent Company."))
    assert_entitled(company)
    data = json.loads(payload) if isinstance(payload, str) else payload
    return make_proposal(company, ref_doctype, ref_name, action, data or {}, frappe.session.user)


@frappe.whitelist()
def pending() -> list[dict]:
    """The CRM changes waiting for a person to approve, for this Company."""
    company = current_company()
    return frappe.get_all("Sales CRM Action", filters={"company": company, "status": "Pending"},
                          fields=["name", "summary", "ref_doctype", "ref_name", "action", "requested_by", "creation"],
                          order_by="creation desc", limit=50)


@frappe.whitelist(methods=["POST"])
def decide(name: str, approve: int = 0) -> dict:
    """Approve (applies the change to the CRM record) or reject a pending change. Managers only."""
    from reckon_sales_agent.agents.crm_actions import decide as decide_change

    if not _can_manage():
        frappe.throw(_("Ask a Sales Agent admin or manager to approve CRM changes."), frappe.PermissionError)
    if frappe.db.get_value("Sales CRM Action", name, "company") != current_company():
        frappe.throw(_("That change belongs to another Company."), frappe.PermissionError)
    return decide_change(name, bool(int(approve or 0)), frappe.session.user)


@frappe.whitelist(methods=["POST"])
def propose_for_prospect(prospect: str, action: str, payload: str | dict = "{}") -> dict:
    """Propose a change for a prospect's CRM record: the deal for deal changes, the lead otherwise."""
    from reckon_sales_agent.agents.crm_actions import DEAL_ONLY
    from reckon_sales_agent.tenant import get_tenant_doc

    doc = get_tenant_doc("Sales Prospect", prospect, "write")
    lead = doc.get("crm_lead")
    if not lead:
        frappe.throw(_("This prospect is not in CRM yet."))
    if action in DEAL_ONLY:
        deal = frappe.db.get_value("CRM Deal", {"lead": lead}, "name")
        if not deal:
            frappe.throw(_("This lead has no deal yet."))
        return propose("CRM Deal", deal, action, payload)
    return propose("CRM Lead", lead, action, payload)
