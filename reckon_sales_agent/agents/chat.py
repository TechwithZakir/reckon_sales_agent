"""Chat channels for the Conversations agent: Facebook Messenger, Instagram messages and the website chat.

Only official integrations are used:

* Messenger and Instagram: the Meta Messenger Platform. Meta calls our webhook (signed with the app secret,
  header ``X-Hub-Signature-256``) when someone writes to a connected Page or Instagram account; replies go out
  through the Send API (``POST /{page-id}/messages``) inside Meta's 24-hour standard messaging window, as a
  ``RESPONSE``. Nobody is messaged first: a chat always starts with the lead.
* Comments: with "comment to chat" on, a buying comment on the Company's Facebook or Instagram posts ("price?",
  "দাম কত?") gets one private reply (Meta's Private Replies: ``recipient: {comment_id}``, once per comment,
  within 7 days). Other comments are ignored.
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
from datetime import datetime, timedelta, timezone

CHAT_CHANNELS = ("Messenger", "Instagram", "Web Chat")
META_CHANNELS = {"page": "Messenger", "instagram": "Instagram"}
ACCOUNT_PLATFORM = {"Messenger": "Facebook Page", "Instagram": "Instagram"}
SOURCE_TYPES = {"Messenger": "messenger", "Instagram": "instagram", "Web Chat": "web_chat", "SMS": "sms", "Voice": "voice", "WhatsApp": "whatsapp"}
WINDOW = timedelta(hours=24)  # Meta's standard messaging window
COMMENT_WINDOW = timedelta(days=7)  # Meta: one private reply per comment, within 7 days
COMMENT = "comment:"  # recipient prefix for a private reply to a comment
# A comment that asks to buy or for details (English, Bangla, Banglish). Anything else gets no private message.
BUYING = re.compile(
    r"\b(price|prices|pricing|cost|rate|how much|available|availability|stock|order|buy|purchase|delivery|deliver|"
    r"details?|info|catalog(ue)?|whole ?sale|dealer|distributor|bulk|moq|inbox|dm|pm|interested|daam|dam koto|"
    r"koto)\b|\?\s*$|দাম|মূল্য|প্রাইস|কত|অর্ডার|ডেলিভারি|ইনবক্স|বিস্তারিত|পাইকারি|ডিলার|আগ্রহী|স্টক",
    re.I)
MAX_TEXT = 2000
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def verify_meta_signature(app_secret: str | None, body: bytes, header: str | None) -> bool:
    """Meta signs each webhook call: ``X-Hub-Signature-256: sha256=<hex HMAC of the raw body>``."""
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body or b"", hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[7:].strip())


def _site_time(seconds: float) -> datetime:
    """Meta's timestamps are UTC. Reckon stores times in the site's time zone, like every other record."""
    moment = datetime.fromtimestamp(seconds, tz=timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        import frappe

        zone = ZoneInfo(frappe.utils.get_system_timezone())
    except Exception:  # outside a site (tests): keep UTC
        return moment.replace(tzinfo=None)
    return moment.astimezone(zone).replace(tzinfo=None)


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
            at = _site_time(stamp / 1000) if isinstance(stamp, int | float) else None
            out.append({"channel": channel, "account_id": account, "contact_id": sender,
                        "external_id": str(message["mid"])[:140], "text": text[:MAX_TEXT], "at": at})
    return out


def meta_comments(payload: dict) -> list[dict]:
    """New comments on the account's posts, from one webhook call (the Page's own comments skipped)."""
    channel = META_CHANNELS.get(str(payload.get("object") or ""))
    out = []
    for entry in payload.get("entry") or [] if channel else []:
        if not isinstance(entry, dict):
            continue
        account = str(entry.get("id") or "")
        for change in entry.get("changes") or []:
            value = change.get("value") if isinstance(change, dict) else None
            if not isinstance(value, dict):
                continue
            if channel == "Messenger" and change.get("field") == "feed" and value.get("item") == "comment" \
                    and value.get("verb") == "add":
                comment_id, text, author, post = value.get("comment_id"), value.get("message"), value.get("from"), \
                    value.get("post_id")
            elif channel == "Instagram" and change.get("field") == "comments":
                comment_id, text, author, post = value.get("id"), value.get("text"), value.get("from"), \
                    (value.get("media") or {}).get("id")
            else:
                continue
            author = author if isinstance(author, dict) else {}
            if not comment_id or not text or not author.get("id") or str(author["id"]) == account:
                continue
            stamp = value.get("created_time")
            at = _site_time(stamp) if isinstance(stamp, int | float) else None
            out.append({"channel": channel, "account_id": account, "contact_id": str(author["id"]),
                        "contact_name": str(author.get("name") or author.get("username") or "")[:80] or None,
                        "external_id": str(comment_id)[:140], "text": str(text)[:MAX_TEXT], "at": at,
                        "post_id": str(post or "")[:140] or None, "kind": "Comment"})
    return out


def buying_comment(text: str) -> bool:
    return bool(BUYING.search(text or ""))


def within_window(last_inbound: datetime | None, now: datetime, window: timedelta = WINDOW) -> bool:
    return bool(last_inbound) and now - last_inbound < window


def response_minutes(rows: list[tuple[str, datetime]]) -> list[float]:
    """Minutes from each message a lead wrote (after our last answer) to our next answer; rows sorted by time."""
    out, waiting_since = [], None
    for direction, at in rows:
        if direction == "In" and waiting_since is None:
            waiting_since = at
        elif direction == "Out" and waiting_since is not None:
            out.append(round((at - waiting_since).total_seconds() / 60, 1))
            waiting_since = None
    return out


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else round((ordered[mid - 1] + ordered[mid]) / 2, 1)


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
    """Send API body: a reply inside the 24-hour window, or the one private reply to a comment."""
    if contact_id.startswith(COMMENT):
        return {"recipient": {"comment_id": contact_id[len(COMMENT):]}, "message": {"text": text[:MAX_TEXT]}}
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
                 at=None, contact_name: str | None = None, email: str | None = None, phone: str | None = None,
                 kind: str = "Message", post_id: str | None = None) -> str | None:
    """Store an inbound chat message on the lead's thread (creating the lead when it is new); returns its name."""
    import frappe
    from frappe.utils import now_datetime

    from reckon_sales_agent.usage import log_activity

    if frappe.db.exists("Sales Chat Message", {"external_id": external_id}):
        return None  # Meta retries a webhook it thinks failed
    prospect = _prospect_for(company, channel, contact_id, contact_name, email, phone)
    first = not frappe.db.exists("Sales Chat Message", {"prospect": prospect.name})
    doc = frappe.get_doc({
        "doctype": "Sales Chat Message", "company": company, "prospect": prospect.name, "channel": channel,
        "direction": "In", "sent_at": at or now_datetime(), "contact_id": contact_id, "account_id": account_id,
        "external_id": external_id, "contact_name": contact_name or prospect.business_name, "text": text,
        "kind": kind, "post_id": post_id,
    }).insert(ignore_permissions=True)
    from reckon_sales_agent.agents.omni import conversations_campaign, member_for

    campaign = conversations_campaign(company)
    frappe.get_doc({
        "doctype": "Sales Communication Event", "company": company, "event_type": "received", "campaign": campaign,
        "member": member_for(company, campaign, prospect), "channel": channel, "event_time": doc.sent_at,
        "provider_message_id": external_id[:140], "idempotency_key": f"received:chat:{external_id}"[:140],
        "detail": text[:500],
    }).insert(ignore_permissions=True)
    from reckon_sales_agent.agents.conversations import touch_inbound

    touch_inbound(company, prospect.name, channel, doc.sent_at)
    from reckon_sales_agent.agents.inbox_events import notify_inbox
    notify_inbox(company, prospect.name)
    log_activity(company, "comment_received" if kind == "Comment" else "chat_received", prospect,
                 f"{channel}: {text[:200]}", actor_type="system",
                 agent="Conversations")
    from reckon_sales_agent.agents.lead_details import after_inbound

    after_inbound(prospect.name, text, first)  # asks a new contact for their details; never raises
    _notify(company, prospect, channel, text)
    return doc.name


def _prospect_for(company, channel, contact_id, contact_name, email, phone):
    import frappe
    from frappe.utils import now_datetime

    from reckon_sales_agent.discovery.normalize import normalize_phone

    known = frappe.db.get_value("Sales Chat Message", {"company": company, "channel": channel,
                                                       "contact_id": contact_id, "prospect": ["is", "set"]},
                                "prospect", order_by="creation desc")
    trusted = channel != "Web Chat"  # what a website visitor types is not verified
    if not known and email and trusted:
        known = frappe.db.get_value("Sales Prospect", {"company": company, "email": email, "merged_into": ["is", "not set"]})
    phone = normalize_phone(phone) if phone else None
    if not known and phone and trusted:
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


def meta_profile_name(channel: str, account: str, contact_id: str) -> str | None:
    """The name Meta shows for someone who wrote to a Page (Messenger) or an Instagram account; None when unavailable."""
    import frappe
    import requests

    try:
        token = frappe.get_doc("Sales Social Account", account).get_password("access_token", raise_exception=False)
        fields = "first_name,last_name" if channel == "Messenger" else "name,username"
        response = requests.get(f"https://graph.facebook.com/v23.0/{contact_id}",
                                params={"fields": fields, "access_token": token}, timeout=10)
        if response.status_code >= 400:
            frappe.log_error(title="Meta profile not read", message=f"{channel} {contact_id}: {response.text[:400]}")
            return None
        data = response.json() or {}
    except Exception:  # a missing name must never stop the message from being saved
        return None
    if channel == "Messenger":
        name = " ".join(part for part in (data.get("first_name"), data.get("last_name")) if part)
    else:
        name = data.get("name") or data.get("username")
    return str(name)[:140] if name else None


def _notify(company, prospect, channel, text) -> None:
    import frappe

    from reckon_sales_agent.usage import get_settings

    user = get_settings(company).get("task_assignee")
    if user:
        frappe.publish_realtime("msgprint", {"message": f"{channel} · {prospect.business_name}: {text[:140]}",
                                             "indicator": "blue", "alert": True}, user=user, after_commit=True)


def last_chat(prospect_name: str) -> dict | None:
    """The lead's latest inbound chat: {channel, at, kind, contact_id, account_id, recipient}."""
    import frappe

    row = frappe.db.get_value("Sales Chat Message", {"prospect": prospect_name, "direction": "In"},
                              ["channel", "sent_at", "contact_id", "account_id", "kind", "external_id"], as_dict=True,
                              order_by="sent_at desc")
    if not row:
        return None
    comment = row.kind == "Comment"
    return {"channel": row.channel, "at": row.sent_at, "kind": row.kind or "Message", "contact_id": row.contact_id,
            "account_id": row.account_id, "recipient": f"{COMMENT}{row.external_id}" if comment else row.contact_id}


def reachable(channel: str, prospect_name: str) -> tuple[bool, str, str | None]:
    """(reachable, reason, contact id) for a chat reply."""
    import frappe
    from frappe.utils import get_datetime, now_datetime

    row = frappe.db.get_value("Sales Chat Message", {"prospect": prospect_name, "channel": channel, "direction": "In"},
                              ["sent_at", "contact_id", "kind", "external_id"], as_dict=True, order_by="sent_at desc")
    if not row:
        return False, f"They have not written on {channel}.", None
    if row.kind == "Comment":
        recipient = f"{COMMENT}{row.external_id}"
        if frappe.db.exists("Sales Chat Message", {"contact_id": recipient, "direction": "Out"}):
            return False, "This comment already has its private reply (Meta allows one).", None
        if not within_window(get_datetime(row.sent_at), now_datetime(), COMMENT_WINDOW):
            return False, "The comment is more than 7 days old; Meta no longer allows a private reply.", None
        return True, f"Private reply to their {channel} comment.", recipient
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
    recipient = str(message.recipient or "")
    match = {"external_id": recipient[len(COMMENT):]} if recipient.startswith(COMMENT) else {"contact_id": recipient}
    inbound = frappe.db.get_value("Sales Chat Message", {"prospect": message.prospect, "channel": channel,
                                                         "direction": "In", **match},
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
    """The AI drafts the answer as soon as a lead writes (autopilot, fast answers or comment-to-chat on); it goes
    out at once only when the fast-answer policy allows, else a person approves it."""
    import frappe

    from reckon_sales_agent.agents.conversations import mode_for
    from reckon_sales_agent.usage import get_settings

    doc = frappe.get_doc("Sales Prospect", prospect)
    settings = get_settings(doc.company)
    mode = mode_for(doc.company, prospect)
    if mode == "Human only":
        return None  # a person has this conversation
    if not (settings.get("autopilot_enabled") or settings.get("chat_auto_answer") or settings.get("comment_to_chat")):
        return None
    if frappe.db.exists("Sales Outreach Message", {"prospect": prospect, "status": "Draft", "is_reply": 1}):
        return None
    from reckon_sales_agent.agents.omni import draft_reply

    try:
        return draft_reply(prospect, reason="they just wrote and are waiting for an answer",
                           allow_auto=mode == "Autopilot")
    except frappe.ValidationError:
        frappe.clear_messages()  # no AI or no written channel: the thread waits in Conversations
        return None


def remind_waiting() -> int:
    """Every few minutes: tell the salesperson about chats waiting longer than the Company's limit (once each)."""
    import frappe
    from frappe.utils import add_to_date, now_datetime

    from reckon_sales_agent.usage import get_settings

    reminded = 0
    since = add_to_date(now_datetime(), hours=-24)
    companies = frappe.get_all("Sales Chat Message", filters={"direction": "In", "sent_at": [">=", since]},
                               pluck="company", distinct=True)
    for company in companies:
        settings = get_settings(company)
        minutes = int(settings.get("chat_reply_sla_minutes") or 0)
        user = settings.get("task_assignee")
        if not minutes or not user:
            continue
        late = add_to_date(now_datetime(), minutes=-minutes)
        rows = frappe.get_all("Sales Chat Message", filters={"company": company, "direction": "In",
                                                             "sent_at": ["between", [since, late]]},
                              fields=["name", "prospect", "channel", "sent_at", "text", "contact_name"],
                              order_by="sent_at asc", limit=200)
        for row in rows:
            key = f"reckon_sales_agent:chat_reminded:{row.name}"
            if not row.prospect or frappe.cache.get_value(key):
                continue
            answered = frappe.db.exists("Sales Outreach Message", {
                "prospect": row.prospect, "is_reply": 1, "status": ["in", ["Sent", "Dry Run"]],
                "sent_on": [">=", row.sent_at]})
            newer = frappe.db.exists("Sales Chat Message", {"prospect": row.prospect, "direction": "In",
                                                            "sent_at": [">", row.sent_at]})
            frappe.cache.set_value(key, 1, expires_in_sec=26 * 3600)
            if answered or newer:
                continue  # answered, or a later message gets its own reminder
            frappe.get_doc({
                "doctype": "Notification Log", "for_user": user, "type": "Alert", "document_type": "Sales Prospect",
                "document_name": row.prospect, "from_user": "Administrator",
                "subject": f"{row.channel}: {row.contact_name or 'a lead'} has waited over {minutes} min for a reply",
                "email_content": frappe.utils.escape_html(row.text or ""),
            }).insert(ignore_permissions=True)
            reminded += 1
        frappe.db.commit()
    return reminded


def response_stats(company: str, days: int = 7) -> dict:
    """Median minutes to answer a chat, and how many chats came in, over the last ``days``."""
    import frappe
    from frappe.utils import add_days, get_datetime, nowdate

    rows = frappe.get_all("Sales Chat Message", filters={"company": company, "sent_at": [">=", add_days(nowdate(), -days)]},
                          fields=["prospect", "direction", "sent_at"], order_by="sent_at asc", limit=20000)
    by: dict[str, list] = {}
    for row in rows:
        by.setdefault(row.prospect, []).append((row.direction, get_datetime(row.sent_at)))
    minutes = [m for thread in by.values() for m in response_minutes(thread)]
    return {"chats": sum(1 for r in rows if r.direction == "In"), "median_minutes": median(minutes),
            "answered": len(minutes)}
