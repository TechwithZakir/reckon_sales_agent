"""SMS for each Company: the system provider's gateway, or the Company's own account with a Bangladeshi gateway
(BulkSMSBD, SSL Wireless) or Twilio (SMS, and RCS through a Messaging Service, with SMS fallback).

Only official HTTP APIs. Twilio also delivers the lead's replies to a signed webhook
(``X-Twilio-Signature``), which open or continue the lead's conversation; "STOP" (or বন্ধ) adds the number to the
do-not-contact list. SMS still needs recorded consent before the first message; a lead who texts us first has
given it for the reply. The request builders and the signature check are pure.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re

STOP = re.compile(r"^\s*(stop|stopall|unsubscribe|cancel|end|quit|বন্ধ)\s*$", re.I)


def bd_number(phone: str) -> str:
    """8801XXXXXXXXX: the form Bangladeshi gateways expect."""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("01") and len(digits) == 11:
        digits = "88" + digits
    return digits


def build_request(provider: str, *, to: str, text: str, key: str, sender: str, account: str = "",
                  reference: str = "", messaging_service: str = "") -> dict:
    """{method, url, data|json|params, auth} for one SMS."""
    if provider == "BulkSMSBD":
        return {"method": "POST", "url": "https://bulksmsbd.net/api/smsapi",
                "data": {"api_key": key, "type": "text", "number": bd_number(to), "senderid": sender, "message": text}}
    if provider == "SSL Wireless":
        return {"method": "POST", "url": "https://smsplus.sslwireless.com/api/v3/send-sms",
                "json": {"api_token": key, "sid": account, "msisdn": bd_number(to), "sms": text,
                         "csms_id": (reference or "rsa")[:20]}}
    if provider in ("Twilio", "Twilio (SMS and RCS)"):
        number = "+" + re.sub(r"\D", "", to) if not to.startswith("+") else to
        # A Messaging Service picks RCS where the phone supports it and falls back to SMS.
        origin = {"MessagingServiceSid": messaging_service} if messaging_service else {"From": sender}
        return {"method": "POST", "url": f"https://api.twilio.com/2010-04-01/Accounts/{account}/Messages.json",
                "data": {"To": number, **origin, "Body": text}, "auth": (account, key)}
    raise ValueError(provider)


def parse_result(provider: str, status: int, body: dict) -> tuple[bool, str]:
    """(accepted, message id or error) from the gateway's answer."""
    if provider == "BulkSMSBD":
        ok = str(body.get("response_code")) == "202"
        return ok, str(body.get("message_id") or body.get("success_message") or "") if ok else str(
            body.get("error_message") or body.get("response_code") or status)
    if provider == "SSL Wireless":
        ok = str(body.get("status")).upper() == "SUCCESS"
        info = (body.get("smsinfo") or [{}])[0] if isinstance(body.get("smsinfo"), list) else {}
        return ok, str(info.get("reference_id") or "") if ok else str(body.get("error_message") or status)
    if provider in ("Twilio", "Twilio (SMS and RCS)"):
        ok = status < 400 and bool(body.get("sid"))
        return ok, str(body.get("sid") or "") if ok else str(body.get("message") or status)
    return False, "unknown provider"


def twilio_signature(auth_token: str, url: str, params: dict) -> str:
    """Twilio's request signature: HMAC-SHA1 over the URL followed by each POST parameter name and value, sorted."""
    payload = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    return base64.b64encode(hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()).decode()


def valid_twilio(auth_token: str | None, url: str, params: dict, header: str | None) -> bool:
    if not auth_token or not header:
        return False
    return hmac.compare_digest(twilio_signature(auth_token, url, params), header)


# --------------------------------------------------------------------------- Frappe side


def send(message, settings) -> str | None:
    """Send one SMS through the Company's provider; returns the gateway's message id."""
    import requests

    from reckon_sales_agent.providers.channels import (
        SMS_MAX_CHARS,
        ChannelUnavailable,
        html_to_text,
    )

    text = html_to_text(message.body)[:SMS_MAX_CHARS]
    provider = settings.get("sms_provider") or "Platform gateway"
    secret = ""  # the provider's key or token, kept out of any error text
    if provider == "Platform gateway":
        try:
            from reckon_saas_platform.sms import is_sms_configured, send_sms
        except ImportError as exc:
            raise ChannelUnavailable("The platform SMS gateway is not installed.") from exc
        if not is_sms_configured():
            raise ChannelUnavailable("The platform SMS gateway is not configured.")
        try:
            reference = send_sms(message.recipient.lstrip("+"), text)
        except Exception as exc:
            # Live test: the gateway's account was refused (BulkSMSBD "User ID not found") and the message stayed Approved,
            # retried every ten minutes with the reason only in the Error Log. A failed send is Failed, with its reason.
            raise ChannelUnavailable("The platform SMS gateway could not send this SMS (its account may be wrong). "
                                     "Ask the platform owner to check it, or choose your own SMS provider in Integrations.") from exc
        return str(reference) if reference else None
    if provider == "Twilio (SMS and RCS)":
        from reckon_sales_agent.providers.twilio import credentials

        sid, token = credentials(settings)
        secret = token or ""
        if not settings.get("twilio_messaging_service_sid") and not settings.get("twilio_phone_number"):
            raise ChannelUnavailable("Enter a Twilio Messaging Service SID or phone number.")
        request = build_request(provider, to=message.recipient, text=text, key=token,
                                sender=settings.get("twilio_phone_number") or "", account=sid,
                                messaging_service=settings.get("twilio_messaging_service_sid") or "")
    else:
        key = settings.get_password("sms_api_key", raise_exception=False) if settings.get("sms_api_key") else ""
        if not key or not settings.get("sms_sender_id"):
            raise ChannelUnavailable(f"Enter your {provider} key and sender ID in Sales Agent Settings.")
        secret = key
        request = build_request(provider, to=message.recipient, text=text, key=key, sender=settings.sms_sender_id,
                                account=settings.get("sms_account") or "", reference=message.name)
    try:
        response = requests.request(request.pop("method"), request.pop("url"), timeout=30, **request)
    except requests.RequestException as exc:
        raise ChannelUnavailable(f"{provider} unreachable.") from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    ok, detail = parse_result(provider, response.status_code, body if isinstance(body, dict) else {})
    if not ok:
        # Live test: BulkSMSBD's refusal repeats the API key ("user id not found in this <key> key"), and the reason is
        # stored on the message and its event, so a secret must never travel with it.
        if secret:
            detail = detail.replace(secret, "***")
        raise ChannelUnavailable(f"{provider} refused the SMS: {detail[:200]}")
    return detail or None


def receive(company: str, sender: str, text: str, message_id: str) -> str | None:
    """A lead texted us (Twilio): STOP suppresses the number; anything else continues the conversation."""
    import frappe

    from reckon_sales_agent.agents.chat import receive_chat
    from reckon_sales_agent.campaigns.suppression import suppress
    from reckon_sales_agent.discovery.normalize import normalize_phone

    phone = normalize_phone(sender) or sender
    if STOP.match(text or ""):
        suppress(company, "Phone", phone, "Unsubscribed", "SMS STOP")
        for name in frappe.get_all("Sales Prospect", filters={"company": company, "normalized_phone": phone},
                                   pluck="name"):
            frappe.db.set_value("Sales Prospect", name, "do_not_contact", 1, update_modified=False)
        return None
    name = receive_chat(company, "SMS", "sms", phone, text, f"sms:{message_id}"[:140], phone=phone)
    prospect = frappe.db.get_value("Sales Chat Message", name, "prospect") if name else None
    if prospect:
        # Texting us is consent to an SMS answer.
        frappe.db.set_value("Sales Prospect", prospect, "sms_consent", 1, update_modified=False)
        if not frappe.db.get_value("Sales Prospect", prospect, "consent_source"):
            frappe.db.set_value("Sales Prospect", prospect, "consent_source", "Texted us", update_modified=False)
    return name
