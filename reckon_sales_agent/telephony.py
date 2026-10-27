"""Telephony phase 1: click-to-call through the Company's own PBX (Asterisk over SIP), and call logs.

Bangladeshi numbers must be called through a BTRC-licensed IPTSP SIP trunk; the PBX's dial plan routes +880
numbers there and other countries to an international trunk (see docs/roadmap.md, section 2).

- Click-to-call: the app asks Asterisk (ARI) to ring the salesperson's own extension first (desk phone or a
  softphone app); when they answer, Asterisk dials the lead in the configured context.
- Call events: the PBX posts each call's result to ``api_telephony.call_event``, signed with the Company's
  secret (HMAC-SHA256). The app writes Frappe CRM's own Call Log, linked to the CRM lead (or the prospect),
  so call history and recordings appear in the CRM as with its built-in providers.
- Inbound: an incoming call is matched to a lead by number and the owner is notified.

``originate_params``, ``call_status`` and ``normalize_event`` are pure.
"""

from __future__ import annotations

from urllib.parse import quote

ASTERISK = "Asterisk (SIP)"
# Asterisk DIALSTATUS -> Frappe CRM Call Log status.
STATUS = {"ANSWER": "Completed", "COMPLETED": "Completed", "NOANSWER": "No Answer", "BUSY": "Busy",
          "CANCEL": "No Answer", "CHANUNAVAIL": "Failed", "CONGESTION": "Failed", "FAILED": "Failed",
          "RINGING": "Ringing", "INITIATED": "Initiated", "INPROGRESS": "In Progress", "UP": "In Progress"}


def call_status(raw: str | None) -> str:
    return STATUS.get(str(raw or "").upper().replace(" ", "").replace("_", ""), "Completed")


def dial_digits(number: str) -> str:
    """What the dial plan receives: E.164 without the plus (8801711…); the PBX decides the trunk."""
    from reckon_sales_agent.discovery.normalize import normalize_phone

    phone = normalize_phone(number) or ""
    return phone.lstrip("+")


def originate_params(extension: str, number: str, context: str, caller_id: str | None, call_id: str,
                     reference: str) -> tuple[str, dict]:
    """(query string, JSON body) for ``POST /ari/channels``: ring the salesperson, then dial the lead."""
    query = {
        "endpoint": f"PJSIP/{extension}",
        "extension": dial_digits(number),
        "context": context or "from-internal",
        "priority": "1",
        "timeout": "30",
        "channelId": call_id,
    }
    if caller_id:
        query["callerId"] = caller_id
    body = {"variables": {"RECKON_CALL_ID": call_id, "RECKON_REFERENCE": reference,
                          "CALLERID(name)": "Reckon CRM"}}
    return "&".join(f"{k}={quote(str(v), safe='')}" for k, v in query.items()), body


def normalize_event(payload: dict) -> dict:
    """A PBX call event in the fields Frappe CRM's Call Log uses."""
    direction = "Incoming" if str(payload.get("direction") or "").lower().startswith("in") else "Outgoing"
    duration = payload.get("duration") or payload.get("billsec") or 0
    try:
        duration = max(0, int(float(duration)))
    except (TypeError, ValueError):
        duration = 0
    return {
        "id": str(payload.get("call_id") or payload.get("uniqueid") or "")[:140],
        "status": call_status(payload.get("status") or payload.get("dialstatus")),
        "type": direction,
        "from": str(payload.get("from") or payload.get("src") or "")[:40],
        "to": str(payload.get("to") or payload.get("dst") or "")[:40],
        "duration": duration,
        "recording_url": str(payload.get("recording_url") or "")[:1000] or None,
        "extension": str(payload.get("extension") or "")[:40] or None,
        "start_time": payload.get("start_time") or None,
        "end_time": payload.get("end_time") or None,
        "reference": str(payload.get("reference") or "")[:140] or None,
    }


# --------------------------------------------------------------------------- Frappe side


def extension_of(user: str) -> str | None:
    import frappe

    if not frappe.db.has_column("CRM Telephony Agent", "rsa_sip_extension"):
        return None
    return frappe.db.get_value("CRM Telephony Agent", {"user": user}, "rsa_sip_extension")


def user_of_extension(company: str, extension: str | None) -> str | None:
    import frappe

    if not extension or not frappe.db.has_column("CRM Telephony Agent", "rsa_sip_extension"):
        return None
    return frappe.db.get_value("CRM Telephony Agent", {"rsa_sip_extension": extension, "rsa_company": company}, "user")


def click_to_call(company: str, user: str, prospect_name: str) -> str:
    """Ring the salesperson's extension, then the lead; returns the call id."""
    import frappe
    import requests
    from frappe import _
    from frappe.utils import now_datetime

    from reckon_sales_agent.usage import get_settings, log_activity

    settings = get_settings(company)
    if settings.get("telephony_provider") != ASTERISK or not settings.get("ari_url"):
        frappe.throw(_("Set up the phone system first (Sales Agent Settings → Phone system)."))
    extension = extension_of(user)
    if not extension:
        frappe.throw(_("You have no phone extension yet: add yours under CRM Telephony Agent (SIP extension)."))
    prospect = frappe.get_doc("Sales Prospect", prospect_name)
    if not dial_digits(prospect.phone):
        frappe.throw(_("This lead has no phone number."))
    if prospect.do_not_contact:
        frappe.throw(_("This lead asked not to be contacted."))
    call_id = f"rsa-{frappe.generate_hash(length=16)}"
    reference = prospect.crm_lead or prospect.name
    query, body = originate_params(extension, prospect.phone, settings.get("sip_context"),
                                   settings.get("sip_caller_id"), call_id, reference)
    url = settings.ari_url.rstrip("/")
    if not url.startswith("https://"):
        frappe.throw(_("The Asterisk ARI URL must use HTTPS."))
    try:
        response = requests.post(f"{url}/ari/channels?{query}", json=body, timeout=10,
                                 auth=(settings.ari_username or "", settings.get_password("ari_password",
                                                                                          raise_exception=False) or ""))
    except requests.RequestException as exc:
        frappe.throw(_("The phone system did not answer: {0}").format(str(exc)[:200]))
    if response.status_code >= 400:
        frappe.throw(_("The phone system refused the call ({0}): {1}").format(response.status_code,
                                                                             response.text[:200]))
    _write_log(company, {"id": call_id, "status": "Initiated", "type": "Outgoing", "from": extension,
                         "to": prospect.phone, "duration": 0, "start_time": now_datetime(), "reference": reference},
               caller=user)
    log_activity(company, "call_started", prospect, f"via extension {extension}", agent="Engagement")
    return call_id


def apply_event(company: str, payload: dict) -> str:
    """Write a PBX call event to Frappe CRM's Call Log; notify the owner of an inbound call."""
    import frappe

    event = normalize_event(payload)
    if not event["id"]:
        frappe.throw("A call event needs a call id.")
    user = user_of_extension(company, event["extension"])
    name = _write_log(company, event, caller=user if event["type"] == "Outgoing" else None,
                      receiver=user if event["type"] == "Incoming" else None)
    if event["type"] == "Incoming" and event["status"] in ("Ringing", "Initiated", "In Progress", "No Answer"):
        _notify_inbound(company, event, user)
    return name


def _match(company: str, number: str) -> tuple[str | None, str | None]:
    """(reference doctype, name) for a phone number: a CRM lead first, else a prospect."""
    import frappe

    from reckon_sales_agent.discovery.normalize import normalize_phone

    phone = normalize_phone(number)
    if not phone:
        return None, None
    prospect = frappe.db.get_value("Sales Prospect", {"company": company, "normalized_phone": phone},
                                   ["name", "crm_lead"], as_dict=True)
    if prospect:
        return ("CRM Lead", prospect.crm_lead) if prospect.crm_lead else ("Sales Prospect", prospect.name)
    lead = frappe.db.get_value("CRM Lead", {"rsa_company": company, "mobile_no": ["in", [phone, phone.lstrip("+")]]},
                               "name") if frappe.db.has_column("CRM Lead", "rsa_company") else None
    return ("CRM Lead", lead) if lead else (None, None)


def _write_log(company: str, event: dict, caller: str | None = None, receiver: str | None = None) -> str:
    import frappe

    existing = frappe.db.get_value("CRM Call Log", {"id": event["id"]}, "name")
    doc = frappe.get_doc("CRM Call Log", existing) if existing else frappe.new_doc("CRM Call Log")
    other = event["to"] if event["type"] == "Outgoing" else event["from"]
    ref_doctype, ref_name = (None, None)
    if event.get("reference"):
        ref_doctype = "CRM Lead" if frappe.db.exists("CRM Lead", event["reference"]) else (
            "Sales Prospect" if frappe.db.exists("Sales Prospect", event["reference"]) else None)
        ref_name = event["reference"] if ref_doctype else None
    if not ref_name:
        ref_doctype, ref_name = _match(company, other)
    doc.update({k: v for k, v in {
        "id": event["id"], "status": event["status"], "type": event["type"], "from": event["from"],
        "to": event["to"], "duration": event.get("duration") or 0, "medium": ASTERISK,
        "recording_url": event.get("recording_url"), "start_time": event.get("start_time"),
        "end_time": event.get("end_time"), "reference_doctype": ref_doctype, "reference_docname": ref_name,
        "caller": caller, "receiver": receiver,
    }.items() if v not in (None, "") or k in ("duration",)})
    if frappe.get_meta("CRM Call Log").has_field("rsa_company"):
        doc.rsa_company = doc.get("rsa_company") or company
    doc.flags.ignore_permissions = True
    doc.save() if existing else doc.insert()
    return doc.name


def _notify_inbound(company: str, event: dict, user: str | None) -> None:
    import frappe

    from reckon_sales_agent.usage import get_settings

    ref_doctype, ref_name = _match(company, event["from"])
    owner = user or (frappe.db.get_value(ref_doctype, ref_name, "lead_owner") if ref_doctype == "CRM Lead" else None) \
        or get_settings(company).get("task_assignee")
    if not owner:
        return
    who = ref_name or event["from"]
    frappe.get_doc({"doctype": "Notification Log", "for_user": owner, "type": "Alert",
                    "subject": f"Incoming call from {who} ({event['status']})",
                    "document_type": ref_doctype, "document_name": ref_name}).insert(ignore_permissions=True)
