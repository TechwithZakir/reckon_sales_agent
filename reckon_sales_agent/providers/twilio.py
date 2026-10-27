"""Twilio for each Company: phone calls, an AI voice assistant, SMS/RCS (see ``providers/sms.py``) and email through
Twilio SendGrid. Only Twilio's documented REST APIs, TwiML and signed webhooks.

- **Calls**: click-to-call rings the salesperson's own phone first, then connects the lead from the Company's
  Twilio number (calling hours enforced). Status and recordings come back to signed webhooks and land on Frappe
  CRM's Call Log; recordings are transcribed and summarised (Voice agent).
- **AI voice assistant** (opt-in): on an incoming call it says it is an AI assistant, listens (Twilio speech
  recognition), and answers from the Company's approved knowledge only. When it may not answer (prices it cannot
  find, discounts, complaints, anything unsure) or the caller asks for a person, it connects the call to the
  Company's number for people. Every turn is written to the caller's conversation. Plain HTTP request/response
  (``<Gather input="speech">``), no extra servers.
- **Email**: SendGrid's v3 Mail Send API, with the outreach message's name in ``custom_args`` so signed event
  webhooks (bounces, spam reports) find it again.

TwiML builders, status mapping and payload builders are pure.
"""

from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr

API = "https://api.twilio.com/2010-04-01"
# Twilio CallStatus -> Frappe CRM Call Log status.
STATUS = {"queued": "Initiated", "initiated": "Initiated", "ringing": "Ringing", "in-progress": "In Progress",
          "answered": "In Progress", "completed": "Completed", "busy": "Busy", "no-answer": "No Answer",
          "failed": "Failed", "canceled": "No Answer"}
MAX_TURNS = 6
VOICE_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}, "grounded": {"type": "boolean"},
                   "needs_person": {"type": "boolean"}, "caller_done": {"type": "boolean"}},
    "required": ["answer", "grounded", "needs_person", "caller_done"], "additionalProperties": False,
}
VOICE_SYSTEM = (
    "You are the AI phone assistant of a B2B seller in Bangladesh. Answer the caller's question in one to three "
    "short spoken sentences, using ONLY the approved knowledge; no prices, discounts, dates or promises that are not "
    "in it. Speak naturally, no lists or symbols. grounded: true only if every fact you said is in the knowledge. "
    "needs_person: true if they want a person, a discount, a custom price, to order, to complain, or anything the "
    "knowledge does not answer. caller_done: true if they said goodbye or have nothing more to ask.")


def call_status(raw: str | None) -> str:
    return STATUS.get(str(raw or "").lower(), "Completed")


def twiml(*verbs: str) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?><Response>' + "".join(verbs) + "</Response>"


def say(text: str, language: str = "en-US") -> str:
    return f"<Say language={quoteattr(language)}>{escape(text[:1000])}</Say>"


def gather(prompt: str, action: str, language: str = "en-US") -> str:
    """Speak, then listen for the caller's answer and post it to ``action``."""
    return (f"<Gather input=\"speech\" action={quoteattr(action)} method=\"POST\" language={quoteattr(language)} "
            f"speechTimeout=\"auto\" timeout=\"6\">{say(prompt, language)}</Gather>")


def dial(number: str, caller_id: str | None = None, record: bool = False, recording_callback: str | None = None) -> str:
    attrs = f" callerId={quoteattr(caller_id)}" if caller_id else ""
    if record:
        attrs += ' record="record-from-answer-dual"'
        if recording_callback:
            attrs += f" recordingStatusCallback={quoteattr(recording_callback)}"
    return f"<Dial{attrs}><Number>{escape(number)}</Number></Dial>"


def click_to_call_params(agent_phone: str, lead_phone: str, from_number: str, business: str, status_url: str,
                         record: bool, recording_url: str) -> dict:
    """POST /Calls body: ring the salesperson, then connect the lead."""
    return {"To": agent_phone, "From": from_number,
            "Twiml": twiml(say(f"Connecting you to {business}."), dial(lead_phone, from_number, record, recording_url)),
            "StatusCallback": status_url, "StatusCallbackEvent": "initiated ringing answered completed"}


def sendgrid_payload(to: str, from_email: str, from_name: str, subject: str, html: str, message: str) -> dict:
    return {"personalizations": [{"to": [{"email": to}], "custom_args": {"message": message}}],
            "from": {"email": from_email, "name": from_name}, "subject": subject,
            "content": [{"type": "text/html", "value": html}]}


def sendgrid_events(events: list[dict]) -> list[dict]:
    """SendGrid event webhook items in the shape ``engagement.normalize_email_events`` reads."""
    kinds = {"delivered": "delivered", "bounce": "bounce", "dropped": "bounce", "spamreport": "spamreport"}
    out = []
    for item in events if isinstance(events, list) else []:
        kind = kinds.get(str(item.get("event") or ""))
        if not kind or not item.get("sg_event_id"):
            continue
        hard = not (item.get("event") == "bounce" and str(item.get("type") or "") == "blocked")
        out.append({"id": f"sg:{item['sg_event_id']}", "type": kind, "bounce_type": "hard" if hard else "soft",
                    "email": item.get("email"), "message": item.get("message") or ""})
    return out


def verify_sendgrid(public_key_b64: str | None, signature_b64: str | None, timestamp: str | None, body: bytes) -> bool:
    """SendGrid's signed event webhook: ECDSA (P-256, SHA-256) over timestamp + raw body."""
    if not public_key_b64 or not signature_b64 or not timestamp:
        return False
    import base64

    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    try:
        key = serialization.load_der_public_key(base64.b64decode(public_key_b64.strip()))
        key.verify(base64.b64decode(signature_b64), timestamp.encode() + body, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- Frappe side


def credentials(settings) -> tuple[str, str]:
    import frappe
    from frappe import _

    sid = settings.get("twilio_account_sid") or ""
    token = settings.get_password("twilio_auth_token", raise_exception=False) if settings.get("twilio_auth_token") else ""
    if not sid or not token:
        frappe.throw(_("Enter the Twilio Account SID and auth token in Sales Agent Settings → Twilio."))
    return sid, token


def webhook_url(method: str, company: str) -> str:
    from urllib.parse import quote

    from frappe.utils import get_url

    return get_url(f"/api/method/reckon_sales_agent.api_twilio.{method}?company={quote(company)}")


def click_to_call(company: str, user: str, prospect_name: str) -> str:
    import frappe
    import requests
    from frappe import _
    from frappe.utils import now_datetime

    from reckon_sales_agent.agents.compliance import check_call
    from reckon_sales_agent.discovery.normalize import normalize_phone
    from reckon_sales_agent.usage import get_settings, log_activity

    settings = get_settings(company)
    sid, token = credentials(settings)
    agent_phone = normalize_phone(frappe.db.get_value("User", user, "mobile_no") or frappe.db.get_value("User", user, "phone"))
    if not agent_phone:
        frappe.throw(_("Add your mobile number to your user profile: Twilio rings it first."))
    prospect = frappe.get_doc("Sales Prospect", prospect_name)
    lead_phone = normalize_phone(prospect.phone)
    if not lead_phone:
        frappe.throw(_("This lead has no phone number."))
    if prospect.do_not_contact:
        frappe.throw(_("This lead asked not to be contacted."))
    check_call(company)
    params = click_to_call_params(agent_phone, lead_phone, settings.get("twilio_phone_number") or "",
                                  prospect.business_name, webhook_url("call_status", company),
                                  bool(settings.get("twilio_record_calls")), webhook_url("recording", company))
    try:
        response = requests.post(f"{API}/Accounts/{sid}/Calls.json", data=params, auth=(sid, token), timeout=15)
    except requests.RequestException as exc:
        frappe.throw(_("Twilio did not answer: {0}").format(str(exc)[:200]))
    body = response.json() if response.content else {}
    if response.status_code >= 400:
        frappe.throw(_("Twilio refused the call: {0}").format(str(body.get("message") or response.status_code)[:200]))
    from reckon_sales_agent.telephony import _write_log

    _write_log(company, {"id": body["sid"], "status": "Initiated", "type": "Outgoing", "from": agent_phone,
                         "to": lead_phone, "duration": 0, "start_time": now_datetime(),
                         "reference": prospect.crm_lead or prospect.name}, caller=user)
    if frappe.get_meta("CRM Call Log").get_field("telephony_medium"):
        frappe.db.set_value("CRM Call Log", {"id": body["sid"]}, "telephony_medium", "Twilio", update_modified=False)
    log_activity(company, "call_started", prospect, "via Twilio", agent="Engagement")
    return body["sid"]


def apply_status(company: str, form: dict) -> str | None:
    """Twilio's call status callback onto the CRM Call Log."""
    import frappe

    from reckon_sales_agent.telephony import _write_log

    sid = form.get("ParentCallSid") or form.get("CallSid")
    if not sid or not frappe.db.exists("CRM Call Log", {"id": sid}):
        return None
    log = frappe.db.get_value("CRM Call Log", {"id": sid}, ["type", "from", "to"], as_dict=True)
    return _write_log(company, {"id": sid, "status": call_status(form.get("CallStatus")), "type": log.type,
                                "from": log["from"], "to": log.to, "duration": int(form.get("CallDuration") or 0)})


def apply_recording(company: str, form: dict) -> None:
    import frappe

    from reckon_sales_agent.agents.voice import queue

    sid = form.get("CallSid")
    url = form.get("RecordingUrl")
    name = frappe.db.get_value("CRM Call Log", {"id": sid}) if sid else None
    if not name and form.get("ParentCallSid"):
        name = frappe.db.get_value("CRM Call Log", {"id": form["ParentCallSid"]})
    if name and url and form.get("RecordingStatus", "completed") == "completed":
        frappe.db.set_value("CRM Call Log", name, {"recording_url": f"{url}.mp3", "status": "Completed"},
                            update_modified=False)
        queue(name)


def voice_answer(company: str, caller: str, call_sid: str, speech: str) -> tuple[str, str]:
    """(TwiML verb(s), outcome) for one caller turn: answer and listen again, connect to a person, or say goodbye."""
    import frappe
    from frappe.utils import now_datetime

    from reckon_sales_agent.agents.chat import receive_chat
    from reckon_sales_agent.agents.content import knowledge_prompt
    from reckon_sales_agent.agents.content_agent import approved_knowledge
    from reckon_sales_agent.constants import USAGE_AI
    from reckon_sales_agent.providers.factory import get_llm
    from reckon_sales_agent.providers.llm import LLMError, untrusted
    from reckon_sales_agent.usage import get_settings, remaining, reserve

    settings = get_settings(company)
    language = settings.get("voice_ai_language") or "en-US"
    action = webhook_url("voice_turn", company)
    turns = frappe.db.count("Sales Chat Message", {"external_id": ["like", f"voice:{call_sid}:%"], "direction": "In"})
    name = receive_chat(company, "Voice", settings.get("twilio_phone_number") or "voice", caller, speech[:1000],
                        f"voice:{call_sid}:{turns + 1}", phone=caller)
    prospect = frappe.db.get_value("Sales Chat Message", name, "prospect") if name else None
    forward = settings.get("voice_forward_to")

    def connect(reason: str) -> tuple[str, str]:
        if prospect:
            from reckon_sales_agent.agents.conversations import handoff

            handoff(company, prospect, f"Phone call: {reason}")
        if forward:
            return say("Let me connect you to a colleague.", language) + dial(forward, settings.get("twilio_phone_number")), "connected"
        return say("A colleague will call you back soon. Thank you for calling.", language), "callback"

    llm = get_llm(company)
    if not llm or remaining(company, USAGE_AI) <= 0 or turns + 1 > MAX_TURNS:
        return connect("the assistant could not continue")
    history = "\n".join(f"{'CALLER' if r.direction == 'In' else 'ASSISTANT'}: {r.text}" for r in frappe.get_all(
        "Sales Chat Message", filters={"external_id": ["like", f"voice:{call_sid}:%"]},
        fields=["direction", "text"], order_by="sent_at asc", limit=20))
    reserve(company, USAGE_AI, 1, None)
    frappe.db.commit()
    try:
        data = llm.complete_json(VOICE_SYSTEM, untrusted("call so far", history) + "\n" + untrusted(
            "approved knowledge", knowledge_prompt(approved_knowledge(company))), VOICE_SCHEMA, max_tokens=500)
    except LLMError:
        return connect("the AI was unavailable")
    if data.get("needs_person") or not data.get("grounded"):
        return connect("the caller needs a person" if data.get("needs_person") else "the answer was not in the knowledge")
    answer = str(data.get("answer") or "").strip()[:600]
    frappe.get_doc({"doctype": "Sales Chat Message", "company": company, "prospect": prospect, "channel": "Voice",
                    "direction": "Out", "sent_at": now_datetime(), "contact_id": caller,
                    "external_id": f"voice:{call_sid}:{turns + 1}:out", "text": answer}).insert(ignore_permissions=True)
    if data.get("caller_done"):
        return say(answer, language) + say("Thank you for calling. Goodbye.", language), "done"
    return gather(answer + " Anything else?", action, language), "answered"


def send_email(message, settings) -> str | None:
    """One outreach email through SendGrid; returns SendGrid's message id."""
    import requests

    from reckon_sales_agent.providers.channels import ChannelUnavailable

    key = settings.get_password("sendgrid_api_key", raise_exception=False) if settings.get("sendgrid_api_key") else ""
    if not key or not settings.get("sendgrid_from_email"):
        raise ChannelUnavailable("Enter the SendGrid API key and a verified from address in Sales Agent Settings.")
    payload = sendgrid_payload(message.recipient, settings.sendgrid_from_email, settings.sender_name or message.company,
                               message.subject or "", message.body or "", message.name)
    try:
        response = requests.post("https://api.sendgrid.com/v3/mail/send", json=payload, timeout=30,
                                 headers={"Authorization": f"Bearer {key}"})
    except requests.RequestException as exc:
        raise ChannelUnavailable("SendGrid unreachable.") from exc
    if response.status_code >= 400:
        from reckon_sales_agent.providers.llm import http_reason

        raise ChannelUnavailable(f"SendGrid refused the email: {http_reason(response)}")
    return response.headers.get("X-Message-Id")
