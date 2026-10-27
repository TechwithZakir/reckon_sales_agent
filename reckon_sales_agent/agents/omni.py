"""Omni-channel conversations agent: one thread per lead across email, WhatsApp, calls and forms, and an AI
reply on the right channel, waiting for a person's approval.

- ``threads`` lists the Company's conversations, newest first, flagging those where the lead spoke last.
- ``timeline`` gives one lead's whole history: messages sent, replies received, call outcomes, meetings.
- ``draft_reply`` picks the channel (WhatsApp inside the 24-hour window with consent, else email, else a call)
  and has Claude write from the history and the approved knowledge only; the content check runs on it and it
  is saved as a Draft for approval, like every outbound message.

One-off replies that belong to no sequence go through the Company's "Conversations" campaign, which stays
paused (the sequence engine never drafts from it) but keeps approval, limits and the audit trail.
``choose_channel`` and ``needs_reply`` are pure.
"""

from __future__ import annotations

from datetime import datetime, timedelta

CONVERSATIONS = "Conversations"
WINDOW = timedelta(hours=24)
# Only something the lead wrote asks for a written reply; call outcomes have their own next steps (a meeting,
# a callback, or stopping), so a "not interested" call never triggers an AI message.
INBOUND = ("received",)
OUTBOUND = ("sent", "dry_run")

REPLY_SCHEMA = {
    "type": "object",
    "properties": {"subject": {"type": "string"}, "body": {"type": "string"}, "why": {"type": "string"}},
    "required": ["subject", "body", "why"],
    "additionalProperties": False,
}
REPLY_SYSTEM = (
    "You write the next message from a B2B seller in Bangladesh to one lead, continuing the conversation shown. "
    "Answer what they asked or said, using ONLY facts in the approved knowledge; never invent prices, discounts, "
    "clients or numbers. If they asked for something the knowledge does not cover, say a colleague will confirm. "
    "Propose one simple next step (a call or a short demo). Match their language (English or Bangla). Email: "
    "subject under 60 characters, body under 120 words. WhatsApp: under 60 words, no subject (use empty). "
    "why: one sentence for the salesperson on why this reply. Do not add an unsubscribe line; it is added."
)


def choose_channel(prospect: dict, last_whatsapp_inbound: datetime | None, now: datetime) -> tuple[str | None, str]:
    """(channel, reason) for the next written reply, or (None, reason) when only a call is possible."""
    if (prospect.get("whatsapp_consent") and prospect.get("phone") and last_whatsapp_inbound
            and now - last_whatsapp_inbound < WINDOW):
        return "WhatsApp", "They wrote on WhatsApp in the last 24 hours."
    if prospect.get("email"):
        return "Email", "Email is the channel they can be written to."
    if prospect.get("phone"):
        return None, "Only a phone number: a salesperson should call."
    return None, "No way to reach this lead yet."


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
            for w in frappe.get_all("WhatsApp Message", filters={"type": "Incoming",
                                                                  "from": ["in", [phone, phone.lstrip("+")]]},
                                    fields=["name", "message", "creation"], limit=100):
                items.append({"at": w.creation, "direction": "in", "channel": "WhatsApp", "status": "Received",
                              "subject": "", "text": (w.message or "")[:1500], "ref": w.name})
    if frappe.db.exists("DocType", "Sales Meeting"):
        for m in frappe.get_all("Sales Meeting", filters={"prospect": prospect_name},
                                fields=["name", "status", "starts_on", "creation", "outcome_notes"], limit=50):
            items.append({"at": m.starts_on or m.creation, "direction": "note", "channel": "Meeting",
                          "status": m.status, "subject": "", "text": m.outcome_notes or "", "ref": m.name})
    items.sort(key=lambda i: str(i["at"]))
    return items[-limit:]


def threads(company: str, limit: int = 40) -> list[dict]:
    """Leads with a conversation, newest activity first; ``needs_reply`` when they spoke last."""
    import frappe

    rows = frappe.get_all("Sales Communication Event", filters={
        "company": company, "event_type": ["in", list(INBOUND + OUTBOUND)]},
        fields=["message", "event_type", "event_time"], order_by="event_time desc", limit=5000)
    prospects = {m.name: m.prospect for m in frappe.get_all("Sales Outreach Message", filters={
        "name": ["in", list({r.message for r in rows if r.message}) or [""]]}, fields=["name", "prospect"])}
    by: dict[str, dict] = {}
    for row in rows:
        prospect = prospects.get(row.message)
        if not prospect:
            continue
        t = by.setdefault(prospect, {"prospect": prospect, "last_in": None, "last_out": None, "last": row.event_time})
        if row.event_type in INBOUND and not t["last_in"]:
            t["last_in"] = row.event_time
        if row.event_type in OUTBOUND and not t["last_out"]:
            t["last_out"] = row.event_time
    for meta_lead in frappe.get_all("Sales Prospect", filters={"company": company, "source_type": "meta_lead_ads"},
                                    fields=["name", "creation"], order_by="creation desc", limit=200):
        by.setdefault(meta_lead.name, {"prospect": meta_lead.name, "last_in": meta_lead.creation, "last_out": None,
                                       "last": meta_lead.creation})
    info = {p.name: p for p in frappe.get_all("Sales Prospect", filters={"name": ["in", list(by) or [""]]},
                                              fields=["name", "business_name", "email", "phone", "source_type"])}
    drafts = set(frappe.get_all("Sales Outreach Message", filters={"prospect": ["in", list(by) or [""]],
                                                                   "status": "Draft", "is_reply": 1}, pluck="prospect"))
    out = []
    for t in sorted(by.values(), key=lambda t: str(t["last"]), reverse=True)[:limit]:
        p = info.get(t["prospect"]) or {}
        out.append({**t, "business": p.get("business_name"), "email": p.get("email"), "phone": p.get("phone"),
                    "source": p.get("source_type"), "needs_reply": needs_reply(t["last_in"], t["last_out"]),
                    "draft_waiting": t["prospect"] in drafts})
    return out


def draft_reply(prospect_name: str, reason: str = "", instruction: str = "") -> str:
    """An AI reply on the right channel, saved as a Draft for approval; returns the message name."""
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
    last_wa = prospect.get("whatsapp_last_inbound")
    channel, why_channel = choose_channel(prospect.as_dict(), get_datetime(last_wa) if last_wa else None,
                                          now_datetime())
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
        "recipient": prospect.email if channel == "Email" else prospect.phone,
        "subject": subject or f"Reply: {prospect.business_name}"[:140], "body": html, "ai_generated": 1,
        "is_reply": 1, "status": "Draft",
        "error": ("Content check: " + "; ".join(issues))[:500] if issues else None,
        "idempotency_key": f"omni:{prospect.name}:{frappe.generate_hash(length=8)}",
    }).insert(ignore_permissions=True)
    record_event(message, "drafted", f"draft:{message.name}", detail=str(data.get("why") or "")[:500])
    log_activity(company, "reply_drafted_omni", message, f"{channel}: {data.get('why') or why_channel}"[:500],
                 actor_type="agent", agent="Engagement", policy_outcome="draft only: a person approves")
    frappe.db.commit()
    return message.name
