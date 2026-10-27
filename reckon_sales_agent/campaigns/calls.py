"""Call outcomes: what the salesperson heard decides the agents' next step.

A call task (a CRM Task, or a ToDo on the prospect when it is not in the CRM
yet) belongs to the outreach message that created it. The salesperson picks
one outcome and the Engagement agent does the rest:

    interested      the call confirms the business: CRM lead, a "book the demo" task, sequence stops (positive)
    callback        a new call task on the agreed date; the sequence waits until after it
    not_interested  the sequence stops (no suppression: a later campaign may ask again)
    wrong_number    the number is removed from the lead; email steps may still reach it
    no_answer       a retry the next day, at most twice; then the sequence carries on

``plan_outcome`` is pure; ``record_call_outcome`` applies it.
"""

from __future__ import annotations

OUTCOMES = ("interested", "callback", "not_interested", "wrong_number", "no_answer")
MAX_RETRIES = 2
EVENT = {outcome: f"call_{outcome}" for outcome in OUTCOMES}
REACHED = ("interested", "callback", "not_interested")  # someone answered and talked


def plan_outcome(outcome: str, no_answers_so_far: int = 0) -> dict:
    """What to do: {"stop", "classification", "new_call_in_days" (None or days), "callback", "drop_phone",
    "crm_lead", "positive"}."""
    if outcome not in OUTCOMES:
        raise ValueError(f"Unknown call outcome {outcome!r}.")
    plan = {"stop": False, "classification": None, "new_call_in_days": None, "callback": False,
            "drop_phone": False, "crm_lead": False, "positive": False}
    if outcome == "interested":
        plan.update(stop=True, classification="interested", crm_lead=True, positive=True)
    elif outcome == "callback":
        plan.update(classification="not_now", callback=True)
    elif outcome == "not_interested":
        plan.update(stop=True, classification="not_interested")
    elif outcome == "wrong_number":
        plan.update(drop_phone=True)
    elif no_answers_so_far < MAX_RETRIES:
        plan.update(new_call_in_days=1)
    return plan


# --------------------------------------------------------------------------- Frappe side


def call_message(task_name: str) -> str | None:
    """The Call Task step message whose task this is, or None.

    Live test: reply follow-up tasks are also recorded as "task_created" on an email message, and one was
    accepted as a call ("no answer" closed it and created a retry). Only a Call Task step's tasks are calls.
    """
    import frappe

    for message in frappe.get_all("Sales Communication Event", filters={
            "provider_message_id": str(task_name), "event_type": "task_created"}, pluck="message"):
        if frappe.db.get_value("Sales Outreach Message", message, "channel") == "Call Task":
            return message
    return None


def record_call_outcome(task_doctype: str, task_name: str, outcome: str, note: str = "",
                        callback_on: str | None = None) -> dict:
    import frappe
    from frappe import _
    from frappe.utils import add_days, getdate, nowdate

    from reckon_sales_agent.campaigns.engine import (
        _cancel_pending,
        _note_on_lead,
        _refresh_metrics,
        record_event,
    )
    from reckon_sales_agent.providers.channels import create_task, html_to_text
    from reckon_sales_agent.usage import get_settings, log_activity

    message_name = call_message(task_name)
    if not message_name:
        frappe.throw(_("This task did not come from a campaign call step."))
    message = frappe.get_doc("Sales Outreach Message", message_name)
    member = frappe.get_doc("Sales Campaign Member", message.member)
    prospect = frappe.get_doc("Sales Prospect", message.prospect)
    settings = get_settings(message.company)
    no_answers = frappe.db.count("Sales Communication Event", {"member": member.name, "event_type": EVENT["no_answer"]})
    plan = plan_outcome(outcome, no_answers)
    if plan["callback"]:
        if not callback_on or getdate(callback_on) < getdate(nowdate()):
            frappe.throw(_("Choose the date to call back (today or later)."))

    key = f"call:{task_name}:{outcome}"
    if frappe.db.exists("Sales Communication Event", {"idempotency_key": key}):
        return {"outcome": outcome, "repeat": True}
    record_event(message, EVENT[outcome], key, detail=note[:500] if note else outcome.replace("_", " "))
    _close_task(task_doctype, task_name)

    script = html_to_text(message.body)
    result = {"outcome": outcome}
    if plan["stop"] and member.status == "Active":
        member.db_set({"status": "Stopped", "stop_reason": f"{outcome.replace('_', ' ')} on a call",
                       "next_action_on": None})
        _cancel_pending(member.name, "Outcome of a call.")
    if plan["classification"]:
        member.db_set({"reply_classification": plan["classification"], "last_event": EVENT[outcome]})
    if plan["drop_phone"]:
        prospect.db_set("phone", None)  # email steps may still reach the business
        result["note"] = _("The number was removed from the lead.")
    if plan["crm_lead"]:
        result["crm_lead"] = _confirm_and_sync(prospect)
        # The Meeting agent proposes demo slots and drafts the invitation (a person approves it).
        from reckon_sales_agent.agents.meetings import start_meeting

        result["meeting"] = start_meeting(prospect.name, f"interested on a call ({message.name})")
    if plan["callback"] or plan["new_call_in_days"]:
        due = callback_on if plan["callback"] else add_days(nowdate(), plan["new_call_in_days"])
        title = (_("Call back: {0}") if plan["callback"] else _("Try again: {0}")).format(prospect.business_name)
        task = create_task(prospect.name, title, script, frappe._dict({**settings.as_dict(), "task_due_days":
                           max(0, (getdate(due) - getdate(nowdate())).days)}))
        record_event(message, "task_created", f"task:{task.provider_message_id}",
                     provider_message_id=task.provider_message_id)  # the new task reports to the same call step
        if member.status == "Active":
            member.db_set("next_action_on", add_days(due, 1))  # the sequence waits until after this call
        result["next_task"] = task.provider_message_id
    if plan["positive"]:
        from reckon_sales_agent.qualification.service import qualify_prospect

        qualify_prospect(prospect.name)
    if note:
        _note_on_lead(message, plan["classification"] or outcome, note)
    _refresh_metrics(message.campaign)
    log_activity(message.company, EVENT[outcome], prospect, note or outcome.replace("_", " "), actor_type="user",
                 agent="Engagement")
    return result


def _close_task(doctype: str, name: str) -> None:
    import frappe

    if doctype == "ToDo":
        frappe.db.set_value("ToDo", name, "status", "Closed")
    elif doctype == "CRM Task":
        frappe.db.set_value("CRM Task", name, "status", "Done")


def _confirm_and_sync(prospect) -> str | None:
    """The salesperson spoke to the business: its name no longer depends on the listing source."""
    import json

    from frappe.utils import now_datetime

    from reckon_sales_agent.crm_sync import sync_to_crm

    provenance = json.loads(prospect.provenance_json or "{}")
    confirmed = {"source": "phone_call", "retrieved_at": str(now_datetime()), "retention_days": None,
                 "attribution": None}
    for field in ("business_name", "phone"):
        if prospect.get(field):
            provenance[field] = confirmed
    prospect.db_set("provenance_json", json.dumps(provenance, sort_keys=True))
    prospect.reload()
    if prospect.review_status != "Approved":
        return prospect.crm_lead
    return sync_to_crm(prospect)
