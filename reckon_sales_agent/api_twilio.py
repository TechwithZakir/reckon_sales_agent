"""Twilio webhooks for each Company (``?company=``): incoming calls and the AI voice assistant, call status,
recordings, incoming SMS/RCS, and SendGrid email events. Every call is checked against the Company's Twilio auth
token (``X-Twilio-Signature``) or SendGrid's signed-webhook key before anything is read."""

from __future__ import annotations

import json

import frappe
from frappe.utils import get_url
from werkzeug.wrappers import Response

from reckon_sales_agent.usage import get_settings

XML = "text/xml"


def _company_settings(company: str | None):
    if not company or not frappe.db.exists("Sales Agent Settings", company):
        return None
    return get_settings(company)


def _verified(settings) -> bool:
    """Twilio signed this request with the Company's auth token (URL as Twilio called it, plus the POST form)."""
    from reckon_sales_agent.providers.sms import valid_twilio

    token = settings.get_password("twilio_auth_token", raise_exception=False) if settings.get("twilio_auth_token") else ""
    url = get_url(frappe.request.full_path.rstrip("?"))
    return valid_twilio(token, url, dict(frappe.request.form.items()), frappe.get_request_header("X-Twilio-Signature"))


def _deny() -> Response:
    return Response("forbidden", status=403, mimetype="text/plain")


@frappe.whitelist(allow_guest=True, methods=["POST"])
def voice(company: str | None = None, **kwargs):
    """An incoming call to the Company's Twilio number: the AI assistant greets, or the call goes to a person."""
    from reckon_sales_agent.providers.twilio import dial, gather, say, twiml, webhook_url

    settings = _company_settings(company)
    if not settings or not _verified(settings):
        return _deny()
    language = settings.get("voice_ai_language") or "en-US"
    if settings.get("voice_ai_enabled"):
        greeting = settings.get("voice_ai_greeting") or "Hello, I am an AI assistant. How can I help?"
        body = twiml(gather(greeting, webhook_url("voice_turn", company), language),
                     say("Sorry, I did not hear anything. Goodbye.", language))
    elif settings.get("voice_forward_to"):
        body = twiml(dial(settings.voice_forward_to, settings.get("twilio_phone_number")))
    else:
        body = twiml(say("Thank you for calling. Please call again later.", language))
    return Response(body, mimetype=XML)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def voice_turn(company: str | None = None, **kwargs):
    """What the caller said: the assistant answers from approved knowledge, or connects a person."""
    from reckon_sales_agent.providers.twilio import gather, twiml, voice_answer, webhook_url

    settings = _company_settings(company)
    if not settings or not _verified(settings):
        return _deny()
    form = frappe.request.form
    speech = (form.get("SpeechResult") or "").strip()
    language = settings.get("voice_ai_language") or "en-US"
    if not speech:
        return Response(twiml(gather("Sorry, could you say that again?", webhook_url("voice_turn", company), language)),
                        mimetype=XML)
    frappe.set_user("Administrator")  # a verified Twilio call: the system answers for the Company
    verbs, _outcome = voice_answer(company, form.get("From") or "", form.get("CallSid") or "", speech)
    frappe.db.commit()
    return Response(twiml(verbs), mimetype=XML)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def call_status(company: str | None = None, **kwargs):
    from reckon_sales_agent.providers.twilio import apply_status

    settings = _company_settings(company)
    if not settings or not _verified(settings):
        return _deny()
    frappe.set_user("Administrator")
    apply_status(company, dict(frappe.request.form.items()))
    frappe.db.commit()
    return Response("", status=204)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def recording(company: str | None = None, **kwargs):
    from reckon_sales_agent.providers.twilio import apply_recording

    settings = _company_settings(company)
    if not settings or not _verified(settings):
        return _deny()
    frappe.set_user("Administrator")
    apply_recording(company, dict(frappe.request.form.items()))
    frappe.db.commit()
    return Response("", status=204)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def sms(company: str | None = None, **kwargs):
    """An incoming SMS or RCS message to the Company's Twilio number or Messaging Service."""
    from reckon_sales_agent.providers.sms import receive
    from reckon_sales_agent.providers.twilio import twiml

    settings = _company_settings(company)
    if not settings or not _verified(settings):
        return _deny()
    form = frappe.request.form
    frappe.set_user("Administrator")
    name = receive(company, form.get("From") or "", (form.get("Body") or "")[:2000], form.get("MessageSid") or "")
    frappe.db.commit()
    if name:
        from reckon_sales_agent.api_channels import _queue_draft

        _queue_draft(name)
    return Response(twiml(), mimetype=XML)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def sendgrid_events(company: str | None = None, **kwargs):
    """SendGrid's signed event webhook: bounces and spam reports reach the do-not-contact list."""
    from reckon_sales_agent.agents.engagement import normalize_email_events
    from reckon_sales_agent.agents.engagement_agent import apply_email_event
    from reckon_sales_agent.providers.twilio import sendgrid_events as to_events
    from reckon_sales_agent.providers.twilio import verify_sendgrid

    settings = _company_settings(company)
    body = frappe.request.get_data() or b""
    if not settings or not verify_sendgrid(settings.get("sendgrid_webhook_key"),
                                           frappe.get_request_header("X-Twilio-Email-Event-Webhook-Signature"),
                                           frappe.get_request_header("X-Twilio-Email-Event-Webhook-Timestamp"), body):
        return _deny()
    try:
        events = json.loads(body or b"[]")
    except ValueError:
        return Response("invalid JSON", status=400, mimetype="text/plain")
    frappe.set_user("Administrator")
    handled = 0
    for event in normalize_email_events(to_events(events))[:1000]:
        try:
            handled += 1 if apply_email_event(event) else 0
            frappe.db.commit()
        except Exception:
            frappe.db.rollback()
            frappe.log_error(title="Sales Agent SendGrid event failed")
    return Response(json.dumps({"ok": True, "handled": handled}), mimetype="application/json")
