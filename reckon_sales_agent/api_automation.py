"""Automation Studio: the endpoints behind the visual flow editor.

Everything is limited to the session's Company. Seeing automations needs no special role; saving, switching on or off and
enrolling people needs a Sales Agent manager, and switching on is the approval of what the automation will send.
"""

from __future__ import annotations

import json

import frappe
from frappe import _

from reckon_sales_agent.api_studio import _can_manage
from reckon_sales_agent.automation import engine
from reckon_sales_agent.automation import flow as fl
from reckon_sales_agent.campaigns import person_store, segment_service
from reckon_sales_agent.tenant import current_company, get_tenant_doc
from reckon_sales_agent.usage import assert_entitled

RUN_PAGE = 40


def _require_manager() -> None:
    if not _can_manage():
        frappe.throw(_("Ask a Sales Agent admin or manager to do this."), frappe.PermissionError)


def _json(value):
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value or "{}")
    except ValueError:
        frappe.throw(_("That request is not valid."))


@frappe.whitelist()
def catalog() -> dict:
    """Everything the editor offers: step types and what can be chosen in them."""
    company = current_company()
    assert_entitled(company)
    templates = frappe.get_all("Sales Message Template", filters={"company": company, "status": "Approved",
                                                                   "channel": ["in", ["Email", "SMS", "WhatsApp"]]},
                               fields=["name", "template_name", "channel", "subject"], order_by="modified desc", limit=300)
    return {
        "triggers": fl.TRIGGERS, "checks": fl.CHECKS, "actions": fl.ACTIONS, "units": list(fl.WAIT_UNITS), "templates": templates,
        "segments": frappe.get_all("Sales Segment", filters={"company": company}, fields=["name", "segment_name"], limit=200),
        "forms": frappe.get_all("Sales Capture Form", filters={"company": company}, fields=["slug", "form_name"], limit=200),
        "deal_statuses": frappe.get_all("CRM Deal Status", pluck="name", limit=50),
        "can_manage": _can_manage(),
    }


@frappe.whitelist()
def automations() -> list[dict]:
    company = current_company()
    assert_entitled(company)
    rows = frappe.get_all("Sales Automation", filters={"company": company},
                          fields=["name", "automation_name", "status", "trigger_event", "description", "modified", "activated_on"],
                          order_by="modified desc", limit=200)
    for row in rows:
        counts = {s: frappe.db.count("Sales Automation Run", {"automation": row.name, "status": s})
                  for s in ("Active", "Waiting", "Completed", "Stopped")}
        row["people"] = sum(counts.values())
        row["in_progress"] = counts["Active"] + counts["Waiting"]
        row["completed"] = counts["Completed"]
        row["modified"] = str(row.modified)
        row["activated_on"] = str(row.activated_on or "")
    return rows


def _detail(doc) -> dict:
    flow = engine.flow_of(doc)
    return {"name": doc.name, "automation_name": doc.automation_name, "status": doc.status, "description": doc.description or "",
            "stop_on_reply": bool(doc.stop_on_reply), "flow": flow, "campaign": doc.campaign,
            "issues": fl.issues(flow, engine.template_status(doc.company)), "has_secret": bool(doc.get_password("webhook_secret", raise_exception=False))}


@frappe.whitelist()
def automation(name: str) -> dict:
    doc = get_tenant_doc("Sales Automation", name, "read")
    return {**_detail(doc), "stats": engine.stats(doc)}


@frappe.whitelist(methods=["POST"])
def create(automation_name: str, event: str = "signup", description: str = "") -> str:
    _require_manager()
    company = current_company()
    assert_entitled(company)
    doc = frappe.get_doc({"doctype": "Sales Automation", "company": company, "automation_name": automation_name, "description": description,
                          "flow": json.dumps(fl.new_flow(event if event in fl.TRIGGERS else "signup"))})
    doc.insert()
    return doc.name


@frappe.whitelist(methods=["POST"])
def save(name: str, flow, automation_name: str | None = None, description: str | None = None, stop_on_reply: int | None = None,
         webhook_secret: str | None = None) -> dict:
    """Save what the editor drew. An automation that is on is paused by the change and must be switched on again."""
    _require_manager()
    doc = get_tenant_doc("Sales Automation", name, "write")
    was_active = doc.status == "Active"
    doc.flow = json.dumps(_json(flow))
    if automation_name:
        doc.automation_name = automation_name
    if description is not None:
        doc.description = description
    if stop_on_reply is not None:
        doc.stop_on_reply = 1 if int(stop_on_reply) else 0
    if webhook_secret:
        doc.webhook_secret = webhook_secret
    doc.save()
    return {**_detail(doc), "paused_by_change": was_active and doc.status != "Active"}


@frappe.whitelist(methods=["POST"])
def check(flow) -> dict:
    """The editor's live check: the cleaned flow and what is still missing, without saving."""
    company = current_company()
    clean = fl.normalize(_json(flow))
    return {"flow": clean, "issues": fl.issues(clean, engine.template_status(company))}


@frappe.whitelist(methods=["POST"])
def simulate(flow, decisions=None) -> dict:
    """The path one person would take, step by step and with the time each step is reached. Nothing is sent or changed."""
    clean = fl.normalize(_json(flow))
    path = fl.walk(clean, _json(decisions) if decisions else {})
    for step in path:
        step["when"] = fl.duration_text(step["after_minutes"])
    return {"path": path, "total": fl.duration_text(path[-1]["after_minutes"] if path else 0)}


@frappe.whitelist(methods=["POST"])
def activate(name: str, acknowledge_issues: int = 0) -> dict:
    _require_manager()
    from reckon_sales_agent.api import _require_approver

    _require_approver()  # switching on approves what will be sent, like approving a campaign
    doc = get_tenant_doc("Sales Automation", name, "write")
    result = engine.activate(doc, frappe.session.user, bool(int(acknowledge_issues or 0)))
    engine.poll_segments()
    return result


@frappe.whitelist(methods=["POST"])
def pause(name: str) -> None:
    _require_manager()
    engine.pause(get_tenant_doc("Sales Automation", name, "write"))


@frappe.whitelist(methods=["POST"])
def delete_automation(name: str) -> None:
    _require_manager()
    doc = get_tenant_doc("Sales Automation", name, "delete")
    if doc.status == "Active":
        frappe.throw(_("Pause the automation first."))
    if frappe.db.exists("Sales Automation Run", {"automation": doc.name, "status": ["in", list(engine.LIVE)]}):
        frappe.throw(_("People are still in this automation. Pause it and let them finish, or stop them first."))
    frappe.delete_doc("Sales Automation", doc.name)


@frappe.whitelist()
def runs(name: str, status: str = "", page: int = 0) -> list[dict]:
    """People in the automation, newest first, with the steps they took."""
    doc = get_tenant_doc("Sales Automation", name, "read")
    filters = {"automation": doc.name}
    if status in ("Active", "Waiting", "Completed", "Stopped", "Failed"):
        filters["status"] = status
    rows = frappe.get_all("Sales Automation Run", filters=filters, order_by="modified desc", limit=RUN_PAGE,
                          limit_start=int(page or 0) * RUN_PAGE,
                          fields=["name", "prospect", "status", "current_node", "wake_at", "stop_reason", "started_on", "finished_on", "path"])
    people = {p.name: p for p in frappe.get_all("Sales Prospect", filters={"name": ["in", [r.prospect for r in rows]]},
                                                  fields=["name", "business_name", "contact_name", "email", "phone"])} if rows else {}
    out = []
    for row in rows:
        who = people.get(row.prospect)
        try:
            steps = [p.get("node") for p in json.loads(row.path or "[]") if isinstance(p, dict)]
        except ValueError:
            steps = []
        out.append({"name": row.name, "prospect": row.prospect, "person": (who.contact_name or who.business_name) if who else row.prospect,
                    "email": who.email if who else "", "status": row.status, "at": row.current_node, "next_check": str(row.wake_at or ""),
                    "reason": row.stop_reason or "", "started": str(row.started_on or ""), "steps": steps})
    return out


@frappe.whitelist(methods=["POST"])
def enroll_segment(name: str, segment: str) -> dict:
    """Put everyone in a segment into the automation (people already in it are skipped)."""
    _require_manager()
    doc = get_tenant_doc("Sales Automation", name, "write")
    if doc.status != "Active":
        frappe.throw(_("Switch the automation on first."))
    seg = get_tenant_doc("Sales Segment", segment, "read")
    people = [p["name"] for p in segment_service.resolve(seg)][:500]
    return {**engine.enroll_many(doc, people, f"segment {seg.segment_name}"), "people": len(people)}


@frappe.whitelist(methods=["POST"])
def enroll_person(name: str, email: str = "", phone: str = "") -> dict:
    _require_manager()
    doc = get_tenant_doc("Sales Automation", name, "write")
    if doc.status != "Active":
        frappe.throw(_("Switch the automation on first."))
    from reckon_sales_agent.discovery.normalize import normalize_email, normalize_phone

    found = person_store.find(doc.company, normalize_email(email), normalize_phone(phone) if phone else "")
    if not found:
        frappe.throw(_("No one with that email or phone is on your list yet."))
    return {"enrolled": bool(engine.enroll(doc, found, "by hand"))}


@frappe.whitelist(methods=["POST"])
def trigger(automation: str, email: str = "", phone: str = "", name: str = "", consent_statement: str = "") -> dict:
    """For your own system: start an automation for a person. The caller states how the person agreed to hear from you, and
    that statement is stored as their consent record. Authenticate with an API key and secret of a Sales Agent manager."""
    _require_manager()
    from reckon_sales_agent.discovery.normalize import normalize_email, normalize_phone

    doc = get_tenant_doc("Sales Automation", automation, "write")
    if doc.status != "Active":
        frappe.throw(_("The automation is not switched on."))
    trigger_event = engine.flow_of(doc)["nodes"][engine.flow_of(doc)["start"]]["config"]["event"]
    if trigger_event not in ("api_call", "manual"):
        frappe.throw(_("This automation does not start from an API call."))
    statement = " ".join((consent_statement or "").split())
    if len(statement) < 10:
        frappe.throw(_("Say how this person agreed to hear from you."))
    person = {"email": normalize_email(email), "phone": normalize_phone(phone) if phone else "", "contact_name": " ".join((name or "").split())[:140]}
    if not person["email"] and not person["phone"]:
        frappe.throw(_("Send a valid email or phone number."))
    prospect, outcome = person_store.upsert(doc.company, person, source_type="api", consent_source=f"API: {statement} (by {frappe.session.user})")
    if not prospect:
        return {"enrolled": False, "reason": outcome}
    return {"enrolled": bool(engine.enroll(doc, prospect, "api")), "person": prospect, "outcome": outcome}
