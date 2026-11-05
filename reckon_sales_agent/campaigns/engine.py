"""Campaign audience, drafting, approval, sending and stop conditions.

Outbound safety, in order, immediately before every send:
kill switch -> outbound enabled -> subscription -> campaign/member state ->
suppression and do-not-contact -> approval -> daily limits -> monthly quota.
While outbound sending is off, approved messages are logged as dry runs.
"""

from __future__ import annotations

import json
from html import escape as html_escape

import frappe
from frappe import _
from frappe.utils import (
    add_days,
    add_to_date,
    get_datetime,
    get_url,
    getdate,
    now_datetime,
    nowdate,
)

from reckon_sales_agent.campaigns import variants
from reckon_sales_agent.campaigns.suppression import is_suppressed, suppress
from reckon_sales_agent.campaigns.templates import (
    footer,
    is_builder_html,
    render,
    resolve_dynamic,
    text_to_html,
)
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
    # Approval is the decision (a person, or the autopilot within its rules): an approved lead the score left in
    # "Needs Review" joins too. Live test: approved borderline leads could never enter a campaign.
    filters = {
        "company": campaign.company,
        "review_status": "Approved",
        "fit_score": [">=", campaign.minimum_fit_score or 0],
    }
    if campaign.discovery_campaign:
        filters["discovery_campaign"] = campaign.discovery_campaign
    added = 0
    settings = get_settings(campaign.company)
    from reckon_sales_agent.agents.analytics import in_holdout

    pilot = bool(campaign.get("pilot_mode"))
    limit = (campaign.get("pilot_max_members") or 100) if pilot else None
    treated = frappe.db.count("Sales Campaign Member", {"campaign": campaign.name,
                                                        "status": ["not in", ["Holdout", "Ineligible", "Eligible"]]})
    # A person approved a larger pilot (or the full launch): members waiting on the pilot limit now start.
    for waiting in frappe.get_all("Sales Campaign Member", filters={"campaign": campaign.name, "status": "Eligible",
                                                                    "eligibility_reason": ["like", "Pilot audience limit%"]},
                                  pluck="name", order_by="creation asc", limit=5000):
        if limit is not None and treated >= limit:
            break
        frappe.db.set_value("Sales Campaign Member", waiting, {"status": "Active", "next_action_on": nowdate(),
                                                                "eligibility_reason": "Started after the pilot was scaled."})
        treated += 1
    for name, source in _candidates(campaign, filters):
        key = f"{campaign.name}:{name}"
        if frappe.db.exists("Sales Campaign Member", {"idempotency_key": key}):
            continue
        prospect = frappe.get_doc("Sales Prospect", name)
        ok, reason = eligibility(prospect, campaign, settings)
        status = "Active" if ok else "Ineligible"
        if ok and pilot:
            if in_holdout(key, campaign.get("holdout_percent") or 20):
                status, reason = "Holdout", "Pilot hold-out: not contacted, used to measure the campaign's effect."
            elif treated >= (campaign.get("pilot_max_members") or 100):
                status, reason = "Eligible", "Pilot audience limit reached; waits until the pilot is scaled."
            else:
                treated += 1
        frappe.get_doc({
            "doctype": "Sales Campaign Member",
            "company": campaign.company,
            "campaign": campaign.name,
            "prospect": name,
            "crm_lead": prospect.crm_lead,
            "audience": campaign.get("audience") or None,
            "source_doctype": source.get("ref_doctype") or None,
            "source_name": source.get("ref_name") or None,
            "email": prospect.email if ok else None,
            "phone": prospect.phone if ok else None,
            "status": status,
            "eligibility_reason": reason,
            "next_action_on": campaign.start_date or nowdate(),
            "idempotency_key": key,
            "unsubscribe_token": frappe.generate_hash(length=32),
        }).insert(ignore_permissions=True)
        added += 1
    _refresh_metrics(campaign.name)
    from reckon_sales_agent.agents.policy import audience_grew_materially

    total = frappe.db.count("Sales Campaign Member", {"campaign": campaign.name})
    if campaign.get("approved_audience_size") and audience_grew_materially(campaign.approved_audience_size, total):
        _require_reapproval(campaign, f"The audience grew from {campaign.approved_audience_size} to {total} "
                                      "members after approval.")
    return added



def _candidates(campaign, filters) -> list[tuple[str, dict]]:
    """(prospect, where they came from). An audience wins over the discovery campaign and the fit score."""
    if campaign.get("audience"):
        from reckon_sales_agent.campaigns.audience_resolve import materialize

        audience = frappe.get_doc("Sales Audience", campaign.audience)
        if audience.company != campaign.company:
            frappe.throw(_("That audience belongs to another Company."), frappe.PermissionError)
        return materialize(audience)
    return [(name, {}) for name in frappe.get_all("Sales Prospect", filters=filters, pluck="name", limit=5000)]


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
    contact = " ".join((prospect.get("contact_name") or "").split())
    owner = prospect.get("sales_owner")
    values = {
        "business_name": prospect.business_name,
        "city": prospect.city,
        "industry": prospect.industry,
        "website": prospect.get("domain") or prospect.get("website") or "",
        "contact_name": contact,
        "first_name": contact.split(" ")[0] if contact else "",
        "owner_name": (frappe.db.get_value("User", owner, "full_name") if owner else "") or "",
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
    if channel in TASK_CHANNELS:
        # A script a salesperson reads aloud: they say their own name, and with no website research the AI
        # triage's reading of the listing is the talking point (internal, never sent). Live test: the scripts
        # said "this is Reckon Technologies Ltd. from Reckon Technologies" with an empty talking point.
        caller = settings.get("task_assignee")
        values["sender_name"] = (frappe.db.get_value("User", caller, "first_name") if caller else None) or "[your name]"
        if not values["personal_line"]:
            values["personal_line"] = prospect.get("ai_triage_reason") or "No research yet: ask how they work today."
    _ok, _reason, recipient = reachability(channel, prospect, settings)
    # A/B test: each person gets one of the template's subject lines, the same one every time it is asked.
    letter, chosen_subject = variants.choose(key, step.subject_template or "", step.get("subject_variants"))
    subject = render(chosen_subject, values, escape=False)[:140]
    unsubscribe_url = get_url(f"/api/method/reckon_sales_agent.api.unsubscribe?token={member.unsubscribe_token}")
    if channel == "Email":
        # Dynamic blocks pick their content for this person first, then the fields are filled.
        rendered = render(resolve_dynamic(step.body_template, values), values)
        body = rendered if is_builder_html(rendered) else text_to_html(rendered)  # builder email is already HTML
        body += footer(values["sender_name"], settings.physical_address, unsubscribe_url)
    elif channel in ("SMS", "WhatsApp"):
        text = render(step.body_template, values, escape=False).strip()
        body = text_to_html(html_escape(f"{text}\n\n{values['sender_name']} · Opt out: {unsubscribe_url}"))
    else:  # internal CRM task for a person: call, LinkedIn, visit
        body = text_to_html(render(step.body_template, values))
    # Internal tasks contact nobody, so they need no approval; outreach does.
    approval = settings.human_approval_required and channel not in TASK_CHANNELS
    from reckon_sales_agent.campaigns import autopilot

    auto, auto_reason = autopilot.may_auto_approve(
        autopilot.normalize_level(settings.get("campaign_autopilot")), campaign_active=campaign.status == "Active",
        campaign_approved=bool(campaign.get("approved_by")), content_passed=campaign.get("content_status") == "Passed",
        channel=channel)
    auto = bool(approval and auto)  # only matters where a person would otherwise have to approve
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
        "variant": letter or None,
        "body": body,
        "ai_generated": ai_generated,
        "whatsapp_template": step.get("whatsapp_template") if channel == "WhatsApp" else None,
        "whatsapp_params": json.dumps([str(values.get(p.strip()) or "") for p in
                                       (step.get("whatsapp_template_params") or "").split(",") if p.strip()])
        if channel == "WhatsApp" and step.get("whatsapp_template") else None,
        "status": "Draft" if (approval and not auto) else "Approved",
        "auto_approved_by_policy": 1 if auto else 0,
        "idempotency_key": key,
    }).insert(ignore_permissions=True)
    record_event(message, "drafted", f"draft:{message.name}")
    if auto:
        record_event(message, "auto_approved", f"auto:{message.name}", detail=auto_reason)
        log_activity(campaign.company, "message_auto_approved", message, auto_reason, actor_type="agent",
                     agent="Engagement", policy_outcome="automatic (autopilot: approved campaign)")
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
    from reckon_sales_agent.agents.approvals import fingerprint, message_payload

    if message.status != "Draft":
        frappe.throw(_("Only drafts can be approved."))
    message.db_set({"status": "Approved", "approved_by": frappe.session.user,
                    "approval_fingerprint": fingerprint(message_payload(message))})
    record_event(message, "approved", f"approved:{message.name}")


HOUR_FULL = 3600.0  # what pace_wait returns while an hour's limit is reached (the caller does not sleep that long)


def pace_wait(message, settings) -> float:
    """Seconds this message must still wait for its channel's pace; 0 when it may go now.

    Only real sends count (dry runs and internal tasks do not reach a mailbox). The gap is measured from the last
    real send on the same channel, and an hour's limit counts the sends of the last 60 minutes.
    """
    from reckon_sales_agent.campaigns import pacing

    channel = message.get("channel") or "Email"
    if channel not in pacing.PACED_CHANNELS:
        return 0.0
    pace = pacing.config(settings)
    filters = {"company": message.company, "channel": channel, "status": "Sent"}
    if pace["hourly"]:
        last_hour = frappe.db.count("Sales Outreach Message", {**filters, "sent_on": [">=", add_to_date(now_datetime(), hours=-1)]})
        if pacing.hourly_reached(last_hour, pace["hourly"]):
            return HOUR_FULL
    if not pace["gap"]:
        return 0.0
    last = frappe.db.get_value("Sales Outreach Message", filters, "sent_on", order_by="sent_on desc")
    since = (now_datetime() - get_datetime(last)).total_seconds() if last else None
    return pacing.wait_seconds(since, pacing.message_gap(pace["gap"], pace["jitter"], message.name))


def run_paced_send() -> None:
    """Every ten minutes: one background job per Company with approved messages, each sending at its own pace, so one
    Company's gaps never hold up another's."""
    for company in frappe.get_all("Sales Outreach Message", filters={"status": "Approved"}, pluck="company", distinct=True):
        frappe.enqueue("reckon_sales_agent.campaigns.engine.send_due_messages", queue="long", timeout=900,
                       job_id=f"reckon_sales_agent_paced_send_{company}", deduplicate=True, company=company, pace=True,
                       budget=540)


def send_due_messages(company: str | None = None, pace: bool = False, budget: int = 0) -> int:
    """Send what is approved. With ``pace`` the job waits out each message's gap (up to ``budget`` seconds in all), so
    a long list goes out one message at a time instead of in a burst; without it a message still too soon waits."""
    import time

    filters = {"status": "Approved"}
    if company:
        filters["company"] = company
    sent = 0
    deadline = time.monotonic() + budget
    for name in frappe.get_all("Sales Outreach Message", filters=filters, pluck="name",
                               order_by="creation asc", limit=500):
        try:
            message = frappe.get_doc("Sales Outreach Message", name)
            if pace and budget and not message.get("is_reply"):
                wait = pace_wait(message, get_settings(message.company))
                if 0 < wait < HOUR_FULL:
                    if time.monotonic() + wait >= deadline:
                        continue  # no time left this run: later messages (other channels) may still be ready
                    time.sleep(wait)
                    frappe.db.rollback()  # end the open transaction so the next read sees other workers' sends
                    message = frappe.get_doc("Sales Outreach Message", name)
                    if message.status != "Approved":
                        continue  # cancelled or sent by someone else while it waited
            if send_message(message):
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
    is_reply = bool(message.get("is_reply"))  # answering someone who wrote to us, not a sequence step
    if not is_reply and (campaign.status != "Active" or member.status != "Active"):
        return _cancel(message, "Campaign or member is no longer active.")
    if not is_reply and campaign.end_date and getdate(campaign.end_date) < getdate(nowdate()):
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
    from reckon_sales_agent.agents.approvals import (
        approval_current,
        campaign_payload,
        message_payload,
    )
    from reckon_sales_agent.agents.policy import ALLOW, NEEDS_APPROVAL, decide

    if channel == "WhatsApp" and not message.get("whatsapp_template"):
        from reckon_sales_agent.agents.engagement import within_service_window

        if not within_service_window(prospect.get("whatsapp_last_inbound"), now_datetime()):
            # WhatsApp only allows free-form business messages within 24 hours of the customer's last message.
            _cancel(message, "Outside the 24-hour WhatsApp window: give this step an approved WhatsApp template.")
            if not is_reply:
                _advance(campaign, member)
            return False
    if campaign.approval_fingerprint and not approval_current(campaign.approval_fingerprint, campaign_payload(campaign)):
        _require_reapproval(campaign, "The campaign changed after approval.")
        return False
    message_current = approval_current(message.get("approval_fingerprint"), message_payload(message))
    decision = decide("send_approved_message", {
        "approved": bool(message.approved_by) or bool(message.get("auto_approved_by_policy"))
        or not settings.human_approval_required,
        "approval_current": message_current,
    })
    if decision.outcome == NEEDS_APPROVAL and message.approved_by and not message_current:
        # Changed after approval: back to draft for a person to look at again.
        message.db_set({"status": "Draft", "approved_by": None, "approval_fingerprint": None})
        record_event(message, "approval_invalidated", f"invalidated:{message.name}:{now_datetime()}",
                     detail=decision.reason)
        return False
    if decision.outcome != ALLOW:
        return False
    try:
        assert_entitled(message.company)
    except NotEntitled:
        return False
    if not is_reply:
        from reckon_sales_agent.campaigns.autopilot import in_window

        now = now_datetime()
        minutes = now.hour * 60 + now.minute
        step_window = next((s.get("send_window") for s in campaign.steps if s.step_no == message.get("step_no")), "")
        if not in_window(settings.get("campaign_send_window"), minutes) or not in_window(step_window, minutes):
            return False  # outside the sending hours (the Company's, or this step's): it waits, approved, until they open
    if _sent_today(message.company) >= (settings.daily_message_limit or 0):
        return False
    if _sent_today(message.company, campaign.name) >= (campaign.daily_limit or 0):
        return False
    from reckon_sales_agent.agents.deliverability import allowed, today_email_limit

    if settings.get("allowlist_only") and not allowed(message.recipient, channel, settings.get("outbound_allowlist")):
        return False  # safe mode: it waits, approved, until the recipient is listed or safe mode is off
    if settings.outbound_enabled and channel == "Email" and _real_emails_today(message.company) >= today_email_limit(settings):
        return False  # warming up the sending domain: the rest goes out on the following days

    if not settings.outbound_enabled:
        message.db_set({"status": "Dry Run", "sent_on": now_datetime()})
        record_event(message, "dry_run", f"dry_run:{message.name}")
        _advance(campaign, member)
        return True

    if not is_reply and pace_wait(message, settings) > 0:
        return False  # too soon after the last one, or the hour is full: it waits, approved, for the next run

    reserve(message.company, USAGE_MESSAGE, 1, message)
    stored_body = message.body
    try:
        _instrument(message, settings)
        result = send(channel, message, settings)
    except ChannelUnavailable as exc:
        message.db_set({"status": "Failed", "error": str(exc)[:500]})
        record_event(message, "failed", f"failed:{message.name}", detail=str(exc))
        return False
    finally:
        message.body = stored_body  # tracking changes only the copy that goes out, never what was approved
    message.db_set({"status": "Sent", "sent_on": now_datetime()})
    record_event(message, "sent", f"sent:{message.name}", provider_message_id=result.provider_message_id)
    if channel == "Email" and not settings.get("first_send_on"):
        frappe.db.set_value("Sales Agent Settings", message.company, "first_send_on", nowdate())  # warm-up starts
    _advance(campaign, member)
    return True


def _instrument(message, settings) -> None:
    """Track opens and clicks on the outgoing copy. A failure here must never stop the message."""
    try:
        from reckon_sales_agent.campaigns.track_links import instrument

        instrument(message, settings)
    except Exception:
        frappe.log_error(title="Sales Agent link tracking failed", reference_doctype="Sales Outreach Message",
                         reference_name=message.name)


def _advance(campaign, member) -> None:
    if member.status != "Active":
        return  # answers to replies do not move a stopped sequence
    steps = sorted(campaign.steps, key=lambda s: s.step_no)
    position = (member.sequence_position or 0) + 1
    if position >= len(steps):
        member.db_set({"sequence_position": position, "status": "Completed", "next_action_on": None,
                       "stop_reason": "sequence finished", "last_event": "sent"})
    else:
        member.db_set({"sequence_position": position, "last_event": "sent",
                       "next_action_on": add_days(nowdate(), steps[position].delay_days or 0)})
    _refresh_metrics(campaign.name)


def _require_reapproval(campaign, reason: str) -> None:
    """Stop a campaign from sending until a person approves it again."""
    campaign.db_set({"status": "Pending Approval", "approved_by": None, "approved_on": None,
                     "approval_fingerprint": None})
    log_activity(campaign.company, "campaign_needs_approval", campaign, reason, actor_type="system",
                 agent="Governance", policy_outcome="needs_approval")


def _cancel(message, reason: str) -> bool:
    message.db_set({"status": "Cancelled", "error": reason})
    record_event(message, "stopped", f"stopped:{message.name}", detail=reason)
    return False


def _real_emails_today(company: str) -> int:
    """Emails actually sent today (dry runs do not affect the domain's reputation)."""
    sent = frappe.get_all("Sales Communication Event", filters={"company": company, "event_type": "sent",
                                                                "event_time": [">=", f"{nowdate()} 00:00:00"]},
                          pluck="message", limit=100000)
    return frappe.db.count("Sales Outreach Message", {"name": ["in", sent], "channel": "Email"}) if sent else 0


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
    """``Communication.after_insert``: an email to or from a lead. Replies to outreach are recorded as sequence replies;
    any other email from the Company's sending account goes onto the lead's Conversations thread."""
    if doc.reference_doctype != "Sales Outreach Message":
        from reckon_sales_agent.agents.email_threads import file_email

        return file_email(doc)
    if doc.sent_or_received != "Received":
        return
    import hashlib

    from reckon_sales_agent.providers.channels import html_to_text

    # The email's own Message-ID, so a redelivered email (a new Communication) is still recognised.
    key = (doc.get("message_id") or "").strip().strip("<>") or doc.name
    if len(key) > 100:
        key = hashlib.sha256(key.encode()).hexdigest()[:40]
    receive_reply(doc.reference_name, html_to_text(doc.content or ""), f"email:{key}", "Email")


def handle_whatsapp(doc, method=None) -> None:
    """``WhatsApp Message.after_insert`` (frappe_whatsapp): an inbound WhatsApp message on a Company's account.

    The account decides the Company (Sales Agent Settings → WhatsApp account), so a message is never filed under
    another tenant. A reply to a running sequence answers that sequence; anything else opens or continues the
    lead's conversation in Conversations, like a Messenger or website chat message.
    """
    if doc.get("type") != "Incoming":
        return
    company = _account_company(doc.get("whatsapp_account"))
    phone = normalize_phone(doc.get("from"))
    if not company or not phone:
        return
    from reckon_sales_agent.agents.engagement_agent import record_whatsapp_inbound

    record_whatsapp_inbound(phone, company)
    member = frappe.db.get_value("Sales Campaign Member", {"company": company, "phone": ["in", [phone, phone.lstrip("+")]],
                                                           "status": "Active"}, "name", order_by="modified desc")
    message = frappe.db.get_value("Sales Outreach Message", {"member": member, "channel": "WhatsApp"}, "name",
                                  order_by="creation desc") if member else None
    if message:
        receive_reply(message, doc.get("message") or "", f"whatsapp:{doc.name}", "WhatsApp")
        return
    _whatsapp_conversation(company, phone, doc)


def handle_whatsapp_status(doc, method=None) -> None:
    """``WhatsApp Message.on_update``: Meta's delivered / read / failed receipts for a campaign message we sent."""
    if doc.get("type") != "Outgoing" or doc.get("reference_doctype") != "Sales Outreach Message":
        return
    kind = {"delivered": "delivered", "read": "read", "failed": "failed"}.get(str(doc.get("status") or "").lower())
    if not kind or not doc.get("reference_name") or not frappe.db.exists("Sales Outreach Message", doc.reference_name):
        return
    message = frappe.get_doc("Sales Outreach Message", doc.reference_name)
    record_event(message, kind, f"wa:{doc.name}:{kind}", provider_message_id=doc.get("message_id"))
    _refresh_metrics(message.campaign)


def _account_company(account: str | None) -> str | None:
    """The Company that uses this WhatsApp account (one Company per account)."""
    if not account:
        return None
    return frappe.db.get_value("Sales Agent Settings", {"whatsapp_account": account}, "name")


def _whatsapp_conversation(company: str, phone: str, doc) -> None:
    """A WhatsApp message outside any sequence: it joins the lead's conversation like a chat message."""
    from reckon_sales_agent.agents.chat import receive_chat
    from reckon_sales_agent.agents.engagement_agent import record_whatsapp_inbound

    text = (doc.get("message") or "").strip()
    if doc.get("attach"):
        text = f"{text}\n[attachment: {doc.attach}]".strip()
    name = receive_chat(company, "WhatsApp", doc.get("whatsapp_account") or "whatsapp", phone, text or "[message]",
                        f"wa:{doc.get('message_id') or doc.name}"[:140], at=doc.get("creation"),
                        contact_name=doc.get("profile_name") or None, phone=phone)
    prospect = frappe.db.get_value("Sales Chat Message", name, "prospect") if name else None
    if not prospect:
        return
    # They wrote first: that is consent to answer on WhatsApp, and it opens the 24-hour window.
    frappe.db.set_value("Sales Prospect", prospect, "whatsapp_consent", 1, update_modified=False)
    if not frappe.db.get_value("Sales Prospect", prospect, "consent_source"):
        frappe.db.set_value("Sales Prospect", prospect, "consent_source", "Wrote to us on WhatsApp", update_modified=False)
    record_whatsapp_inbound(phone, company)
    frappe.enqueue("reckon_sales_agent.agents.chat.auto_draft", queue="short", prospect=prospect,
                   job_id=f"chat-draft:{prospect}", deduplicate=True, enqueue_after_commit=True)


def receive_reply(message_name: str, text: str, source_key: str, channel: str) -> None:
    """Apply the safe rule-based actions now; AI classification and CRM follow-up run in the background."""
    from reckon_sales_agent.campaigns.replies import actions_for, classify_rules

    message = frappe.get_doc("Sales Outreach Message", message_name)
    if frappe.db.exists("Sales Communication Event", {"idempotency_key": f"received:{source_key}"}):
        return  # the same inbound message delivered twice: handled already
    record_event(message, "received", f"received:{source_key}")
    from reckon_sales_agent.agents.conversations import touch_inbound

    touch_inbound(message.company, message.prospect, channel)
    from reckon_sales_agent.agents.inbox_events import notify_inbox
    notify_inbox(message.company, message.prospect)
    member = frappe.get_doc("Sales Campaign Member", message.member)
    rule_class = classify_rules(text)
    action = actions_for(rule_class)
    if action["stop"]:
        member.db_set({"status": "Stopped", "stop_reason": "replied", "last_event": "replied",
                       "reply_classification": rule_class, "next_action_on": None})
        _cancel_pending(member.name, "Recipient replied.")
    elif action.get("reschedule_days"):
        member.db_set({"reply_classification": rule_class, "last_event": rule_class,
                       "next_action_on": add_days(nowdate(), action["reschedule_days"])})
    else:
        member.db_set({"reply_classification": rule_class, "last_event": rule_class})
    if action["suppress"]:
        _suppress_member(message.company, member, channel, f"reply {source_key}",
                         "Complaint" if rule_class == "complaint" else "Unsubscribed")
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
        _suppress_member(message.company, member, message.get("channel") or "Email", f"reply {source_key}",
                         "Complaint" if final == "complaint" else "Unsubscribed")
    if action["stop"] and member.status == "Active":
        member.db_set({"status": "Stopped", "stop_reason": "replied", "next_action_on": None})
        _cancel_pending(member.name, "Recipient replied.")
    record_event(message, action["event"], f"{action['event']}:{source_key}", detail=summary or final)
    _note_on_lead(message, final, summary or replies.strip_quoted(text)[:500])
    task_title = f"{final.replace('_', ' ').title()} reply"
    if final == "question":
        from reckon_sales_agent.agents.engagement import DRAFT, ESCALATE, SEND
        from reckon_sales_agent.agents.engagement_agent import answer_question

        route, why = answer_question(message, text, source_key)
        task_title = {SEND: "Question answered automatically", DRAFT: "Review the suggested answer",
                      ESCALATE: "Question needs your answer"}[route]
        next_step = f"{why} {next_step}".strip()
        if route == SEND:
            action = {**action, "task": ("Medium", 1)}
    elif final == "complaint":
        task_title = "Complaint: handle personally"
        log_activity(message.company, "reply_complaint", member, summary or "complaint", actor_type="agent",
                     agent="Engagement", policy_outcome="needs a person (handle_complaint)")
    if action["task"] and settings.create_crm_tasks:
        priority, days = action["task"]
        try:
            task = create_task(
                message.prospect,
                f"{task_title}: {frappe.db.get_value('Sales Prospect', message.prospect, 'business_name')}",
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
    if final in ("interested", "meeting_request"):
        from reckon_sales_agent.agents.meetings import start_meeting

        start_meeting(message.prospect, f"replied: {final.replace('_', ' ')}")  # slots, invitation drafted
    _refresh_metrics(message.campaign)
    log_activity(message.company, f"reply_{final}", member, summary, "agent" if ai_class else "provider")
    frappe.db.commit()


def _suppress_member(company: str, member, channel: str, source: str, reason: str = "Unsubscribed") -> None:
    if member.email:
        suppress(company, "Email", member.email, reason, source)
    if member.phone and channel in ("SMS", "WhatsApp"):
        suppress(company, "Phone", member.phone, reason, source)


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
    for name in frappe.get_all("Sales Campaign Member", filters={"crm_lead": doc.lead, "converted_on": ["is", "not set"],
                                                                  "status": ["in", ["Active", "Completed", "Stopped",
                                                                                    "Holdout", "Eligible"]]},
                               pluck="name"):
        member = frappe.get_doc("Sales Campaign Member", name)
        if member.status in ("Holdout", "Eligible"):
            # Not contacted: the conversion still counts for measuring the pilot.
            member.db_set({"converted_on": now_datetime(), "last_event": "converted"})
        else:
            member.db_set({"status": "Converted", "converted_on": now_datetime(), "last_event": "converted",
                           "next_action_on": None})
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

    def count_unique(event_type):  # people reached, not repeat visits
        return frappe.db.sql("select count(distinct message) from `tabSales Communication Event` "
                             "where campaign = %s and event_type = %s", (campaign_name, event_type))[0][0]

    frappe.db.set_value("Sales Campaign", campaign_name, {
        "member_count": count_members(),
        "sent_count": count_events("sent") + count_events("dry_run"),
        "reply_count": count_events("replied") + count_events("positive_reply") + count_events("meeting_requested"),
        "positive_reply_count": count_events("positive_reply") + count_events("meeting_requested"),
        "meeting_count": count_events("meeting_requested"),
        "unsubscribe_count": count_events("unsubscribed"),
        "bounce_count": count_events("bounced"),
        "open_count": count_unique("opened"),
        "click_count": count_unique("clicked"),
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
