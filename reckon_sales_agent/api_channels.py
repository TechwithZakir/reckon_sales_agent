"""Channels: the Meta webhook (Messenger, Instagram), the website chat's public endpoints, social sign-in, and the
Channels page where a Company connects them."""

from __future__ import annotations

import hmac
import json
import re

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from werkzeug.wrappers import Response

from reckon_sales_agent.tenant import current_company, get_tenant_doc
from reckon_sales_agent.usage import get_settings, platform_settings

VISITOR = re.compile(r"^[A-Za-z0-9]{24,40}$")


def _require_manager() -> None:
    from reckon_sales_agent.api_studio import _can_manage

    if not _can_manage():
        frappe.throw(_("Ask a Sales Agent admin or manager to do this."), frappe.PermissionError)


# --------------------------------------------------------------------------- Meta webhook


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def meta_webhook(**kwargs):
    """Meta's webhook: GET answers the subscription check; POST carries messages, signed with the app secret."""
    platform = platform_settings()
    if frappe.request.method == "GET":
        token = platform.get_password("meta_verify_token", raise_exception=False) if platform.get("meta_verify_token") else ""
        offered = str(frappe.form_dict.get("hub.verify_token") or "")
        if token and frappe.form_dict.get("hub.mode") == "subscribe" and hmac.compare_digest(offered, token):
            return Response(str(frappe.form_dict.get("hub.challenge") or ""), mimetype="text/plain")
        return Response("forbidden", status=403, mimetype="text/plain")
    from reckon_sales_agent.agents.chat import (
        account_company,
        meta_events,
        receive_chat,
        verify_meta_signature,
    )

    body = frappe.request.get_data() or b""
    secret = platform.get_password("meta_app_secret", raise_exception=False) if platform.get("meta_app_secret") else ""
    if not verify_meta_signature(secret, body, frappe.get_request_header("X-Hub-Signature-256")):
        return Response("invalid signature", status=401, mimetype="text/plain")
    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        return Response("invalid JSON", status=400, mimetype="text/plain")
    frappe.set_user("Administrator")  # a verified Meta event: act as the system
    from reckon_sales_agent.agents.chat import buying_comment, meta_comments
    from reckon_sales_agent.leads_bridge import leadgen_events

    for lead in leadgen_events(payload)[:50]:
        frappe.enqueue("reckon_sales_agent.leads_bridge.receive_meta_lead", queue="short", job_id=f"leadgen:{lead['leadgen_id']}",
                       deduplicate=True, page_id=lead["page_id"], leadgen_id=lead["leadgen_id"], form_id=lead["form_id"])
    comments = [c for c in meta_comments(payload) if buying_comment(c["text"])]
    for event in (meta_events(payload) + comments)[:100]:
        owner = account_company(event["channel"], event["account_id"])
        if not owner:
            continue  # a Page no Company has connected (or it switched messages off)
        if event.get("kind") == "Comment" and not get_settings(owner[0]).get("comment_to_chat"):
            continue
        try:
            name = receive_chat(owner[0], event["channel"], event["account_id"], event["contact_id"], event["text"],
                                event["external_id"], event["at"], contact_name=event.get("contact_name"),
                                kind=event.get("kind") or "Message", post_id=event.get("post_id"))
            frappe.db.commit()
            if name:
                _queue_draft(name)
        except Exception:
            frappe.db.rollback()
            frappe.log_error(title="Sales Agent chat message failed")
    return Response("EVENT_RECEIVED", mimetype="text/plain")  # Meta retries anything but a quick 200


def _queue_draft(chat_message: str) -> None:
    prospect = frappe.db.get_value("Sales Chat Message", chat_message, "prospect")
    if prospect:
        frappe.enqueue("reckon_sales_agent.agents.chat.auto_draft", queue="short", prospect=prospect,
                       job_id=f"chat-draft:{prospect}", deduplicate=True)


# --------------------------------------------------------------------------- website chat (public)


def _json(data: dict, status: int = 200, origin: str | None = None) -> Response:
    response = Response(json.dumps(data, default=str), status=status, mimetype="application/json")
    if origin:
        # The widget runs on the Company's own website; it never sends cookies (credentials: "omit").
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    return response


def _chat_company(key: str | None) -> tuple[str | None, object | None]:
    if not key or not re.fullmatch(r"[A-Za-z0-9]{16,40}", key):
        return None, None
    company = frappe.db.get_value("Sales Agent Settings", {"webchat_key": key, "webchat_enabled": 1}, "name")
    return (company, get_settings(company)) if company else (None, None)


def _visitor_messages(company: str, visitor: str) -> list[dict]:
    rows = frappe.get_all("Sales Chat Message", filters={"company": company, "channel": "Web Chat",
                                                         "contact_id": visitor},
                          fields=["direction", "text", "sent_at"], order_by="sent_at asc", limit=60)
    return [{"from": "you" if r.direction == "In" else "us", "text": r.text, "at": r.sent_at} for r in rows]


@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=120, seconds=60)
def webchat_messages(key: str | None = None, visitor: str | None = None):
    """The widget's settings and, for a returning visitor, their conversation."""
    from reckon_sales_agent.agents.chat import origin_allowed

    origin = frappe.get_request_header("Origin")
    company, settings = _chat_company(key)
    if not company or not origin_allowed(origin, settings.get("webchat_allowed_origins")):
        return _json({"ok": False}, 404, origin)
    messages = _visitor_messages(company, visitor) if visitor and VISITOR.match(visitor) else []
    return _json({"ok": True, "title": settings.get("webchat_title") or _("Chat with us"),
                  "welcome": settings.get("webchat_welcome") or "", "messages": messages}, origin=origin)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=20, seconds=300)
def webchat_send():
    """A website visitor's message. Sent as text/plain JSON so browsers make no pre-flight request."""
    from reckon_sales_agent.agents.chat import origin_allowed, receive_chat, visitor_fields

    origin = frappe.get_request_header("Origin")
    try:
        data = json.loads(frappe.request.get_data() or b"{}")
    except ValueError:
        return _json({"ok": False, "error": _("Invalid message.")}, 400, origin)
    company, settings = _chat_company(str(data.get("key") or ""))
    if not company or not origin_allowed(origin, settings.get("webchat_allowed_origins")):
        return _json({"ok": False}, 404, origin)
    fields, error = visitor_fields(data)
    if error:
        return _json({"ok": False, "error": _(error)}, 400, origin)
    visitor = str(data.get("visitor") or "")
    if not VISITOR.match(visitor):
        visitor = frappe.generate_hash(length=32)
    frappe.set_user("Administrator")  # a public visitor: the system records it for the Company
    name = receive_chat(company, "Web Chat", "web", visitor, fields["text"],
                        f"web:{visitor}:{frappe.generate_hash(length=12)}",
                        contact_name=fields["name"] or None, email=fields["email"] or None, phone=fields["phone"] or None)
    frappe.db.commit()
    if name:
        _queue_draft(name)
    return _json({"ok": True, "visitor": visitor, "messages": _visitor_messages(company, visitor)}, origin=origin)


# --------------------------------------------------------------------------- social sign-in


@frappe.whitelist()
def social_connect(provider: str) -> str:
    """The URL that starts Facebook / LinkedIn sign-in for this Company."""
    from reckon_sales_agent.agents.social_connect import PROVIDERS, start

    _require_manager()
    if provider not in PROVIDERS:
        frappe.throw(_("Unknown provider."))
    return start(current_company(), frappe.session.user, provider)


@frappe.whitelist(methods=["GET"])
def social_callback(code: str | None = None, state: str | None = None, error: str | None = None, **kwargs):
    """Where Facebook / LinkedIn send the person back after they approve access."""
    from urllib.parse import quote

    from reckon_sales_agent.agents.social_connect import finish

    if error or not code:
        message = kwargs.get("error_description") or error or "cancelled"
        return _redirect(f"/desk/sales-channels?connect_error={quote(str(message)[:200])}")
    try:
        _company, saved = finish(state or "", code, frappe.session.user)
    except frappe.ValidationError as exc:
        frappe.db.rollback()
        return _redirect(f"/desk/sales-channels?connect_error={quote(str(exc)[:200])}")
    frappe.db.commit()
    return _redirect(f"/desk/sales-channels?connected={len(saved)}")


def _redirect(location: str) -> Response:
    return Response("", status=302, headers={"Location": location})


# --------------------------------------------------------------------------- the Channels page


@frappe.whitelist()
def overview() -> dict:
    from reckon_sales_agent.api_studio import _can_manage

    company = current_company()
    settings = get_settings(company)
    platform = platform_settings()
    accounts = frappe.get_all("Sales Social Account", filters={"company": company},
                              fields=["name", "platform", "account_name", "enabled", "receive_messages",
                                      "token_expires_on", "last_check", "last_error", "connected_by"],
                              order_by="platform asc, account_name asc")
    count = lambda channel: frappe.db.count("Sales Chat Message", {"company": company, "channel": channel,  # noqa: E731
                                                                   "direction": "In"})
    from reckon_sales_agent.providers.factory import ai_setup

    ai = ai_setup(company)
    vendor = _is_vendor()
    return {
        "company": company,
        "is_vendor": vendor,
        "references": _references(),
        "quick_help": _quick_help(),
        # Vendors only: the platform's own values (secrets say whether they are set) and every Company to switch to.
        "platform": _platform_values(platform) if vendor else None,
        "companies": frappe.get_all("Sales Agent Settings", pluck="name", order_by="name asc") if vendor else [],
        "values": _values(settings),
        "ai": {"on": bool(platform.get("ai_enabled") and settings.get("ai_enabled")), "label": ai["label"],
               "model": ai["model"], "error": ai["error"]},
        "phone": {"provider": settings.get("telephony_provider") or "Phone (tap to call)",
                  "asterisk": bool(settings.get("ari_url"))},
        "can_manage": _can_manage(),
        "accounts": accounts,
        "meta_ready": bool(platform.get("meta_app_id") and platform.get("meta_app_secret")),
        "linkedin_ready": bool(platform.get("linkedin_client_id") and platform.get("linkedin_client_secret")),
        "whatsapp": {"installed": "frappe_whatsapp" in frappe.get_installed_apps(),
                     "enabled": bool(settings.get("whatsapp_enabled")), "account": settings.get("whatsapp_account") or "",
                     "accounts": _wa_accounts(company), "webhook": frappe.utils.get_url("/api/method/frappe_whatsapp.utils.webhook.webhook")},
        "email": {"account": frappe.db.get_value("Email Account", {"enable_outgoing": 1, "default_outgoing": 1},
                                                 "email_id")},
        "webchat": {"enabled": bool(settings.get("webchat_enabled")), "key": settings.get("webchat_key") or "",
                    "title": settings.get("webchat_title") or "", "welcome": settings.get("webchat_welcome") or "",
                    "origins": settings.get("webchat_allowed_origins") or "",
                    "script": frappe.utils.get_url("/assets/reckon_sales_agent/js/reckon_webchat.js"),
                    "site": frappe.utils.get_url()},
        "counts": {c: count(c) for c in ("Messenger", "Instagram", "Web Chat")},
        "twilio": {"ready": bool(settings.get("twilio_account_sid") and settings.get("twilio_auth_token")),
                   "phone": settings.get("twilio_phone_number") or "",
                   "messaging_service": bool(settings.get("twilio_messaging_service_sid")),
                   "voice_ai": bool(settings.get("voice_ai_enabled")), "calls": settings.get("telephony_provider") == "Twilio",
                   "sms": settings.get("sms_provider") == "Twilio (SMS and RCS)",
                   "email": settings.get("email_provider") == "Twilio SendGrid",
                   "urls": {k: _twilio_url(k, company) for k in ("voice", "sms", "sendgrid_events")}},
        "sms": {"enabled": bool(settings.get("sms_enabled")), "provider": settings.get("sms_provider") or "Platform gateway",
                "configured": bool(settings.get("sms_api_key") or settings.get("sms_provider") in (
                    None, "", "Platform gateway", "Twilio (SMS and RCS)"))},
        "vendor": _vendor_setup(platform) if _is_vendor() else None,
        "fast": {"auto_answer": bool(settings.get("chat_auto_answer")),
                 "whatsapp": bool(settings.get("autopilot_whatsapp")),
                 "agents": settings.get("chat_agents") or "", "auto_assign": bool(settings.get("auto_assign", 1)),
                 "call_routing": settings.get("call_routing") or "One salesperson",
                 "sla_minutes": settings.get("chat_reply_sla_minutes") or 0,
                 "comment_to_chat": bool(settings.get("comment_to_chat")),
                 "assignee": settings.get("task_assignee") or ""},
        "outbound_enabled": bool(settings.outbound_enabled),
    }


@frappe.whitelist(methods=["POST"])
def set_webchat(data: str | dict) -> dict:
    _require_manager()
    data = json.loads(data) if isinstance(data, str) else data
    company = current_company()
    doc = get_tenant_doc("Sales Agent Settings", company, "write")
    doc.webchat_enabled = 1 if data.get("enabled") else 0
    if doc.webchat_enabled and not doc.get("webchat_key"):
        doc.webchat_key = frappe.generate_hash(length=24)
    for field, key, limit in (("webchat_title", "title", 80), ("webchat_welcome", "welcome", 500),
                              ("webchat_allowed_origins", "origins", 1000)):
        if key in data:
            setattr(doc, field, str(data.get(key) or "")[:limit])
    doc.save()
    return overview()


@frappe.whitelist(methods=["POST"])
def set_fast_answers(data: str | dict) -> dict:
    _require_manager()
    data = json.loads(data) if isinstance(data, str) else data
    doc = get_tenant_doc("Sales Agent Settings", current_company(), "write")
    doc.chat_auto_answer = 1 if data.get("auto_answer") else 0
    doc.comment_to_chat = 1 if data.get("comment_to_chat") else 0
    doc.chat_reply_sla_minutes = max(0, min(int(data.get("sla_minutes") or 0), 1440))
    if "agents" in data:
        from reckon_sales_agent.agents.conversations import parse_agents

        doc.chat_agents = "\n".join(parse_agents(str(data.get("agents") or "")))
    if "auto_assign" in data:
        doc.auto_assign = 1 if data.get("auto_assign") else 0
    if "whatsapp" in data:
        doc.autopilot_whatsapp = 1 if data.get("whatsapp") else 0
    if data.get("call_routing") in ("One salesperson", "Share across the team"):
        doc.call_routing = data["call_routing"]
    doc.save()
    from reckon_sales_agent.usage import log_activity

    log_activity(doc.company, "fast_answers_set", doc, f"instant answers {'on' if doc.chat_auto_answer else 'off'}, "
                 f"comment to chat {'on' if doc.comment_to_chat else 'off'}, remind after "
                 f"{doc.chat_reply_sla_minutes} min", agent="Conversations")
    return overview()


@frappe.whitelist(methods=["POST"])
def set_account(account: str, enabled: int | None = None, receive_messages: int | None = None) -> dict:
    _require_manager()
    doc = get_tenant_doc("Sales Social Account", account, "write")
    if enabled is not None:
        doc.enabled = 1 if int(enabled) else 0
    if receive_messages is not None:
        doc.receive_messages = 1 if int(receive_messages) else 0
    doc.save()
    return overview()


@frappe.whitelist(methods=["POST"])
def check_account(account: str) -> dict:
    from reckon_sales_agent.agents.social_agent import check_account as check

    _require_manager()
    doc = get_tenant_doc("Sales Social Account", account, "write")
    try:
        check(doc)
    except frappe.ValidationError:
        frappe.clear_messages()
    frappe.db.commit()
    return overview()


def _twilio_url(kind: str, company: str) -> str:
    from reckon_sales_agent.providers.twilio import webhook_url

    return webhook_url(kind, company)


def _is_vendor() -> bool:
    from reckon_sales_agent.constants import VENDOR_ROLES

    return bool(set(frappe.get_roles()) & set(VENDOR_ROLES))


def _vendor_setup(platform) -> dict:
    """The system provider's one-time checklist, with the exact addresses to paste into Meta and LinkedIn."""
    from frappe.utils import get_url

    from reckon_sales_agent.agents.social_connect import redirect_uri

    return {
        "redirect_uri": redirect_uri(),
        "meta_webhook": get_url("/api/method/reckon_sales_agent.api_channels.meta_webhook"),
        "checks": [
            {"label": _("Meta app ID and secret"), "ok": bool(platform.get("meta_app_id") and platform.get("meta_app_secret"))},
            {"label": _("Meta webhook verify token"), "ok": bool(platform.get("meta_verify_token"))},
            {"label": _("LinkedIn client ID and secret"),
             "ok": bool(platform.get("linkedin_client_id") and platform.get("linkedin_client_secret"))},
            {"label": _("Default AI provider"), "ok": bool(platform.get("ai_enabled"))},
            {"label": _("Call transcription"), "ok": bool(platform.get("transcription_enabled"))},
        ],
    }


@frappe.whitelist(methods=["POST"])
def new_verify_token() -> str:
    """System provider only: a fresh Meta webhook verify token, shown once to paste into the Meta app."""
    if not _is_vendor():
        frappe.throw(_("Only the system provider can do this."), frappe.PermissionError)
    token = frappe.generate_hash(length=32)
    doc = frappe.get_doc("Sales Agent Platform Settings")
    doc.meta_verify_token = token
    doc.save(ignore_permissions=True)
    return token


# Settings a Company manages from the integration panels (secrets are write-only).
EDITABLE = {
    "sms_enabled": "check", "sms_provider": "text", "sms_api_key": "secret", "sms_account": "text",
    "sms_sender_id": "text", "whatsapp_enabled": "check",
    "telephony_provider": "text", "calling_hours": "text", "ari_url": "text", "ari_username": "text",
    "ari_password": "secret", "sip_context": "text", "sip_caller_id": "text", "telephony_webhook_secret": "secret",
    "whatsapp_account": "text",
    "twilio_account_sid": "text", "twilio_auth_token": "secret", "twilio_phone_number": "text",
    "twilio_messaging_service_sid": "text", "twilio_record_calls": "check", "voice_ai_enabled": "check",
    "voice_ai_greeting": "text", "voice_ai_language": "text", "voice_forward_to": "text",
    "email_provider": "text", "sendgrid_api_key": "secret", "sendgrid_from_email": "text",
    "sendgrid_webhook_key": "text",
}


def _values(settings) -> dict:
    """Current values for the panels; a secret only says whether it is set."""
    return {field: bool(settings.get(field)) if kind == "secret" else settings.get(field)
            for field, kind in EDITABLE.items()}


@frappe.whitelist(methods=["POST"])
def save_settings(data: str | dict) -> dict:
    """Save an integration panel. Only the listed fields; an empty secret keeps the stored one."""
    _require_manager()
    data = json.loads(data) if isinstance(data, str) else data
    doc = get_tenant_doc("Sales Agent Settings", current_company(), "write")
    for field, value in (data or {}).items():
        kind = EDITABLE.get(field)
        if not kind or (kind == "secret" and not str(value or "").strip()):
            continue
        if kind == "check":
            value = 1 if value in (1, "1", True, "true") else 0
        elif doc.meta.get_field(field) and doc.meta.get_field(field).fieldtype == "Select":
            options = (doc.meta.get_field(field).options or "").splitlines()
            if str(value) not in options:
                frappe.throw(_("{0} is not an option for {1}.").format(value, doc.meta.get_label(field)))
        doc.set(field, str(value).strip()[:2000] if kind != "check" else value)
    doc.save()
    return overview()


# The system provider's settings (Sales Agent Platform Settings): shown and saved only to vendor roles.
PLATFORM_EDITABLE = {
    "ai_enabled": "check", "ai_provider": "text", "ai_model": "text", "ai_effort": "text",
    "anthropic_api_key": "secret", "openai_api_key": "secret", "openai_model": "text", "openai_base_url": "text",
    "local_ai_base_url": "text", "local_ai_model": "text", "local_ai_api_key": "secret",
    "allow_company_ai_override": "check", "allow_company_ai_endpoints": "check",
    "meta_app_id": "text", "meta_app_secret": "secret", "meta_verify_token": "secret",
    "linkedin_client_id": "text", "linkedin_client_secret": "secret",
    "transcription_enabled": "check", "transcription_provider": "text", "transcription_model": "text",
    # Lead sources: Brave, Google Places, Google Maps and Search providers, and how leads are routed between them.
    "brave_enabled": "check", "brave_api_key": "secret", "brave_country": "text",
    "places_enabled": "check", "google_places_api_key": "secret", "places_terms_reviewed": "check",
    "places_retention_days": "text",
    "maps_terms_ack": "check", "maps_data_retention_days": "text",
    "serpapi_enabled": "check", "serpapi_api_key": "secret",
    "apify_enabled": "check", "apify_api_token": "secret", "apify_actor": "text",
    "scrapingdog_enabled": "check", "scrapingdog_api_key": "secret",
    "scrapingbee_enabled": "check", "scrapingbee_api_key": "secret",
    "search_terms_ack": "check", "search_data_retention_days": "text", "search_country": "text",
    "search_language": "text", "search_serpapi_enabled": "check", "search_scrapingdog_enabled": "check",
    "search_scrapingbee_enabled": "check",
    "default_places_provider": "text", "default_page_context_provider": "text", "default_web_search_provider": "text",
    # Experimental headless browsers (Playwright): off unless the vendor turns them on.
    "maps_browser_enabled": "check", "maps_browser_max_results": "text", "maps_browser_delay": "text",
    "maps_browser_language": "text", "search_browser_enabled": "check", "search_browser_max_results": "text",
    "search_browser_delay": "text",
    # Website research, social publishing, email events, plans and limits.
    "research_enabled": "check", "user_agent": "text", "fetch_timeout": "text", "max_page_kb": "text",
    "max_pages_per_site": "text", "market_research_max_requests": "text",
    "social_enabled": "check", "meta_graph_version": "text", "linkedin_api_version": "text",
    "email_webhook_secret": "secret",
    "monthly_discovery_limit": "text", "monthly_research_limit": "text", "monthly_ai_limit": "text",
    "monthly_message_limit": "text", "internal_companies": "text",
}


def _platform_values(platform) -> dict:
    return {field: bool(platform.get(field)) if kind == "secret" else platform.get(field)
            for field, kind in PLATFORM_EDITABLE.items()}


@frappe.whitelist(methods=["POST"])
def save_platform_settings(data: str | dict) -> dict:
    """Save the system provider's settings. Vendor roles only, checked here on the server."""
    if not _is_vendor():
        frappe.throw(_("Only the system provider can change these settings."), frappe.PermissionError)
    data = json.loads(data) if isinstance(data, str) else data
    doc = frappe.get_doc("Sales Agent Platform Settings")
    for field, value in (data or {}).items():
        kind = PLATFORM_EDITABLE.get(field)
        if not kind or (kind == "secret" and not str(value or "").strip()):
            continue  # an empty secret keeps the stored one
        if kind == "check":
            value = 1 if value in (1, "1", True, "true") else 0
        else:
            value = str(value).strip()[:2000]
        doc.set(field, value)
    doc.save()
    return overview()


def _wa_accounts(company: str) -> list[dict]:
    """The WhatsApp accounts on this site that no other Company has taken."""
    if "frappe_whatsapp" not in frappe.get_installed_apps() or not frappe.db.exists("DocType", "WhatsApp Account"):
        return []
    taken = frappe.get_all("Sales Agent Settings", filters={"whatsapp_account": ["is", "set"], "name": ["!=", company]},
                           pluck="whatsapp_account")
    return frappe.get_all("WhatsApp Account", filters={"name": ["not in", taken or [""]]},
                          fields=["name", "account_name", "status"], order_by="name asc", limit=50)


def _quick_help() -> dict:
    from reckon_sales_agent.agents.channel_guide import CONFIG, QUICK_HELP

    return {key: {**help_, "details": CONFIG.get(key, [])} for key, help_ in QUICK_HELP.items()}


def _references() -> dict:
    from reckon_sales_agent.agents.channel_guide import REFERENCES

    return REFERENCES


@frappe.whitelist()
def guide(key: str, refresh: int = 0) -> dict:
    """AI-guided setup help for one integration. Platform integrations are for the system provider only."""
    from reckon_sales_agent.agents.channel_guide import PLATFORM_KEYS, build_guide

    if key in PLATFORM_KEYS and not _is_vendor():
        frappe.throw(_("Only the system provider can open this guide."), frappe.PermissionError)
    return build_guide(current_company(), key, bool(int(refresh or 0)))

