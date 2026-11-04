"""Engagement agent: answers routine questions from approved knowledge, escalates the rest, handles delivery events.

The agent never decides alone on pricing exceptions, contracts, complaints or
legal matters, and every message it sends goes through the same send path as
campaign messages: consent, suppression, kill switch and limits are checked
again just before sending.
"""

from __future__ import annotations

import frappe
from frappe.utils import get_url, now_datetime

from reckon_sales_agent.agents.approvals import fingerprint, message_payload
from reckon_sales_agent.agents.content import check_step
from reckon_sales_agent.agents.engagement import (
    ANSWER_SCHEMA,
    ANSWER_SYSTEM,
    ESCALATE,
    SEND,
    answer_route,
)
from reckon_sales_agent.agents.policy import ALLOW, decide
from reckon_sales_agent.constants import USAGE_AI
from reckon_sales_agent.providers.factory import get_llm
from reckon_sales_agent.providers.llm import LLMError, untrusted
from reckon_sales_agent.usage import QuotaExceeded, get_settings, log_activity, remaining, reserve


def answer_question(message, text: str, source_key: str) -> tuple[str, str]:
    """Answer a prospect's question from approved knowledge; returns (route, reason) for the follow-up task."""
    from reckon_sales_agent.agents.content import knowledge_prompt
    from reckon_sales_agent.agents.content_agent import approved_knowledge
    from reckon_sales_agent.campaigns.replies import strip_quoted

    settings = get_settings(message.company)
    knowledge = approved_knowledge(message.company)
    llm = get_llm(message.company)
    if not knowledge or not llm or remaining(message.company, USAGE_AI) <= 0:
        return ESCALATE, "No approved knowledge or AI available to answer; reply personally."
    try:
        reserve(message.company, USAGE_AI, 1, message)
        frappe.db.commit()
        data = llm.complete_json(ANSWER_SYSTEM, untrusted("approved knowledge", knowledge_prompt(knowledge)) + "\n"
                                 + untrusted("question", strip_quoted(text)), ANSWER_SCHEMA, max_tokens=2000)
    except (LLMError, QuotaExceeded) as exc:
        return ESCALATE, f"The AI could not draft an answer ({exc}); reply personally."
    answer = " ".join(str(data.get("answer") or "").split())[:1200]
    knowledge_text = "\n".join(f"{k.title}\n{k.content}" for k in knowledge)
    pricing_text = "\n".join(k.content for k in knowledge if k.category in ("Pricing", "Offer"))
    channel = message.get("channel") or "Email"
    issues = check_step({"step_no": 0, "channel": channel, "subject_template": "", "body_template": answer},
                        knowledge_text, pricing_text, []) if answer else []
    prospect = frappe.get_doc("Sales Prospect", message.prospect)
    policy = decide("answer_routine_question", {
        "suppressed": bool(prospect.do_not_contact),
        "kill_switch": bool(settings.kill_switch),
        "channel_allows": channel in ("Email", "WhatsApp"),  # the customer just wrote: WhatsApp window is open
        "require_review": not settings.get("auto_answer_questions"),
    })
    route, reason = answer_route(bool(data.get("can_answer")) and bool(answer), data.get("topics") or [], issues,
                                 policy.outcome == ALLOW)
    if route == ESCALATE:
        log_activity(message.company, "reply_escalated", message, reason, actor_type="agent", agent="Engagement",
                     policy_outcome="needs a person")
        return route, reason
    reply = _reply_message(message, answer, source_key, auto=route == SEND)
    if route == SEND:
        from reckon_sales_agent.campaigns.engine import send_message

        send_message(reply)
    log_activity(message.company, "reply_answered" if route == SEND else "reply_answer_drafted", reply, reason,
                 actor_type="agent", agent="Engagement", policy_outcome=policy.outcome)
    return route, reason


def _reply_message(message, answer: str, source_key: str, auto: bool):
    """An outreach message answering the prospect, on the channel they wrote on."""
    from reckon_sales_agent.campaigns.templates import footer, text_to_html

    settings = get_settings(message.company)
    member = frappe.get_doc("Sales Campaign Member", message.member)
    sender = settings.sender_name or message.company
    body = text_to_html(frappe.utils.escape_html(f"{answer}\n\n{sender}"))
    if (message.get("channel") or "Email") == "Email":
        body += footer(sender, settings.physical_address,
                       get_url(f"/api/method/reckon_sales_agent.api.unsubscribe?token={member.unsubscribe_token}"))
    subject = message.subject or ""
    doc = frappe.get_doc({
        "doctype": "Sales Outreach Message",
        "company": message.company,
        "campaign": message.campaign,
        "member": message.member,
        "prospect": message.prospect,
        "step_no": 0,
        "channel": message.get("channel") or "Email",
        "recipient": message.recipient,
        "subject": (subject if subject.lower().startswith("re:") else f"Re: {subject}")[:140] if subject else "",
        "body": body,
        "ai_generated": 1,
        "is_reply": 1,
        "in_reply_to": source_key[:140],
        "status": "Approved" if auto else "Draft",
        "auto_approved_by_policy": 1 if auto else 0,
        "idempotency_key": f"answer:{source_key}"[:140],
    })
    if auto:
        doc.approval_fingerprint = fingerprint(message_payload(doc))
    return doc.insert(ignore_permissions=True)


# Delivery events ---------------------------------------------------------------


def apply_email_event(event: dict) -> bool:
    """Act on one verified email event; returns False when it is unknown or already handled."""
    from reckon_sales_agent.campaigns.engine import _cancel_pending, _suppress_member, record_event

    key = f"email_event:{event['id']}"
    if frappe.db.exists("Sales Communication Event", {"idempotency_key": key}):
        return False  # the provider retried: already handled
    message = None
    if event.get("message") and frappe.db.exists("Sales Outreach Message", event["message"]):
        message = frappe.get_doc("Sales Outreach Message", event["message"])
    elif event.get("message"):
        name = frappe.db.get_value("Sales Communication Event", {"provider_message_id": event["message"]}, "message")
        message = frappe.get_doc("Sales Outreach Message", name) if name else None
    if not message:
        return False
    member = frappe.get_doc("Sales Campaign Member", message.member)
    if event["type"] == "delivered":
        record_event(message, "delivered", key)
        return True
    if event["type"] == "bounce" and not event["hard"]:
        record_event(message, "bounced", key, detail="soft bounce")  # temporary: keep the address
        return True
    # Hard bounce, spam complaint or the recipient's unsubscribe: all stop the sequence and suppress the address.
    reason = {"bounce": "hard bounce", "complaint": "spam complaint", "unsubscribe": "unsubscribed"}[event["type"]]
    outcome = {"bounce": "bounced", "complaint": "complained", "unsubscribe": "unsubscribed"}[event["type"]]
    _suppress_member(message.company, member, "Email", f"{reason} {event['id']}")
    if member.status == "Active":
        member.db_set({"status": "Stopped", "stop_reason": reason, "next_action_on": None})
        _cancel_pending(member.name, f"Email {reason}.")
    record_event(message, outcome, key, detail=reason)
    log_activity(message.company, f"reply_{outcome}", member, reason, actor_type="provider", agent="Engagement",
                 policy_outcome="suppressed")
    return True


def handle_communication_status(doc, method=None) -> None:
    """``Communication.on_update``: Frappe marked an outreach email as bounced or rejected."""
    if doc.reference_doctype != "Sales Outreach Message" or doc.get("delivery_status") not in ("Bounced", "Rejected"):
        return
    apply_email_event({"id": f"frappe:{doc.name}", "type": "bounce", "hard": True, "email": doc.recipients or "",
                       "message": doc.reference_name})


def record_whatsapp_inbound(phone: str, company: str | None = None) -> None:
    """The customer wrote on WhatsApp: the 24-hour service window opens for every prospect with this number."""
    from reckon_sales_agent.discovery.normalize import normalize_phone

    normalized = normalize_phone(phone)
    if not normalized:
        return
    filters = {"normalized_phone": normalized, **({"company": company} if company else {})}
    for name in frappe.get_all("Sales Prospect", filters=filters, pluck="name", limit=50):
        frappe.db.set_value("Sales Prospect", name, "whatsapp_last_inbound", now_datetime(), update_modified=False)
