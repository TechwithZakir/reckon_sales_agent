"""Campaign audience, drafting, approval, sending and stop conditions.

Outbound safety, in order, immediately before every send:
kill switch -> outbound enabled -> subscription -> campaign/member state ->
suppression and do-not-contact -> approval -> daily limits -> monthly quota.
While outbound sending is off, approved messages are logged as dry runs.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, get_url, getdate, now_datetime, nowdate

from reckon_sales_agent.campaigns.suppression import is_suppressed, suppress
from reckon_sales_agent.campaigns.templates import footer, render, text_to_html
from reckon_sales_agent.constants import USAGE_AI, USAGE_MESSAGE
from reckon_sales_agent.providers.factory import get_llm
from reckon_sales_agent.providers.llm import UNTRUSTED_RULES, LLMError, untrusted
from reckon_sales_agent.usage import (
    NotEntitled,
    QuotaExceeded,
    assert_entitled,
    get_settings,
    log_activity,
    remaining,
    reserve,
)

PERSONAL_SCHEMA = {
    "type": "object",
    "properties": {"personal_line": {"type": "string"}},
    "required": ["personal_line"],
    "additionalProperties": False,
}
STOP_WORDS = ("unsubscribe", "stop", "remove me", "not interested", "বন্ধ")


# Audience ------------------------------------------------------------------


def eligibility(prospect) -> tuple[bool, str]:
    if prospect.review_status != "Approved":
        return False, "Prospect is not approved."
    if prospect.do_not_contact:
        return False, "Marked do-not-contact."
    if not prospect.email:
        return False, "No public business email."
    if is_suppressed(prospect.company, email=prospect.email, website=prospect.website):
        return False, "On the suppression list."
    return True, "Public business email of an approved, qualified prospect."


def build_members(campaign) -> int:
    filters = {
        "company": campaign.company,
        "review_status": "Approved",
        "qualification_status": "Qualified",
        "fit_score": [">=", campaign.minimum_fit_score or 0],
    }
    if campaign.discovery_campaign:
        filters["discovery_campaign"] = campaign.discovery_campaign
    added = 0
    for name in frappe.get_all("Sales Prospect", filters=filters, pluck="name", limit=5000):
        key = f"{campaign.name}:{name}"
        if frappe.db.exists("Sales Campaign Member", {"idempotency_key": key}):
            continue
        prospect = frappe.get_doc("Sales Prospect", name)
        ok, reason = eligibility(prospect)
        frappe.get_doc({
            "doctype": "Sales Campaign Member",
            "company": campaign.company,
            "campaign": campaign.name,
            "prospect": name,
            "crm_lead": prospect.crm_lead,
            "email": prospect.email if ok else None,
            "status": "Active" if ok else "Ineligible",
            "eligibility_reason": reason,
            "next_action_on": campaign.start_date or nowdate(),
            "idempotency_key": key,
            "unsubscribe_token": frappe.generate_hash(length=32),
        }).insert(ignore_permissions=True)
        added += 1
    _refresh_metrics(campaign.name)
    return added


# Drafting ------------------------------------------------------------------


def draft_due_messages(campaign) -> int:
    """Create the next step's draft for members whose next action is due."""
    steps = sorted(campaign.steps, key=lambda s: s.step_no)
    created = 0
    for member_name in frappe.get_all(
        "Sales Campaign Member",
        filters={"campaign": campaign.name, "status": "Active", "next_action_on": ["<=", nowdate()]},
        pluck="name",
        limit=500,
    ):
        member = frappe.get_doc("Sales Campaign Member", member_name)
        if member.sequence_position >= len(steps):
            member.db_set({"status": "Completed", "stop_reason": "sequence finished"})
            continue
        step = steps[member.sequence_position]
        key = f"{member.name}:{step.step_no}"
        if frappe.db.exists("Sales Outreach Message", {"idempotency_key": key}):
            continue
        draft_message(campaign, member, step, key)
        created += 1
    return created


def draft_message(campaign, member, step, key: str) -> str:
    settings = get_settings(campaign.company)
    prospect = frappe.get_doc("Sales Prospect", member.prospect)
    values = {
        "business_name": prospect.business_name,
        "city": prospect.city,
        "industry": prospect.industry,
        "sender_name": settings.sender_name or campaign.company,
        "offer": campaign.offer or "",
        "company": campaign.company,
        "personal_line": "",
    }
    ai_generated = 0
    if step.use_ai_personalisation:
        line = _personal_line(campaign, prospect)
        if line:
            values["personal_line"] = line
            ai_generated = 1
    subject = render(step.subject_template, values, escape=False)[:140]
    body = text_to_html(render(step.body_template, values))
    unsubscribe_url = get_url(f"/api/method/reckon_sales_agent.api.unsubscribe?token={member.unsubscribe_token}")
    body += footer(values["sender_name"], settings.physical_address, unsubscribe_url)
    approval = settings.human_approval_required
    message = frappe.get_doc({
        "doctype": "Sales Outreach Message",
        "company": campaign.company,
        "campaign": campaign.name,
        "member": member.name,
        "prospect": prospect.name,
        "step_no": step.step_no,
        "recipient": member.email,
        "subject": subject,
        "body": body,
        "ai_generated": ai_generated,
        "status": "Draft" if approval else "Approved",
        "idempotency_key": key,
    }).insert(ignore_permissions=True)
    record_event(message, "drafted", f"draft:{message.name}")
    return message.name


def _personal_line(campaign, prospect) -> str:
    llm = get_llm(campaign.company)
    if not llm or not prospect.latest_research or remaining(campaign.company, USAGE_AI) <= 0:
        return ""
    report = frappe.get_doc("Sales Research Report", prospect.latest_research)
    facts = "\n".join(f"- {row.statement}" for row in report.facts if not row.is_inference)[:3000]
    try:
        reserve(campaign.company, USAGE_AI, 1, prospect)
        data = llm.complete_json(
            "You write one friendly, specific opening sentence for a B2B sales email from a "
            f"Bangladeshi company. {UNTRUSTED_RULES} Use only facts listed in the data; "
            "make no claims about the recipient's needs, plans or purchases. At most 40 words.",
            untrusted("research facts", f"Company: {prospect.business_name}\n{facts}"),
            PERSONAL_SCHEMA,
            max_tokens=2000,
        )
    except (LLMError, QuotaExceeded):
        return ""
    return " ".join(str(data.get("personal_line") or "").split())[:300]


# Approval and sending ------------------------------------------------------


def approve_message(message) -> None:
    if message.status != "Draft":
        frappe.throw(_("Only drafts can be approved."))
    message.db_set({"status": "Approved", "approved_by": frappe.session.user})
    record_event(message, "approved", f"approved:{message.name}")


def send_due_messages(company: str | None = None) -> int:
    filters = {"status": "Approved"}
    if company:
        filters["company"] = company
    sent = 0
    for name in frappe.get_all("Sales Outreach Message", filters=filters, pluck="name",
                               order_by="creation asc", limit=500):
        try:
            if send_message(frappe.get_doc("Sales Outreach Message", name)):
                sent += 1
        except Exception:
            frappe.db.rollback()
            frappe.log_error(title="Sales Agent send failed", reference_doctype="Sales Outreach Message",
                             reference_name=name)
        frappe.db.commit()
    return sent


def send_message(message) -> bool:
    """Send one approved message after re-checking every safety condition."""
    settings = get_settings(message.company)
    campaign = frappe.get_doc("Sales Campaign", message.campaign)
    member = frappe.get_doc("Sales Campaign Member", message.member)
    prospect = frappe.get_doc("Sales Prospect", message.prospect)

    if settings.kill_switch:
        return False  # paused: leave approved messages waiting
    if campaign.status != "Active" or member.status != "Active":
        return _cancel(message, "Campaign or member is no longer active.")
    if campaign.end_date and getdate(campaign.end_date) < getdate(nowdate()):
        return _cancel(message, "Campaign ended.")
    if prospect.do_not_contact or is_suppressed(message.company, email=message.recipient, website=prospect.website):
        member.db_set({"status": "Stopped", "stop_reason": "suppressed"})
        return _cancel(message, "Recipient is suppressed.")
    if settings.human_approval_required and not message.approved_by:
        return False
    try:
        assert_entitled(message.company)
    except NotEntitled:
        return False
    if _sent_today(message.company) >= (settings.daily_message_limit or 0):
        return False
    if _sent_today(message.company, campaign.name) >= (campaign.daily_limit or 0):
        return False

    if not settings.outbound_enabled:
        message.db_set({"status": "Dry Run", "sent_on": now_datetime()})
        record_event(message, "dry_run", f"dry_run:{message.name}")
        _advance(campaign, member)
        return True

    reserve(message.company, USAGE_MESSAGE, 1, message)
    from frappe.core.doctype.communication.email import make

    result = make(
        doctype="Sales Outreach Message",
        name=message.name,
        content=message.body,
        subject=message.subject,
        recipients=message.recipient,
        sender_full_name=settings.sender_name or message.company,
        send_email=True,
        communication_medium="Email",
    )
    message_id = frappe.db.get_value("Communication", result.get("name"), "message_id")
    message.db_set({"status": "Sent", "sent_on": now_datetime()})
    record_event(message, "sent", f"sent:{message.name}", provider_message_id=message_id)
    _advance(campaign, member)
    return True


def _advance(campaign, member) -> None:
    steps = sorted(campaign.steps, key=lambda s: s.step_no)
    position = (member.sequence_position or 0) + 1
    if position >= len(steps):
        member.db_set({"sequence_position": position, "status": "Completed", "next_action_on": None,
                       "stop_reason": "sequence finished", "last_event": "sent"})
    else:
        member.db_set({"sequence_position": position, "last_event": "sent",
                       "next_action_on": add_days(nowdate(), steps[position].delay_days or 0)})
    _refresh_metrics(campaign.name)


def _cancel(message, reason: str) -> bool:
    message.db_set({"status": "Cancelled", "error": reason})
    record_event(message, "stopped", f"stopped:{message.name}", detail=reason)
    return False


def _sent_today(company: str, campaign: str | None = None) -> int:
    filters = {"company": company, "event_type": ["in", ["sent", "dry_run"]],
               "event_time": [">=", f"{nowdate()} 00:00:00"]}
    if campaign:
        filters["campaign"] = campaign
    return frappe.db.count("Sales Communication Event", filters)


# Events and stop conditions ------------------------------------------------


def record_event(message, event_type: str, key: str, provider_message_id=None, detail=None) -> None:
    if frappe.db.exists("Sales Communication Event", {"idempotency_key": key}):
        return
    frappe.get_doc({
        "doctype": "Sales Communication Event",
        "company": message.company,
        "event_type": event_type,
        "campaign": message.campaign,
        "member": message.member,
        "message": message.name,
        "event_time": now_datetime(),
        "provider_message_id": provider_message_id,
        "idempotency_key": key,
        "detail": (detail or "")[:500] or None,
    }).insert(ignore_permissions=True)


def handle_communication(doc, method=None) -> None:
    """``Communication.after_insert``: a reply to an outreach message stops its sequence."""
    if doc.reference_doctype != "Sales Outreach Message" or doc.sent_or_received != "Received":
        return
    message = frappe.get_doc("Sales Outreach Message", doc.reference_name)
    member = frappe.get_doc("Sales Campaign Member", message.member)
    text = (doc.content or "")[:2000].lower()
    opted_out = any(word in text for word in STOP_WORDS)
    event = "unsubscribed" if opted_out else "replied"
    record_event(message, event, f"{event}:{doc.name}")
    member.db_set({"status": "Stopped", "stop_reason": event, "last_event": event, "next_action_on": None})
    if opted_out and member.email:
        suppress(message.company, "Email", member.email, "Unsubscribed", f"reply {doc.name}")
    _cancel_pending(member.name, f"Recipient {event}.")
    _refresh_metrics(message.campaign)
    log_activity(message.company, f"member_{event}", member, "", "provider")


def unsubscribe_member(token: str) -> bool:
    member_name = frappe.db.get_value("Sales Campaign Member", {"unsubscribe_token": token})
    if not member_name:
        return False
    member = frappe.get_doc("Sales Campaign Member", member_name)
    if member.email:
        suppress(member.company, "Email", member.email, "Unsubscribed", "unsubscribe link")
    member.db_set({"status": "Stopped", "stop_reason": "unsubscribed", "last_event": "unsubscribed",
                   "next_action_on": None})
    last = frappe.db.get_value("Sales Outreach Message", {"member": member.name}, "name", order_by="creation desc")
    if last:
        record_event(frappe.get_doc("Sales Outreach Message", last), "unsubscribed", f"unsubscribed:{member.name}")
    _cancel_pending(member.name, "Recipient unsubscribed.")
    _refresh_metrics(member.campaign)
    return True


def stop_member(member, reason: str) -> None:
    member.db_set({"status": "Stopped", "stop_reason": reason, "next_action_on": None})
    _cancel_pending(member.name, reason)
    _refresh_metrics(member.campaign)


def handle_deal(doc, method=None) -> None:
    """``CRM Deal.after_insert``: a deal from a campaign lead converts its members."""
    if not doc.get("lead"):
        return
    for name in frappe.get_all("Sales Campaign Member", filters={"crm_lead": doc.lead,
                                                                  "status": ["in", ["Active", "Completed", "Stopped"]]},
                               pluck="name"):
        member = frappe.get_doc("Sales Campaign Member", name)
        member.db_set({"status": "Converted", "last_event": "converted", "next_action_on": None})
        _cancel_pending(name, "Converted to a deal.")
        _refresh_metrics(member.campaign)


def _cancel_pending(member_name: str, reason: str) -> None:
    for name in frappe.get_all("Sales Outreach Message",
                               filters={"member": member_name, "status": ["in", ["Draft", "Approved"]]},
                               pluck="name"):
        frappe.db.set_value("Sales Outreach Message", name, {"status": "Cancelled", "error": reason})


def _refresh_metrics(campaign_name: str) -> None:
    def count_members(**filters):
        return frappe.db.count("Sales Campaign Member", {"campaign": campaign_name, **filters})

    def count_events(event_type):
        return frappe.db.count("Sales Communication Event", {"campaign": campaign_name, "event_type": event_type})

    frappe.db.set_value("Sales Campaign", campaign_name, {
        "member_count": count_members(),
        "sent_count": count_events("sent") + count_events("dry_run"),
        "reply_count": count_events("replied"),
        "unsubscribe_count": count_events("unsubscribed"),
        "bounce_count": count_events("bounced"),
        "converted_count": count_members(status="Converted"),
    }, update_modified=False)


# Scheduler -----------------------------------------------------------------


def run_campaign_tick() -> None:
    """Hourly: draft due steps for active campaigns, then send what is approved."""
    for name in frappe.get_all("Sales Campaign", filters={"status": "Active"}, pluck="name"):
        campaign = frappe.get_doc("Sales Campaign", name)
        try:
            assert_entitled(campaign.company)
            if get_settings(campaign.company).kill_switch:
                continue
            draft_due_messages(campaign)
            frappe.db.commit()
        except NotEntitled:
            continue
        except Exception:
            frappe.db.rollback()
            frappe.log_error(title="Sales Agent campaign tick failed", reference_doctype="Sales Campaign",
                             reference_name=name)
    send_due_messages()
