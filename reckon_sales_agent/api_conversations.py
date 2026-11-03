"""Backend for the Conversations page: every lead's thread across channels, and AI replies to approve."""

from __future__ import annotations

import json

import frappe
from frappe import _

from reckon_sales_agent.tenant import current_company, get_tenant_doc


@frappe.whitelist()
def threads() -> list[dict]:
    from reckon_sales_agent.agents.omni import threads as list_threads

    return list_threads(current_company())


@frappe.whitelist()
def thread(prospect: str) -> dict:
    from reckon_sales_agent.agents.conversations import agents_for
    from reckon_sales_agent.agents.omni import reply_channels, timeline

    doc = get_tenant_doc("Sales Prospect", prospect, "read")
    drafts = frappe.get_all("Sales Outreach Message", filters={"prospect": prospect, "status": "Draft"},
                            fields=["name", "channel", "recipient", "subject", "body", "error", "is_reply"],
                            order_by="creation desc", limit=10)
    return {
        "prospect": {k: doc.get(k) for k in ("name", "business_name", "email", "phone", "city", "website",
                                             "crm_lead", "source_type", "consent_source", "do_not_contact")},
        "timeline": timeline(prospect),
        "drafts": drafts,
        "conversation": _conversation(doc),
        "channels": reply_channels(doc.name),
        "agents": agents_for(doc.company),
        "me": frappe.session.user,
        "wa_templates": _wa_templates(doc.company),
    }


def _conversation(prospect_doc) -> dict:
    from reckon_sales_agent.agents.conversations import get, mode_for, parse_tags

    convo = get(prospect_doc.company, prospect_doc.name)
    return {"name": convo.name, "status": convo.status, "assigned_to": convo.assigned_to, "ai_mode": convo.ai_mode,
            "effective": mode_for(prospect_doc.company, prospect_doc.name), "handoff_reason": convo.handoff_reason,
            "tags": parse_tags(frappe.db.get_value("Sales Conversation", convo.name, "_user_tags"))}


def _convo(prospect: str):
    from reckon_sales_agent.agents.conversations import get

    doc = get_tenant_doc("Sales Prospect", prospect, "read")
    convo = get(doc.company, doc.name)
    get_tenant_doc("Sales Conversation", convo.name, "write")
    return doc, convo


@frappe.whitelist(methods=["POST"])
def assign(prospect: str, user: str | None = None) -> dict:
    from reckon_sales_agent.agents.conversations import agents_for, notify

    doc, convo = _convo(prospect)
    if user and user not in {a["user"] for a in agents_for(doc.company)}:
        frappe.throw(_("{0} is not one of this Company's users.").format(user))
    from reckon_sales_agent.agents.ownership import reassign

    convo.db_set("assigned_to", user or None)
    moved = reassign(doc.company, doc.name, user)  # the whole lead follows: tasks, CRM lead, owner
    if user and user != frappe.session.user:
        notify(convo, user, f"{frappe.session.user} gave you {convo.title}"
                            + (f" with {moved} open task(s)" if moved else ""))
    return _changed(prospect)


@frappe.whitelist(methods=["POST"])
def set_status(prospect: str, status: str) -> dict:
    from frappe.utils import now_datetime

    from reckon_sales_agent.agents.conversations import NEEDS_HUMAN, remove_tag

    if status not in ("Open", "Resolved"):
        frappe.throw(_("Unknown status."))
    _doc, convo = _convo(prospect)
    convo.db_set({"status": status, "resolved_on": now_datetime() if status == "Resolved" else None,
                  "handoff_reason": None if status == "Resolved" else convo.handoff_reason})
    if status == "Resolved":
        remove_tag(convo.name, NEEDS_HUMAN)
    return _changed(prospect)


@frappe.whitelist(methods=["POST"])
def set_mode(prospect: str, mode: str) -> dict:
    from reckon_sales_agent.agents.conversations import MODES

    if mode not in MODES:
        frappe.throw(_("Unknown AI mode."))
    _doc, convo = _convo(prospect)
    convo.db_set("ai_mode", mode)
    return _changed(prospect)


@frappe.whitelist(methods=["POST"])
def tag(prospect: str, tag: str, remove: int = 0) -> dict:
    from reckon_sales_agent.agents.conversations import add_tag, remove_tag

    _doc, convo = _convo(prospect)
    (remove_tag if int(remove or 0) else add_tag)(convo.name, tag)
    return _changed(prospect)


@frappe.whitelist(methods=["POST"])
def send(prospect: str, channel: str, text: str, template: str | None = None) -> str:
    """A person's own reply on the chosen channel, sent now."""
    from reckon_sales_agent.agents.omni import compose
    from reckon_sales_agent.usage import assert_entitled

    doc = get_tenant_doc("Sales Prospect", prospect, "write")
    assert_entitled(doc.company)
    return compose(doc.name, channel, text[:3000], template)


@frappe.whitelist()
def suggest(prospect: str, instruction: str | None = None) -> str:
    from reckon_sales_agent.agents.omni import draft_reply
    from reckon_sales_agent.usage import assert_entitled

    doc = get_tenant_doc("Sales Prospect", prospect, "write")
    assert_entitled(doc.company)
    return draft_reply(doc.name, reason="the salesperson asked for a reply", instruction=(instruction or "")[:500])


@frappe.whitelist()
def approve_and_send(message: str) -> str:
    """Approve one draft and send it now (within limits; dry run when sending is off)."""
    from reckon_sales_agent import api
    from reckon_sales_agent.campaigns.engine import send_message

    doc = get_tenant_doc("Sales Outreach Message", message, "write")
    api.approve_messages(json.dumps([doc.name]))
    sent = send_message(frappe.get_doc("Sales Outreach Message", doc.name))
    status = frappe.db.get_value("Sales Outreach Message", doc.name, "status")
    from reckon_sales_agent.agents.inbox_events import notify_inbox
    notify_inbox(doc.company, doc.name)
    if not sent and status == "Approved":
        return _("Approved; it goes out when the daily limit allows.")
    return status


@frappe.whitelist()
def discard(message: str) -> None:
    doc = get_tenant_doc("Sales Outreach Message", message, "write")
    if doc.status != "Draft":
        frappe.throw(_("Only drafts can be discarded."))
    doc.db_set({"status": "Cancelled", "error": "Discarded by a person"})
    from reckon_sales_agent.agents.inbox_events import notify_inbox
    notify_inbox(doc.company, doc.name)


def _changed(prospect: str) -> dict:
    """A team action changed this lead's conversation: tell everyone on the team, then return the thread."""
    from reckon_sales_agent.agents.inbox_events import notify_inbox

    notify_inbox(frappe.db.get_value("Sales Prospect", prospect, "company"), prospect)
    return thread(prospect)


def _wa_templates(company: str) -> list[dict]:
    """The WhatsApp templates Meta approved for this Company's account (frappe_whatsapp)."""
    from reckon_sales_agent.usage import get_settings

    if "frappe_whatsapp" not in frappe.get_installed_apps() or not frappe.db.exists("DocType", "WhatsApp Templates"):
        return []
    filters = {"status": ["in", ["APPROVED", "Approved"]]}
    account = get_settings(company).get("whatsapp_account")
    if account:
        filters["whatsapp_account"] = account
    return frappe.get_all("WhatsApp Templates", filters=filters, fields=["name", "template_name", "language"], limit=200)


@frappe.whitelist(methods=["POST"])
def block(prospect: str, blocked: int = 1) -> dict:
    """Stop messaging this lead, or undo it. Reversible: it only sets the lead's do-not-contact flag."""
    get_tenant_doc("Sales Prospect", prospect, "write")
    frappe.db.set_value("Sales Prospect", prospect, "do_not_contact", 1 if int(blocked) else 0)
    return _changed(prospect)


@frappe.whitelist(methods=["POST"])
def delete_chat(prospect: str) -> dict:
    """Delete this conversation's chat messages. The lead, its email and its records stay. Cannot be undone."""
    doc = get_tenant_doc("Sales Prospect", prospect, "write")
    frappe.db.delete("Sales Chat Message", {"prospect": prospect, "company": doc.company})
    return _changed(prospect)

