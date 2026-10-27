"""Backend for the Meetings page: book proposed demos, see what is coming, log what happened."""

from __future__ import annotations

import json

import frappe
from frappe.utils import now_datetime

from reckon_sales_agent.tenant import current_company, get_tenant_doc

FIELDS = ["name", "title", "status", "prospect", "crm_lead", "assigned_to", "mode", "location", "slot_options",
          "starts_on", "ends_on", "invite_message", "outcome_notes", "source"]


@frappe.whitelist()
def board() -> dict:
    company = current_company()
    rows = frappe.get_list("Sales Meeting", filters={"company": company}, fields=FIELDS,
                           order_by="starts_on asc, creation desc", page_length=200)
    names = {p.name: p for p in frappe.get_all("Sales Prospect", filters={"name": ["in", [r.prospect for r in rows] or [""]]},
                                               fields=["name", "business_name", "phone", "email"])}
    invites = {m.name: m.status for m in frappe.get_all("Sales Outreach Message", filters={
        "name": ["in", [r.invite_message for r in rows if r.invite_message] or [""]]}, fields=["name", "status"])}
    now = now_datetime()
    out = {"to_book": [], "upcoming": [], "to_log": [], "done": []}
    for r in rows:
        p = names.get(r.prospect) or {}
        item = {**r, "business": p.get("business_name"), "phone": p.get("phone"), "email": p.get("email"),
                "slots": json.loads(r.slot_options or "[]"), "invite_status": invites.get(r.invite_message)}
        if r.status == "Proposed":
            out["to_book"].append(item)
        elif r.status == "Booked" and r.ends_on and r.ends_on < now:
            out["to_log"].append(item)
        elif r.status == "Booked":
            out["upcoming"].append(item)
        else:
            out["done"].append(item)
    out["done"] = out["done"][-20:]
    return out


@frappe.whitelist()
def book(meeting: str, starts_on: str) -> str:
    from reckon_sales_agent.agents.meetings import book as do_book

    get_tenant_doc("Sales Meeting", meeting, "write")
    return do_book(meeting, starts_on)


@frappe.whitelist()
def outcome(meeting: str, result: str, notes: str | None = None) -> None:
    from reckon_sales_agent.agents.meetings import record_outcome

    get_tenant_doc("Sales Meeting", meeting, "write")
    record_outcome(meeting, result, notes or "")


@frappe.whitelist()
def propose(prospect: str) -> str | None:
    from reckon_sales_agent.agents.meetings import start_meeting

    get_tenant_doc("Sales Prospect", prospect, "write")
    return start_meeting(prospect, "proposed by a person")
