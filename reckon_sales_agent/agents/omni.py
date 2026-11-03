"""Omni-channel conversations agent: one thread per lead across email, WhatsApp, Messenger, Instagram, website
chat, calls and forms, and an AI reply on the right channel, waiting for a person's approval.

- ``threads`` lists the Company's conversations, newest first, flagging those where the lead spoke last.
- ``timeline`` gives one lead's whole history: messages sent, replies received, call outcomes, meetings.
- ``draft_reply`` picks the channel (the chat they last wrote on, WhatsApp inside the 24-hour window with
  consent, else email, else a call)
  and has Claude write from the history and the approved knowledge only; the content check runs on it and it
  is saved as a Draft for approval, like every outbound message.

One-off replies that belong to no sequence go through the Company's "Conversations" campaign, which stays
paused (the sequence engine never drafts from it) but keeps approval, limits and the audit trail.

Fast answers (opt-in per Company): on a chat channel, a reply goes out without waiting for a person only when the
policy matrix allows a routine answer: the AI says every fact came from the approved knowledge and nothing needs a
person, the content check finds nothing, and what the lead wrote is not a complaint or an opt-out. Anything else
stays a draft for approval.
``choose_channel``, ``needs_reply`` and ``auto_answer_decision`` are pure.
"""

from __future__ import annotations

from datetime import datetime, timedelta

CONVERSATIONS = "Conversations"
WINDOW = timedelta(hours=24)
COMMENT_WINDOW = timedelta(days=7)  # Meta: one private reply to a comment, within 7 days
CHAT_CHANNELS = ("Messenger", "Instagram", "Web Chat")
# Only something the lead wrote asks for a written reply; call outcomes have their own next steps (a meeting,
# a callback, or stopping), so a "not interested" call never triggers an AI message.
INBOUND = ("received",)
OUTBOUND = ("sent", "dry_run")

REPLY_SCHEMA = {
    "type": "object",
    "properties": {"subject": {"type": "string"}, "body": {"type": "string"}, "why": {"type": "string"},
                   "grounded": {"type": "boolean"}, "needs_person": {"type": "boolean"}},
    "required": ["subject", "body", "why", "grounded", "needs_person"],
    "additionalProperties": False,
}
REPLY_SYSTEM = (
    "You write the next message from a B2B seller in Bangladesh to one lead, continuing the conversation shown. "
    "Answer what they asked or said, using ONLY facts in the approved knowledge; never invent prices, discounts, "
    "clients or numbers. If they asked for something the knowledge does not cover, say a colleague will confirm. "
    "Propose one simple next step (a call or a short demo). Match their language (English or Bangla). Email: "
    "subject under 60 characters, body under 120 words. WhatsApp, Messenger, Instagram and website chat: under 60 "
    "words, conversational, no subject (use empty). "
    "why: one sentence for the salesperson on why this reply. Do not add an unsubscribe line; it is added. "
    "grounded: true only if every fact, figure and offer in your reply is in the approved knowledge. "
    "needs_person: true if they ask for a discount, a custom price, credit terms, a contract, complain, raise a legal "
    "or delivery problem, or ask anything the knowledge does not answer. If they commented on a post, this is a "
    "private message answering that comment: thank them and answer it."
)


def choose_channel(prospect: dict, last_whatsapp_inbound: datetime | None, now: datetime,
                   last_chat: dict | None = None) -> tuple[str | None, str]:
    if last_chat and last_chat.get("channel") == "SMS" and prospect.get("sms_consent") and prospect.get("phone") and (
            not last_whatsapp_inbound or not last_chat.get("at") or last_chat["at"] >= last_whatsapp_inbound):
        return "SMS", "They texted us; answer by SMS."
    return _choose(prospect, last_whatsapp_inbound, now, last_chat)


def _choose(prospect: dict, last_whatsapp_inbound: datetime | None, now: datetime,
            last_chat: dict | None = None) -> tuple[str | None, str]:
    """(channel, reason) for the next written reply, or (None, reason) when only a call is possible.

    ``last_chat`` is the lead's latest Messenger / Instagram / website chat message ({channel, at}): answer where
    they wrote, while the platform allows it (Meta: 24 hours; the website chat keeps the thread).
    """
    window = COMMENT_WINDOW if last_chat and last_chat.get("kind") == "Comment" else WINDOW
    if last_chat and last_chat.get("at") and last_chat["channel"] in CHAT_CHANNELS and (
            last_chat["channel"] == "Web Chat" or now - last_chat["at"] < window) and (
            not last_whatsapp_inbound or last_chat["at"] >= last_whatsapp_inbound):
        return last_chat["channel"], f"They wrote on {last_chat['channel']}; answer there."
    if (prospect.get("whatsapp_consent") and prospect.get("phone") and last_whatsapp_inbound
            and now - last_whatsapp_inbound < WINDOW):
        return "WhatsApp", "They wrote on WhatsApp in the last 24 hours."
    if prospect.get("email"):
        return "Email", "Email is the channel they can be written to."
    if prospect.get("phone"):
        return None, "Only a phone number: a salesperson should call."
    return None, "No way to reach this lead yet."


def auto_answer_decision(enabled: bool, channel: str, data: dict, issues: list[str], inbound_class: str,
                         suppressed: bool = False, kill_switch: bool = False, channels=CHAT_CHANNELS):
    """The policy decision for sending a reply without a person's approval (a ``policy.Decision``)."""
    from reckon_sales_agent.agents.policy import NEEDS_APPROVAL, Decision, decide

    if not enabled or channel not in channels:
        return decide("answer_routine_question", {"channel_allows": False})
    if inbound_class in ("complaint", "unsubscribe"):
        return decide("handle_complaint")
    if data.get("needs_person"):
        return decide("change_commercial_terms")
    if not data.get("grounded"):
        return decide("make_uncertain_claim")
    if issues:
        return Decision(NEEDS_APPROVAL, "The content check found: " + "; ".join(issues)[:300], "Engagement")
    return decide("answer_routine_question", {"channel_allows": True, "suppressed": suppressed,
                                              "kill_switch": kill_switch})


def needs_reply(last_inbound: datetime | None, last_outbound: datetime | None) -> bool:
    return bool(last_inbound) and (not last_outbound or last_inbound > last_outbound)


# --------------------------------------------------------------------------- Frappe side


def conversations_campaign(company: str) -> str:
    """The Company's paused campaign that carries one-off replies (created on first use)."""
    import frappe

    name = frappe.db.get_value("Sales Campaign", {"company": company, "campaign_name": CONVERSATIONS})
    if name:
        return name
    return frappe.get_doc({
        "doctype": "Sales Campaign", "company": company, "campaign_name": CONVERSATIONS, "status": "Paused",
        "offer": "One-off replies in conversations", "daily_limit": 100,
        "steps": [{"step_no": 1, "channel": "Email", "delay_days": 0, "subject_template": "Re: {{business_name}}",
                   "body_template": "{{personal_line}}"}],
    }).insert(ignore_permissions=True).name


def member_for(company: str, campaign: str, prospect) -> str:
    import frappe

    key = f"{campaign}:{prospect.name}"
    name = frappe.db.get_value("Sales Campaign Member", {"idempotency_key": key})
    if name:
        return name
    return frappe.get_doc({
        "doctype": "Sales Campaign Member", "company": company, "campaign": campaign, "prospect": prospect.name,
        "crm_lead": prospect.crm_lead, "email": prospect.email, "phone": prospect.phone, "status": "Completed",
        "eligibility_reason": "Conversation", "idempotency_key": key,
        "unsubscribe_token": frappe.generate_hash(length=32),
    }).insert(ignore_permissions=True).name


def timeline(prospect_name: str, limit: int = 40) -> list[dict]:
    """The lead's history across channels, oldest first."""
    import frappe
    from frappe.utils import get_datetime

    from reckon_sales_agent.providers.channels import html_to_text

    messages = frappe.get_all("Sales Outreach Message", filters={"prospect": prospect_name},
                              fields=["name", "channel", "subject", "body", "status", "sent_on", "creation",
                                      "is_reply", "campaign"], order_by="creation asc", limit=200)
    items = [{"at": m.sent_on or m.creation, "direction": "out", "channel": m.channel, "status": m.status,
              "subject": m.subject, "text": html_to_text(m.body)[:1500], "ref": m.name} for m in messages]
    names = [m.name for m in messages]
    if names:
        for c in frappe.get_all("Communication", filters={"reference_doctype": "Sales Outreach Message",
                                                         "reference_name": ["in", names], "sent_or_received": "Received"},
                                fields=["name", "subject", "content", "creation"], limit=200):
            items.append({"at": c.creation, "direction": "in", "channel": "Email", "status": "Received",
                          "subject": c.subject, "text": html_to_text(c.content)[:1500], "ref": c.name})
        for e in frappe.get_all("Sales Communication Event", filters={"message": ["in", names],
                                                                     "event_type": ["like", "call\\_%"]},
                                fields=["event_type", "event_time", "detail"], limit=200):
            items.append({"at": e.event_time, "direction": "in", "channel": "Call",
                          "status": e.event_type.replace("call_", "").replace("_", " "), "subject": "",
                          "text": e.detail or "", "ref": ""})
    if "frappe_whatsapp" in frappe.get_installed_apps():
        phone = frappe.db.get_value("Sales Prospect", prospect_name, "phone")
        if phone:
            # Typed in WhatsApp directly (not by a sequence): the incoming ones are chat messages already.
            for w in frappe.get_all("WhatsApp Message", filters={"type": "Outgoing", "reference_doctype": ["is", "not set"],
                                                                  "to": ["in", [phone, phone.lstrip("+")]]},
                                    fields=["name", "message", "creation"], limit=100):
                items.append({"at": w.creation, "direction": "out", "channel": "WhatsApp", "status": "Sent",
                              "subject": "", "text": (w.message or "")[:1500], "ref": w.name})
    for c in frappe.get_all("Sales Chat Message", filters={"prospect": prospect_name},
                            fields=["name", "channel", "text", "sent_at", "kind", "direction", "outreach_message"], limit=200):
        if c.direction == "Out":
            # Email sent from the CRM (no outreach record): shown here so the thread is complete.
            if c.outreach_message or c.channel != "Email":
                continue
            items.append({"at": c.sent_at, "direction": "out", "channel": "Email", "status": "Sent", "subject": "",
                          "text": (c.text or "")[:1500], "ref": c.name})
            continue
        items.append({"at": c.sent_at, "direction": "in", "channel": c.channel,
                      "status": "Comment on a post" if c.kind == "Comment" else "Received", "subject": "",
                      "text": (c.text or "")[:1500], "ref": c.name})
    if frappe.db.exists("DocType", "Sales Meeting"):
        for m in frappe.get_all("Sales Meeting", filters={"prospect": prospect_name},
                                fields=["name", "status", "starts_on", "creation", "outcome_notes"], limit=50):
            items.append({"at": m.starts_on or m.creation, "direction": "note", "channel": "Meeting",
                          "status": m.status, "subject": "", "text": m.outcome_notes or "", "ref": m.name})
    # Real datetimes, not their text: a text sort is only right while every time is written the same way.
    items.sort(key=lambda i: get_datetime(i["at"] or "1970-01-01"))
    return items[-limit:]


def threads(company: str, limit: int = 40) -> list[dict]:
    """Leads with a conversation, newest activity first; ``needs_reply`` when they spoke last."""
    import frappe

    rows = frappe.get_all("Sales Communication Event", filters={
        "company": company, "event_type": ["in", list(INBOUND + OUTBOUND)]},
        fields=["message", "member", "event_type", "event_time"], order_by="event_time desc", limit=5000)
    prospects = {m.name: m.prospect for m in frappe.get_all("Sales Outreach Message", filters={
        "name": ["in", list({r.message for r in rows if r.message}) or [""]]}, fields=["name", "prospect"])}
    # Messages that arrived outside a sequence (WhatsApp, chats) carry only the lead's Conversations member.
    members = {m.name: m.prospect for m in frappe.get_all("Sales Campaign Member", filters={
        "name": ["in", list({r.member for r in rows if r.member and not r.message}) or [""]]},
        fields=["name", "prospect"])}
    by: dict[str, dict] = {}
    for row in rows:
        prospect = prospects.get(row.message) or members.get(row.member)
        if not prospect:
            continue
        t = by.setdefault(prospect, {"prospect": prospect, "last_in": None, "last_out": None, "last": row.event_time})
        if row.event_type in INBOUND and not t["last_in"]:
            t["last_in"] = row.event_time
        if row.event_type in OUTBOUND and not t["last_out"]:
            t["last_out"] = row.event_time
    chats: dict[str, str] = {}
    for c in frappe.get_all("Sales Chat Message", filters={"company": company},
                            fields=["prospect", "direction", "sent_at", "channel"], order_by="sent_at desc", limit=5000):
        if not c.prospect:
            continue
        t = by.setdefault(c.prospect, {"prospect": c.prospect, "last_in": None, "last_out": None, "last": c.sent_at})
        if str(c.sent_at) > str(t["last"]):
            t["last"] = c.sent_at
        if c.direction == "In":
            chats.setdefault(c.prospect, c.channel)
            if not t["last_in"] or str(c.sent_at) > str(t["last_in"]):
                t["last_in"] = c.sent_at
    for meta_lead in frappe.get_all("Sales Prospect", filters={"company": company, "source_type": "meta_lead_ads"},
                                    fields=["name", "creation"], order_by="creation desc", limit=200):
        by.setdefault(meta_lead.name, {"prospect": meta_lead.name, "last_in": meta_lead.creation, "last_out": None,
                                       "last": meta_lead.creation})
    from reckon_sales_agent.agents.conversations import by_prospect

    convos = by_prospect(company)
    info = {p.name: p for p in frappe.get_all("Sales Prospect", filters={"name": ["in", list(by) or [""]]},
                                              fields=["name", "business_name", "email", "phone", "source_type"])}
    drafts = set(frappe.get_all("Sales Outreach Message", filters={"prospect": ["in", list(by) or [""]],
                                                                   "status": "Draft", "is_reply": 1}, pluck="prospect"))
    out = []
    for t in sorted(by.values(), key=lambda t: str(t["last"]), reverse=True)[:limit]:
        p = info.get(t["prospect"]) or {}
        out.append({**t, "business": p.get("business_name"), "email": p.get("email"), "phone": p.get("phone"),
                    "source": p.get("source_type"), "needs_reply": needs_reply(t["last_in"], t["last_out"]),
                    "draft_waiting": t["prospect"] in drafts, "chat": chats.get(t["prospect"]),
                    "conversation": convos.get(t["prospect"]) or {}})
    return out


def draft_reply(prospect_name: str, reason: str = "", instruction: str = "", allow_auto: bool = False) -> str:
    """An AI reply on the right channel, saved as a Draft for approval; returns the message name.

    ``allow_auto`` (the conversation is on autopilot): the reply goes out at once when the fast-answer policy
    allows; otherwise the conversation is handed to a person with the reason. A person asking for a suggestion
    always gets a draft."""
    import frappe
    from frappe import _
    from frappe.utils import get_datetime, get_url, now_datetime

    from reckon_sales_agent.agents.content import check_step, knowledge_prompt
    from reckon_sales_agent.agents.content_agent import approved_knowledge
    from reckon_sales_agent.campaigns.engine import record_event
    from reckon_sales_agent.campaigns.templates import footer, text_to_html
    from reckon_sales_agent.constants import USAGE_AI
    from reckon_sales_agent.providers.factory import get_llm
    from reckon_sales_agent.providers.llm import LLMError, untrusted
    from reckon_sales_agent.usage import get_settings, log_activity, remaining, reserve

    prospect = frappe.get_doc("Sales Prospect", prospect_name)
    company = prospect.company
    settings = get_settings(company)
    from reckon_sales_agent.agents.chat import last_chat

    last_wa = prospect.get("whatsapp_last_inbound")
    chat = last_chat(prospect.name)
    if chat:
        chat["at"] = get_datetime(chat["at"])
    channel, why_channel = choose_channel(prospect.as_dict(), get_datetime(last_wa) if last_wa else None,
                                          now_datetime(), chat)
    if not channel:
        frappe.throw(_("No written channel for this lead: {0}").format(why_channel))
    if prospect.do_not_contact:
        frappe.throw(_("This lead asked not to be contacted."))
    llm = get_llm(company)
    if not llm:
        frappe.throw(_("Turn on AI to draft replies."))
    if remaining(company, USAGE_AI) <= 0:
        frappe.throw(_("Monthly AI limit reached."))
    history = "\n".join(f"[{i['at']}] {'THEM' if i['direction'] == 'in' else 'US'} via {i['channel']} "
                        f"({i['status']}): {i['subject'] + ' — ' if i['subject'] else ''}{i['text'][:600]}"
                        for i in timeline(prospect_name, 15)) or "No messages yet."
    knowledge = approved_knowledge(company)
    reserve(company, USAGE_AI, 1, prospect)
    frappe.db.commit()
    try:
        data = llm.complete_json(
            REPLY_SYSTEM,
            untrusted("lead", f"{prospect.business_name} · {prospect.city or ''} · {prospect.industry or ''}") + "\n"
            + untrusted("conversation", history) + "\n" + untrusted("approved knowledge", knowledge_prompt(knowledge))
            + f"\nChannel: {channel}\nWhy now: {reason or 'they are waiting for an answer'}\n"
            + (f"Salesperson's instruction: {instruction[:500]}\n" if instruction else ""),
            REPLY_SCHEMA, max_tokens=1500)
    except LLMError as exc:
        frappe.throw(str(exc))
    body = str(data.get("body") or "").strip()
    subject = " ".join(str(data.get("subject") or "").split())[:140] if channel == "Email" else ""
    knowledge_text = "\n".join(f"{k.title}\n{k.content}" for k in knowledge)
    pricing_text = "\n".join(k.content for k in knowledge if k.category in ("Pricing", "Offer"))
    issues = check_step({"step_no": 0, "channel": channel, "subject_template": subject, "body_template": body},
                        knowledge_text, pricing_text, [])
    campaign = conversations_campaign(company)
    member = member_for(company, campaign, prospect)
    token = frappe.db.get_value("Sales Campaign Member", member, "unsubscribe_token")
    sender = settings.sender_name or company
    html = text_to_html(frappe.utils.escape_html(f"{body}\n\n{sender}"))
    if channel == "Email":
        html += footer(sender, settings.physical_address,
                       get_url(f"/api/method/reckon_sales_agent.api.unsubscribe?token={token}"))
    message = frappe.get_doc({
        "doctype": "Sales Outreach Message", "company": company, "campaign": campaign, "member": member,
        "prospect": prospect.name, "step_no": 0, "channel": channel,
        "recipient": prospect.email if channel == "Email" else chat["recipient"] if chat and channel == chat["channel"]
        else prospect.phone,
        "subject": subject or f"Reply: {prospect.business_name}"[:140], "body": html, "ai_generated": 1,
        "is_reply": 1, "status": "Draft",
        "error": ("Content check: " + "; ".join(issues))[:500] if issues else None,
        "idempotency_key": f"omni:{prospect.name}:{frappe.generate_hash(length=8)}",
    }).insert(ignore_permissions=True)
    record_event(message, "drafted", f"draft:{message.name}", detail=str(data.get("why") or "")[:500])
    from reckon_sales_agent.campaigns.replies import classify_rules

    last_in = next((i["text"] for i in reversed(timeline(prospect_name, 15)) if i["direction"] == "in"), "")
    channels = CHAT_CHANNELS + (("WhatsApp",) if settings.get("autopilot_whatsapp") else ())
    decision = auto_answer_decision(allow_auto and bool(settings.get("chat_auto_answer")), channel, data, issues,
                                    classify_rules(last_in), bool(prospect.do_not_contact), bool(settings.kill_switch),
                                    channels)
    if decision.allowed:
        from reckon_sales_agent.agents.approvals import fingerprint, message_payload

        message.db_set({"status": "Approved", "auto_approved_by_policy": 1,
                        "approval_fingerprint": fingerprint(message_payload(message))})
        log_activity(company, "reply_auto_answered", message, f"{channel}: {data.get('why') or ''}"[:500],
                     actor_type="agent", agent="Conversations", policy_outcome=decision.reason)
        frappe.db.commit()
        from reckon_sales_agent.campaigns.engine import send_message

        send_message(frappe.get_doc("Sales Outreach Message", message.name))  # dry run while sending is off
        frappe.db.commit()
        from reckon_sales_agent.agents.inbox_events import notify_inbox
        notify_inbox(company, prospect.name)
        return message.name
    if allow_auto and settings.get("chat_auto_answer"):
        from reckon_sales_agent.agents.conversations import handoff

        handoff(company, prospect.name, f"The AI may not answer this on its own: {decision.reason}")
    log_activity(company, "reply_drafted_omni", message, f"{channel}: {data.get('why') or why_channel}"[:500],
                 actor_type="agent", agent="Conversations", policy_outcome=f"draft: {decision.reason}"[:140])
    frappe.db.commit()
    from reckon_sales_agent.agents.inbox_events import notify_inbox
    notify_inbox(company, prospect.name)
    return message.name


def _sender(channel: str, prospect, settings, company: str, wrote: bool) -> str:
    """The account a reply on this channel goes out from, shown before the person sends it."""
    import frappe

    from reckon_sales_agent.agents.chat import ACCOUNT_PLATFORM

    if channel == "Email":
        return frappe.db.get_value("Email Account", {"enable_outgoing": 1, "default_outgoing": 1}, "email_id") or ""
    if channel == "WhatsApp":
        return settings.get("whatsapp_account") or ""
    if channel == "SMS":
        return settings.get("sms_provider") or ""
    if channel in ACCOUNT_PLATFORM:
        platform = ACCOUNT_PLATFORM[channel]
        if wrote:  # Meta replies from the Page this person wrote to
            account_id = frappe.db.get_value("Sales Chat Message", {"prospect": prospect.name, "channel": channel, "direction": "In"},
                                             "account_id", order_by="sent_at desc")
            name = frappe.db.get_value("Sales Social Account", {"company": company, "platform": platform, "account_id": account_id},
                                       "account_name")
            if name:
                return name
        return ", ".join(frappe.get_all("Sales Social Account", filters={"company": company, "platform": platform, "enabled": 1},
                                        pluck="account_name"))
    return ""


def reply_channels(prospect_name: str) -> list[dict]:
    """Where a person can answer this lead now: [{channel, ok, reason, window_closed}], the lead's latest channel first."""
    import frappe
    from frappe.utils import now_datetime

    from reckon_sales_agent.agents.chat import ACCOUNT_PLATFORM, last_chat
    from reckon_sales_agent.agents.engagement import within_service_window
    from reckon_sales_agent.providers.channels import reachability
    from reckon_sales_agent.usage import get_settings

    prospect = frappe.get_doc("Sales Prospect", prospect_name)
    settings = get_settings(prospect.company)
    chat = last_chat(prospect_name)
    latest = [chat["channel"]] if chat and chat["channel"] in CHAT_CHANNELS + ("SMS", "WhatsApp") else []
    out = []
    for channel in dict.fromkeys(latest + ["WhatsApp", "Email", "SMS", "Messenger", "Instagram", "Web Chat"]):
        ok, reason, _recipient = reachability(channel, prospect, settings)
        closed = False
        if ok and channel == "WhatsApp" and not within_service_window(prospect.get("whatsapp_last_inbound"), now_datetime()):
            ok, reason, closed = False, "Outside WhatsApp's 24-hour window: send an approved template.", True
        wrote = channel in CHAT_CHANNELS and bool(frappe.db.exists("Sales Chat Message", {"prospect": prospect_name, "channel": channel}))
        if channel in CHAT_CHANNELS and not wrote:
            # Meta lets a Page reply only to someone who wrote to it: a connected Page is listed, but cannot send yet.
            if channel not in ACCOUNT_PLATFORM or not frappe.db.exists("Sales Social Account", {
                    "company": prospect.company, "platform": ACCOUNT_PLATFORM[channel], "enabled": 1}):
                continue  # not connected here, or never wrote there
            ok, reason = False, "They have not messaged this Page yet. Meta lets a Page reply only after the person writes in."
        out.append({"channel": channel, "ok": bool(ok), "reason": reason, "window_closed": closed,
                    "from": _sender(channel, prospect, settings, prospect.company, wrote)})
    return out


def compose(prospect_name: str, channel: str, text: str, template: str | None = None) -> str:
    """A person's own reply (or an approved WhatsApp template): approved by them and sent now.

    Dry run while sending is off. The conversation switches to Human only so the AI does not answer over them.
    """
    import frappe
    from frappe import _
    from frappe.utils import get_url

    from reckon_sales_agent.agents import conversations
    from reckon_sales_agent.agents.chat import last_chat
    from reckon_sales_agent.campaigns.engine import approve_message, record_event, send_message
    from reckon_sales_agent.campaigns.templates import footer, text_to_html
    from reckon_sales_agent.providers.channels import reachability
    from reckon_sales_agent.usage import get_settings, log_activity

    text = (text or "").strip()
    if not text and not template:
        frappe.throw(_("Write a message."))
    prospect = frappe.get_doc("Sales Prospect", prospect_name)
    if prospect.do_not_contact:
        frappe.throw(_("This lead asked not to be contacted."))
    options = {o["channel"]: o for o in reply_channels(prospect_name)}
    option = options.get(channel)
    template_ok = bool(template) and channel == "WhatsApp" and bool(option) and option["window_closed"]
    if not option or not (option["ok"] or template_ok):
        frappe.throw(_("You cannot reply on {0} now: {1}").format(channel, (option or {}).get("reason", _("not available"))))
    company = prospect.company
    settings = get_settings(company)
    campaign = conversations_campaign(company)
    member = member_for(company, campaign, prospect)
    chat = last_chat(prospect_name)
    _ok, _why, recipient = reachability(channel, prospect, settings)
    if chat and chat["channel"] == channel:
        recipient = chat["recipient"]
    html = text_to_html(frappe.utils.escape_html(text[:3000])) if text else frappe.utils.escape_html(template or "")
    if channel == "Email":
        token = frappe.db.get_value("Sales Campaign Member", member, "unsubscribe_token")
        sender = settings.sender_name or company
        html += footer(sender, settings.physical_address,
                       get_url(f"/api/method/reckon_sales_agent.api.unsubscribe?token={token}"))
    message = frappe.get_doc({
        "doctype": "Sales Outreach Message", "company": company, "campaign": campaign, "member": member,
        "prospect": prospect.name, "step_no": 0, "channel": channel, "recipient": recipient,
        "subject": f"Re: {prospect.business_name}"[:140] if channel == "Email" else f"Reply: {prospect.business_name}"[:140],
        "body": html, "ai_generated": 0, "is_reply": 1, "status": "Draft",
        "whatsapp_template": template if channel == "WhatsApp" else None,
        "idempotency_key": f"human:{prospect.name}:{frappe.generate_hash(length=8)}",
    }).insert(ignore_permissions=True)
    record_event(message, "drafted", f"draft:{message.name}", detail="written by a person")
    approve_message(message)
    send_message(frappe.get_doc("Sales Outreach Message", message.name))
    convo = conversations.get(company, prospect.name)
    if convo.ai_mode != "Human only":
        convo.db_set("ai_mode", "Human only")  # a person took over: the AI stops answering here
    if not convo.assigned_to:
        convo.db_set("assigned_to", frappe.session.user)
    log_activity(company, "reply_sent_by_person", message, f"{channel}: {(text or template or '')[:200]}", agent="Conversations")
    from reckon_sales_agent.agents.inbox_events import notify_inbox

    notify_inbox(company, prospect.name)
    return frappe.db.get_value("Sales Outreach Message", message.name, "status")
