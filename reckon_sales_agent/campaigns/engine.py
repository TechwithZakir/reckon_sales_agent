"""Campaign audience, drafting, approval, sending and stop conditions.

Outbound safety, in order, immediately before every send:
kill switch -> outbound enabled -> subscription -> campaign/member state ->
suppression and do-not-contact -> approval -> daily limits -> monthly quota.
While outbound sending is off, approved messages are logged as dry runs.
"""

from __future__ import annotations

from html import escape as html_escape

import frappe
from frappe import _
from frappe.utils import add_days, get_url, getdate, now_datetime, nowdate

from reckon_sales_agent.campaigns.suppression import is_suppressed, suppress
from reckon_sales_agent.campaigns.templates import footer, render, text_to_html
from reckon_sales_agent.constants import TASK_CHANNELS, USAGE_AI, USAGE_MESSAGE
from reckon_sales_agent.discovery.normalize import normalize_phone
from reckon_sales_agent.providers.channels import ChannelUnavailable, reachability, send
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


# Audience ------------------------------------------------------------------


def step_channels(campaign) -> list[str]:
    return sorted({step.channel or "Email" for step in campaign.steps})


def eligibility(prospect, campaign=None, settings=None) -> tuple[bool, str]:
    """Eligible when approved, not suppressed and reachable on at least one step's channel."""
    if prospect.review_status != "Approved":
        return False, "Prospect is not approved."
    if prospect.do_not_contact:
        return False, "Marked do-not-contact."
    if is_suppressed(prospect.company, email=prospect.email, phone=prospect.phone, website=prospect.website):
        return False, "On the suppression list."
    channels = step_channels(campaign) if campaign else ["Email"]
    settings = settings or get_settings(prospect.company)
    reasons = []
    for channel in channels:
        ok, reason, _recipient = reachability(channel, prospect, settings)
        if ok:
            return True, f"Reachable by {channel}: {reason}"
        reasons.append(f"{channel}: {reason}")
    return False, " ".join(reasons)


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
    settings = get_settings(campaign.company)
    for name in frappe.get_all("Sales Prospect", filters=filters, pluck="name", limit=5000):
        key = f"{campaign.name}:{name}"
        if frappe.db.exists("Sales Campaign Member", {"idempotency_key": key}):
            continue
        prospect = frappe.get_doc("Sales Prospect", name)
        ok, reason = eligibility(prospect, campaign, settings)
        frappe.get_doc({
            "doctype": "Sales Campaign Member",
            "company": campaign.company,
            "campaign": campaign.name,
            "prospect": name,
            "crm_lead": prospect.crm_lead,
            "email": prospect.email if ok else None,
            "phone": prospect.phone if ok else None,
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
    settings = get_settings(campaign.company)
    created = 0
    for member_name in frappe.get_all(
        "Sales Campaign Member",
        filters={"campaign": campaign.name, "status": "Active", "next_action_on": ["<=", nowdate()]},
        pluck="name",
        limit=500,
    ):
        member = frappe.get_doc("Sales Campaign Member", member_name)
        # Skip steps whose channel cannot reach this member (no consent, no CRM lead, ...).
        while member.sequence_position < len(steps):
            step = steps[member.sequence_position]
            prospect = frappe.get_doc("Sales Prospect", member.prospect)
            reachable, reason, _recipient = reachability(step.channel or "Email", prospect, settings)
            if reachable:
                break
            member.db_set({"sequence_position": member.sequence_position + 1,
                           "last_event": f"skipped step {step.step_no}: {reason}"[:140]})
        if member.sequence_position >= len(steps):
            member.db_set({"status": "Completed", "stop_reason": "sequence finished", "next_action_on": None})
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
    channel = step.channel or "Email"
    _ok, _reason, recipient = reachability(channel, prospect, settings)
    subject = render(step.subject_template, values, escape=False)[:140]
    unsubscribe_url = get_url(f"/api/method/reckon_sales_agent.api.unsubscribe?token={member.unsubscribe_token}")
    if channel == "Email":
        body = text_to_html(render(step.body_template, values))
        body += footer(values["sender_name"], settings.physical_address, unsubscribe_url)
    elif channel in ("SMS", "WhatsApp"):
        text = render(step.body_template, values, escape=False).strip()
        body = text_to_html(html_escape(f"{text}\n\n{values['sender_name']} · Opt out: {unsubscribe_url}"))
    else:  # internal CRM task for a person: call, LinkedIn, visit
        body = text_to_html(render(step.body_template, values))
    # Internal tasks contact nobody, so they need no approval; outreach does.
    approval = settings.human_approval_required and channel not in TASK_CHANNELS
    message = frappe.get_doc({
        "doctype": "Sales Outreach Message",
        "company": campaign.company,
        "campaign": campaign.name,
        "member": member.name,
        "prospect": prospect.name,
        "step_no": step.step_no,
        "channel": channel,
        "recipient": recipient,
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
    channel = message.get("channel") or "Email"
    if prospect.do_not_contact or is_suppressed(
        message.company, email=prospect.email, phone=prospect.phone, website=prospect.website,
        channel=channel if channel in ("Email", "SMS", "WhatsApp") else "Email",
    ):
        member.db_set({"status": "Stopped", "stop_reason": "suppressed"})
        return _cancel(message, "Recipient is suppressed.")
    reachable, reason, recipient = reachability(channel, prospect, settings)
    if not reachable or (recipient and message.recipient and recipient != message.recipient
                         and channel not in TASK_CHANNELS):
        return _cancel(message, f"No longer reachable: {reason}")
    if channel in TASK_CHANNELS:
        # Internal work item for a person; no outreach, so no approval, limits or dry run.
        result = send(channel, message, settings)
        message.db_set({"status": "Sent", "sent_on": now_datetime()})
        record_event(message, "task_created", f"task:{message.name}", provider_message_id=result.provider_message_id)
        _advance(campaign, member)
        return True
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
    try:
        result = send(channel, message, settings)
    except ChannelUnavailable as exc:
        message.db_set({"status": "Failed", "error": str(exc)[:500]})
        record_event(message, "failed", f"failed:{message.name}", detail=str(exc))
        return False
    message.db_set({"status": "Sent", "sent_on": now_datetime()})
    record_event(message, "sent", f"sent:{message.name}", provider_message_id=result.provider_message_id)
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
    """``Communication.after_insert``: an email reply to an outreach message."""
    if doc.reference_doctype != "Sales Outreach Message" or doc.sent_or_received != "Received":
        return
    from reckon_sales_agent.providers.channels import html_to_text

    receive_reply(doc.reference_name, html_to_text(doc.content or ""), f"email:{doc.name}", "Email")


def handle_whatsapp(doc, method=None) -> None:
    """``WhatsApp Message.after_insert`` (frappe_whatsapp): an inbound WhatsApp reply."""
    if doc.get("type") != "Incoming":
        return
    phone = normalize_phone(doc.get("from"))
    if not phone:
        return
    member = frappe.db.get_value("Sales Campaign Member", {"phone": ["in", [phone, phone.lstrip("+")]],
                                                           "status": "Active"}, "name", order_by="modified desc")
    if not member:
        return
    message = frappe.db.get_value("Sales Outreach Message", {"member": member, "channel": "WhatsApp"},
                                  "name", order_by="creation desc")
    if message:
        receive_reply(message, doc.get("message") or "", f"whatsapp:{doc.name}", "WhatsApp")


def receive_reply(message_name: str, text: str, source_key: str, channel: str) -> None:
    """Apply the safe rule-based actions now; AI classification and CRM follow-up run in the background."""
    from reckon_sales_agent.campaigns.replies import actions_for, classify_rules

    message = frappe.get_doc("Sales Outreach Message", message_name)
    member = frappe.get_doc("Sales Campaign Member", message.member)
    rule_class = classify_rules(text)
    action = actions_for(rule_class)
    if action["stop"]:
        member.db_set({"status": "Stopped", "stop_reason": "replied", "last_event": "replied",
                       "reply_classification": rule_class, "next_action_on": None})
        _cancel_pending(member.name, "Recipient replied.")
    else:
        member.db_set({"reply_classification": rule_class, "last_event": rule_class,
                       "next_action_on": add_days(nowdate(), action.get("reschedule_days") or 5)})
    if action["suppress"]:
        _suppress_member(message.company, member, channel, f"reply {source_key}")
    frappe.enqueue(
        "reckon_sales_agent.campaigns.engine.classify_and_follow_up",
        queue="short",
        enqueue_after_commit=True,
        message_name=message.name,
        text=text[:4000],
        source_key=source_key,
        rule_class=rule_class,
    )


def classify_and_follow_up(message_name: str, text: str, source_key: str, rule_class: str) -> None:
    """Background: refine the class with AI, record it, and hand positive replies to a person."""
    from reckon_sales_agent.campaigns import replies
    from reckon_sales_agent.providers.channels import ChannelUnavailable, create_task

    message = frappe.get_doc("Sales Outreach Message", message_name)
    member = frappe.get_doc("Sales Campaign Member", message.member)
    settings = get_settings(message.company)
    summary, next_step, ai_class = "", "", None
    llm = get_llm(message.company) if settings.classify_replies_with_ai else None
    if llm and remaining(message.company, USAGE_AI) > 0:
        try:
            reserve(message.company, USAGE_AI, 1, message)
            frappe.db.commit()
            data = llm.complete_json(
                "You classify replies to B2B sales outreach for a sales team in Bangladesh. "
                f"{UNTRUSTED_RULES} Summarise the reply in one sentence and suggest the next step "
                "for the salesperson. Replies may be in English or Bangla.",
                untrusted("reply", replies.strip_quoted(text)),
                replies.SCHEMA,
                max_tokens=2000,
            )
            ai_class = data.get("classification")
            summary = " ".join(str(data.get("summary") or "").split())[:500]
            next_step = " ".join(str(data.get("suggested_next_step") or "").split())[:300]
        except (LLMError, QuotaExceeded):
            pass
    final = replies.resolve(rule_class, ai_class)
    action = replies.actions_for(final)
    member.db_set("reply_classification", final)
    if action["suppress"]:
        _suppress_member(message.company, member, message.get("channel") or "Email", f"reply {source_key}")
    if action["stop"] and member.status == "Active":
        member.db_set({"status": "Stopped", "stop_reason": "replied", "next_action_on": None})
        _cancel_pending(member.name, "Recipient replied.")
    record_event(message, action["event"], f"{action['event']}:{source_key}", detail=summary or final)
    _note_on_lead(message, final, summary or replies.strip_quoted(text)[:500])
    if action["task"] and settings.create_crm_tasks:
        priority, days = action["task"]
        try:
            task = create_task(
                message.prospect,
                f"{final.replace('_', ' ').title()} reply: {frappe.db.get_value('Sales Prospect', message.prospect, 'business_name')}",
                f"{summary}\n\nSuggested next step: {next_step or 'follow up personally'}",
                frappe._dict({**settings.as_dict(), "task_due_days": days}),
                priority=priority,
            )
            record_event(message, "task_created", f"task:{source_key}", provider_message_id=task.provider_message_id)
        except ChannelUnavailable:
            pass
    if final in replies.POSITIVE:
        from reckon_sales_agent.qualification.service import qualify_prospect

        qualify_prospect(message.prospect)  # engagement raises the deal probability
    _refresh_metrics(message.campaign)
    log_activity(message.company, f"reply_{final}", member, summary, "agent" if ai_class else "provider")
    frappe.db.commit()


def _suppress_member(company: str, member, channel: str, source: str) -> None:
    if member.email:
        suppress(company, "Email", member.email, "Unsubscribed", source)
    if member.phone and channel in ("SMS", "WhatsApp"):
        suppress(company, "Phone", member.phone, "Unsubscribed", source)


def _note_on_lead(message, classification: str, text: str) -> None:
    """Put the reply on the CRM lead's timeline so salespeople see it in /crm."""
    lead = frappe.db.get_value("Sales Prospect", message.prospect, "crm_lead")
    if not lead:
        return
    frappe.get_doc({
        "doctype": "FCRM Note",
        "title": f"{message.get('channel') or 'Email'} reply ({classification.replace('_', ' ')})",
        "content": f"<p>{frappe.utils.escape_html(text)}</p>",
        "reference_doctype": "CRM Lead",
        "reference_docname": lead,
    }).insert(ignore_permissions=True)


def unsubscribe_member(token: str) -> bool:
    member_name = frappe.db.get_value("Sales Campaign Member", {"unsubscribe_token": token})
    if not member_name:
        return False
    member = frappe.get_doc("Sales Campaign Member", member_name)
    if member.email:
        suppress(member.company, "Email", member.email, "Unsubscribed", "unsubscribe link")
    if member.phone:
        suppress(member.company, "Phone", member.phone, "Unsubscribed", "unsubscribe link")
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
    probability = frappe.db.get_value("Sales Prospect", {"crm_lead": doc.lead}, "deal_probability")
    if probability and not doc.get("probability"):
        frappe.db.set_value("CRM Deal", doc.name, "probability", probability, update_modified=False)


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
        "reply_count": count_events("replied") + count_events("positive_reply") + count_events("meeting_requested"),
        "positive_reply_count": count_events("positive_reply") + count_events("meeting_requested"),
        "meeting_count": count_events("meeting_requested"),
        "unsubscribe_count": count_events("unsubscribed"),
        "bounce_count": count_events("bounced"),
        "converted_count": count_members(status="Converted"),
        "task_count": count_events("task_created"),
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
