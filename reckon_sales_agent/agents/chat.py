"""Chat channels for the Conversations agent: Facebook Messenger, Instagram messages and the website chat.

Only official integrations are used:

* Messenger and Instagram: the Meta Messenger Platform. Meta calls our webhook (signed with the app secret,
  header ``X-Hub-Signature-256``) when someone writes to a connected Page or Instagram account; replies go out
  through the Send API (``POST /{page-id}/messages``) inside Meta's 24-hour standard messaging window, as a
  ``RESPONSE``. Nobody is messaged first: a chat always starts with the lead.
* Website chat: a small widget on the Company's own website (``/assets/reckon_sales_agent/js/reckon_webchat.js``)
  that talks to two public endpoints with the Company's public widget key.

What a lead writes becomes a Sales Chat Message and a thread in Conversations; the AI drafts the answer on the
same channel and a person approves it, like every outbound message. Parsing and checks here are pure.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta

CHAT_CHANNELS = ("Messenger", "Instagram", "Web Chat")
META_CHANNELS = {"page": "Messenger", "instagram": "Instagram"}
ACCOUNT_PLATFORM = {"Messenger": "Facebook Page", "Instagram": "Instagram"}
SOURCE_TYPES = {"Messenger": "messenger", "Instagram": "instagram", "Web Chat": "web_chat"}
WINDOW = timedelta(hours=24)  # Meta's standard messaging window
MAX_TEXT = 2000
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def verify_meta_signature(app_secret: str | None, body: bytes, header: str | None) -> bool:
    """Meta signs each webhook call: ``X-Hub-Signature-256: sha256=<hex HMAC of the raw body>``."""
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body or b"", hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[7:].strip())


def meta_events(payload: dict) -> list[dict]:
    """Messages people sent to a Page or Instagram account, from one webhook call (echoes and receipts skipped)."""
    channel = META_CHANNELS.get(str(payload.get("object") or ""))
    if not channel:
        return []
    out = []
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for event in entry.get("messaging") or []:
            message = event.get("message") if isinstance(event, dict) else None
            if not isinstance(message, dict) or message.get("is_echo") or not message.get("mid"):
                continue
            text = str(message.get("text") or "").strip()
            if not text and message.get("attachments"):
                kinds = {str(a.get("type") or "file") for a in message["attachments"] if isinstance(a, dict)}
                text = f"[sent {', '.join(sorted(kinds)) or 'an attachment'}]"
            sender = str((event.get("sender") or {}).get("id") or "")
            account = str((event.get("recipient") or {}).get("id") or entry.get("id") or "")
            if not sender or not account or sender == account:
                continue
            stamp = event.get("timestamp")
            at = datetime.fromtimestamp(stamp / 1000) if isinstance(stamp, int | float) else None
            out.append({"channel": channel, "account_id": account, "contact_id": sender,
                        "external_id": str(message["mid"])[:140], "text": text[:MAX_TEXT], "at": at})
    return out


def within_window(last_inbound: datetime | None, now: datetime) -> bool:
    return bool(last_inbound) and now - last_inbound < WINDOW


def origin_allowed(origin: str | None, allowed: str | None) -> bool:
    """The website chat answers only on the Company's listed websites (any website when none is listed)."""
    sites = {s.strip().rstrip("/").lower() for s in re.split(r"[\s,]+", allowed or "") if s.strip()}
    if not sites:
        return True
    return bool(origin) and origin.strip().rstrip("/").lower() in sites


def visitor_fields(data: dict) -> tuple[dict, str | None]:
    """(clean fields, error) from what a website visitor typed."""
    text = " ".join(str(data.get("text") or "").split())[:MAX_TEXT]
    name = " ".join(str(data.get("name") or "").split())[:80]
    email = str(data.get("email") or "").strip().lower()[:140]
    phone = re.sub(r"[^\d+]", "", str(data.get("phone") or ""))[:20]
    if not text:
        return {}, "Write a message."
    if email and not EMAIL.match(email):
        return {}, "That email address does not look right."
    return {"text": text, "name": name, "email": email, "phone": phone}, None


def send_params(contact_id: str, text: str) -> dict:
    """Send API body for a reply inside the 24-hour window."""
    return {"recipient": {"id": contact_id}, "messaging_type": "RESPONSE", "message": {"text": text[:MAX_TEXT]}}


# --------------------------------------------------------------------------- Frappe side


def account_company(channel: str, account_id: str) -> tuple[str, str] | None:
    """(company, Sales Social Account) for the Page or Instagram account a message was sent to."""
    import frappe

    row = frappe.db.get_value("Sales Social Account", {
        "platform": ACCOUNT_PLATFORM.get(channel), "account_id": account_id, "enabled": 1, "receive_messages": 1},
        ["company", "name"], as_dict=True)
    return (row.company, row.name) if row else None


def receive_chat(company: str, channel: str, account_id: str, contact_id: str, text: str, external_id: str,
                 at=None, contact_name: str | None = None, email: str | None = None, phone: str | None = None) -> str | None:
    """Store an inbound chat message on the lead's thread (creating the lead when it is new); returns its name."""
    import frappe
    from frappe.utils import now_datetime

    from reckon_sales_agent.usage import log_activity

    if frappe.db.exists("Sales Chat Message", {"external_id": external_id}):
        return None  # Meta retries a webhook it thinks failed
    prospect = _prospect_for(company, channel, contact_id, contact_name, email, phone)
    doc = frappe.get_doc({
        "doctype": "Sales Chat Message", "company": company, "prospect": prospect.name, "channel": channel,
        "direction": "In", "sent_at": at or now_datetime(), "contact_id": contact_id, "account_id": account_id,
        "external_id": external_id, "contact_name": contact_name or prospect.business_name, "text": text,
    }).insert(ignore_permissions=True)
    from reckon_sales_agent.agents.omni import conversations_campaign, member_for

    campaign = conversations_campaign(company)
    frappe.get_doc({
        "doctype": "Sales Communication Event", "company": company, "event_type": "received", "campaign": campaign,
        "member": member_for(company, campaign, prospect), "channel": channel, "event_time": doc.sent_at,
        "provider_message_id": external_id[:140], "idempotency_key": f"received:chat:{external_id}"[:140],
        "detail": text[:500],
    }).insert(ignore_permissions=True)
    log_activity(company, "chat_received", prospect, f"{channel}: {text[:200]}", actor_type="system",
                 agent="Conversations")
    _notify(company, prospect, channel, text)
    return doc.name


def _prospect_for(company, channel, contact_id, contact_name, email, phone):
    import frappe
    from frappe.utils import now_datetime

    from reckon_sales_agent.discovery.normalize import normalize_phone

    known = frappe.db.get_value("Sales Chat Message", {"company": company, "channel": channel,
                                                       "contact_id": contact_id, "prospect": ["is", "set"]},
                                "prospect", order_by="creation desc")
    if not known and email:
        known = frappe.db.get_value("Sales Prospect", {"company": company, "email": email, "merged_into": ["is", "not set"]})
    phone = normalize_phone(phone) if phone else None
    if not known and phone:
        known = frappe.db.get_value("Sales Prospect", {"company": company, "normalized_phone": phone,
                                                       "merged_into": ["is", "not set"]})
    if known:
        doc = frappe.get_doc("Sales Prospect", known)
        updates = {k: v for k, v in (("email", email), ("phone", phone)) if v and not doc.get(k)}
        if updates:
            doc.db_set(updates)
        return doc
    label = contact_name or f"{channel} contact …{contact_id[-4:]}"
    given = {"source": "chat", "retrieved_at": str(now_datetime()), "retention_days": None,
             "attribution": f"Given by the person in a {channel} chat"}
    provided = [k for k, v in (("business_name", contact_name), ("email", email), ("phone", phone)) if v]
    # They wrote to us first: an inbound lead, approved for a reply on the channel they chose.
    return frappe.get_doc({
        "doctype": "Sales Prospect", "company": company, "business_name": label[:140], "source_type": SOURCE_TYPES[channel],
        "review_status": "Approved", "external_id": f"{SOURCE_TYPES[channel]}:{contact_id}"[:140], "email": email or None,
        "phone": phone or None, "consent_source": f"Wrote to us on {channel}", "first_seen": now_datetime(),
        "last_seen": now_datetime(), "provenance_json": json.dumps({k: given for k in provided}, sort_keys=True),
    }).insert(ignore_permissions=True)


def _notify(company, prospect, channel, text) -> None:
    import frappe

    from reckon_sales_agent.usage import get_settings

    user = get_settings(company).get("task_assignee")
    if user:
        frappe.publish_realtime("msgprint", {"message": f"{channel} · {prospect.business_name}: {text[:140]}",
                                             "indicator": "blue", "alert": True}, user=user, after_commit=True)


def last_chat(prospect_name: str) -> dict | None:
    """The lead's latest inbound chat: {channel, at, contact_id, account_id}."""
    import frappe

    row = frappe.db.get_value("Sales Chat Message", {"prospect": prospect_name, "direction": "In"},
                              ["channel", "sent_at", "contact_id", "account_id"], as_dict=True, order_by="sent_at desc")
    return {"channel": row.channel, "at": row.sent_at, "contact_id": row.contact_id,
            "account_id": row.account_id} if row else None


def reachable(channel: str, prospect_name: str) -> tuple[bool, str, str | None]:
    """(reachable, reason, contact id) for a chat reply."""
    import frappe
    from frappe.utils import get_datetime, now_datetime

    row = frappe.db.get_value("Sales Chat Message", {"prospect": prospect_name, "channel": channel, "direction": "In"},
                              ["sent_at", "contact_id"], as_dict=True, order_by="sent_at desc")
    if not row:
        return False, f"They have not written on {channel}.", None
    if channel != "Web Chat" and not within_window(get_datetime(row.sent_at), now_datetime()):
        return False, f"More than 24 hours since they wrote on {channel}; Meta allows replies only within 24 hours.", None
    return True, f"Replying on {channel}.", row.contact_id


def deliver(message) -> str:
    """Send an approved chat reply; returns the platform's message ID."""
    import frappe
    import requests
    from frappe.utils import now_datetime

    from reckon_sales_agent.providers.channels import ChannelUnavailable, html_to_text

    channel = message.channel
    text = html_to_text(message.body)[:MAX_TEXT]
    inbound = frappe.db.get_value("Sales Chat Message", {"prospect": message.prospect, "channel": channel,
                                                         "contact_id": message.recipient, "direction": "In"},
                                  "account_id", order_by="sent_at desc")
    external_id = f"out:{message.name}"
    if channel in META_CHANNELS.values():
        name = frappe.db.get_value("Sales Social Account", {"company": message.company, "enabled": 1,
                                                            "platform": ACCOUNT_PLATFORM[channel], "account_id": inbound})
        if not name:
            raise ChannelUnavailable(f"The {channel} account this lead wrote to is no longer connected.")
        account = frappe.get_doc("Sales Social Account", name)
        token = account.get_password("access_token", raise_exception=False)
        page_id = account.account_id
        if channel == "Instagram":  # Instagram messages go out through the Facebook Page linked to the account
            page_id = account.get("linked_page_id") or page_id
        try:
            response = requests.post(f"https://graph.facebook.com/v23.0/{page_id}/messages",
                                     json=send_params(message.recipient, text), params={"access_token": token},
                                     timeout=30)
        except requests.RequestException as exc:
            raise ChannelUnavailable(f"{channel} unreachable.") from exc
        if response.status_code >= 400:
            from reckon_sales_agent.providers.llm import http_reason

            raise ChannelUnavailable(f"{channel} refused the reply: {http_reason(response)}")
        external_id = str((response.json() or {}).get("message_id") or external_id)
    frappe.get_doc({
        "doctype": "Sales Chat Message", "company": message.company, "prospect": message.prospect,
        "channel": channel, "direction": "Out", "sent_at": now_datetime(), "contact_id": message.recipient,
        "account_id": inbound, "external_id": external_id[:140], "outreach_message": message.name, "text": text,
    }).insert(ignore_permissions=True)
    return external_id


def auto_draft(prospect: str) -> str | None:
    """With autopilot on, the AI drafts the answer as soon as a lead writes; a person still approves it."""
    import frappe

    from reckon_sales_agent.usage import get_settings

    doc = frappe.get_doc("Sales Prospect", prospect)
    if not get_settings(doc.company).get("autopilot_enabled"):
        return None
    if frappe.db.exists("Sales Outreach Message", {"prospect": prospect, "status": "Draft", "is_reply": 1}):
        return None
    from reckon_sales_agent.agents.omni import draft_reply

    try:
        return draft_reply(prospect, reason="they just wrote and are waiting for an answer")
    except frappe.ValidationError:
        frappe.clear_messages()  # no AI or no written channel: the thread waits in Conversations
        return None
