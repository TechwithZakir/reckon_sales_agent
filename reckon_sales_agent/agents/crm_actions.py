"""CRM actions, Phase B: the copilot proposes changes to a CRM lead or deal.

Automatic, internal and reversible: a follow-up task and an internal note. They run at once and are logged.
Everything that changes a deal or a lead (stage, value, probability, close date, owner) is stored as a pending
Sales CRM Action, and changes the record only after a person approves it. Nothing is deleted, merged or sent here.

``validate_payload`` is pure, so the rules are unit-tested without Frappe.
"""

from __future__ import annotations

import json
from datetime import datetime

AUTOMATIC = ("create_task", "add_note")
APPROVAL = ("set_stage", "set_deal_value", "set_probability", "set_close_date", "reassign")
ACTIONS = AUTOMATIC + APPROVAL
DEAL_ONLY = ("set_stage", "set_deal_value", "set_probability", "set_close_date")
RECORDS = ("CRM Lead", "CRM Deal")


def validate_payload(action: str, payload: dict) -> dict:
    """The clean details of one action. Raises ValueError with a message a person can act on."""
    if action not in ACTIONS:
        raise ValueError("Unknown CRM action.")
    if not isinstance(payload, dict):
        raise ValueError("The details must be a set of fields.")
    if action == "create_task":
        title = str(payload.get("title") or "").strip()[:140]
        if not title:
            raise ValueError("A task needs a title.")
        due = str(payload.get("due_date") or "")[:10]
        if due:
            _date(due)
        return {"title": title, "due_date": due}
    if action == "add_note":
        text = str(payload.get("text") or "").strip()[:2000]
        if not text:
            raise ValueError("A note needs some text.")
        return {"text": text}
    if action == "set_stage":
        stage = str(payload.get("stage") or "").strip()
        if not stage:
            raise ValueError("Choose the new stage.")
        return {"stage": stage}
    if action == "set_deal_value":
        value = _number(payload.get("value"), "The value")
        if value < 0:
            raise ValueError("The value cannot be negative.")
        return {"value": value}
    if action == "set_probability":
        probability = _number(payload.get("probability"), "The probability")
        if not 0 <= probability <= 100:
            raise ValueError("The probability must be between 0 and 100.")
        return {"probability": probability}
    if action == "set_close_date":
        return {"date": _date(str(payload.get("date") or ""))}
    user = str(payload.get("user") or "").strip()
    if "@" not in user:
        raise ValueError("Pick the person to assign to.")
    return {"user": user}


def allowed_for(ref_doctype: str, action: str) -> bool:
    """Whether this action can be proposed for this kind of record."""
    if ref_doctype not in RECORDS:
        return False
    return not (action in DEAL_ONLY and ref_doctype != "CRM Deal")


def field_change(ref_doctype: str, action: str, clean: dict) -> dict:
    """The CRM field(s) an approved action sets."""
    if action == "set_stage":
        return {"status": clean["stage"]}
    if action == "set_deal_value":
        return {"deal_value": clean["value"]}
    if action == "set_probability":
        return {"probability": clean["probability"]}
    if action == "set_close_date":
        return {"expected_closure_date": clean["date"]}
    if action == "reassign":
        return {"deal_owner" if ref_doctype == "CRM Deal" else "lead_owner": clean["user"]}
    raise ValueError("Not a field change.")


def describe(ref_doctype: str, ref_name: str, action: str, clean: dict) -> str:
    """One line a person reads before approving."""
    labels = {"set_stage": f"Move to stage {clean.get('stage')}", "set_deal_value": f"Set value to {clean.get('value')}",
              "set_probability": f"Set probability to {clean.get('probability')}%",
              "set_close_date": f"Set expected close to {clean.get('date')}", "reassign": f"Assign to {clean.get('user')}",
              "create_task": f"Create task: {clean.get('title')}", "add_note": "Add an internal note"}
    return f"{labels.get(action, action)} on {ref_doctype} {ref_name}"


def _number(value, label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number.") from None


def _date(text: str) -> str:
    try:
        return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise ValueError("Use a date like 2026-12-31.") from None


def propose(company: str, ref_doctype: str, ref_name: str, action: str, payload: dict, requested_by: str) -> dict:
    """Run an automatic action now, or record a pending change for approval. Returns what happened."""
    import frappe
    from frappe import _

    from reckon_sales_agent.tenant import get_tenant_doc
    from reckon_sales_agent.usage import log_activity

    if not allowed_for(ref_doctype, action):
        frappe.throw(_("This action cannot be proposed for that record."))
    clean = validate_payload(action, payload)
    doc = get_tenant_doc(ref_doctype, ref_name, "write")
    if doc.get("rsa_company") != company:
        frappe.throw(_("That record belongs to another Company."), frappe.PermissionError)
    if action == "set_stage" and not frappe.db.exists("CRM Deal Status", clean["stage"]):
        frappe.throw(_("No such deal stage: {0}.").format(clean["stage"]))
    if action == "reassign" and not frappe.db.get_value("User", clean["user"], "enabled"):
        frappe.throw(_("That user is not active."))
    summary = describe(ref_doctype, ref_name, action, clean)
    prospect = frappe.db.get_value("Sales Prospect", {"crm_lead": doc.name if ref_doctype == "CRM Lead" else doc.get("lead")},
                                   "name") if ref_doctype in RECORDS else None

    if action in AUTOMATIC:
        if action == "create_task":
            from frappe.utils import add_days, nowdate

            made = frappe.get_doc({"doctype": "CRM Task", "title": clean["title"], "status": "Todo",
                                   "due_date": clean["due_date"] or add_days(nowdate(), 1),
                                   "reference_doctype": ref_doctype, "reference_docname": ref_name}).insert(ignore_permissions=True)
        else:
            made = frappe.get_doc({"doctype": "FCRM Note", "title": "Copilot note",
                                   "content": frappe.utils.escape_html(clean["text"]).replace("\n", "<br>"),
                                   "reference_doctype": ref_doctype, "reference_docname": ref_name}).insert(ignore_permissions=True)
        log_activity(company, "crm_automatic", None, summary, actor_type="agent", agent="CRM", policy_outcome="automatic")
        return {"status": "Applied", "name": made.name, "summary": summary}

    row = frappe.get_doc({"doctype": "Sales CRM Action", "company": company, "ref_doctype": ref_doctype,
                          "ref_name": ref_name, "prospect": prospect, "action": action, "summary": summary,
                          "payload": json.dumps(clean, sort_keys=True), "status": "Pending",
                          "requested_by": requested_by}).insert(ignore_permissions=True)
    log_activity(company, "crm_proposed", None, summary, actor_type="agent", agent="CRM",
                 policy_outcome="needs approval")
    return {"status": "Pending", "name": row.name, "summary": summary}


def decide(name: str, approve: bool, decided_by: str) -> dict:
    """A person approves or rejects a pending change. Approving applies it to the CRM record."""
    import frappe
    from frappe.utils import now_datetime

    from reckon_sales_agent.usage import log_activity

    row = frappe.get_doc("Sales CRM Action", name)
    if row.status != "Pending":
        frappe.throw(frappe._("This change has already been decided."))
    row.decided_by, row.decided_on = decided_by, now_datetime()
    if not approve:
        row.status, row.result = "Rejected", "Rejected by a person."
        row.save(ignore_permissions=True)
        return {"status": row.status, "summary": row.summary}
    try:
        change = field_change(row.ref_doctype, row.action, json.loads(row.payload or "{}"))
        frappe.db.set_value(row.ref_doctype, row.ref_name, change)
        row.status, row.result = "Applied", "Applied after approval."
    except Exception as exc:  # the record stays as it was; the reason is kept on the action
        row.status, row.result = "Failed", str(exc)[:500]
    row.save(ignore_permissions=True)
    log_activity(row.company, "crm_decided", None, f"{row.status}: {row.summary}", actor_type="user",
                 agent="CRM", policy_outcome="approved" if approve else "rejected")
    return {"status": row.status, "summary": row.summary}
