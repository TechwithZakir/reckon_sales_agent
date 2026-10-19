"""Outreach channel adapters: Email, SMS, WhatsApp, and CRM tasks for human steps.

The campaign engine decides *whether* to send (approval, suppression,
limits); a channel only knows *how*. Each channel also decides whether a
member can be reached on it, so consent rules live in one place:
SMS and WhatsApp require recorded consent; a public phone number is never
treated as permission.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

import frappe
from frappe.utils import add_days, nowdate

from reckon_sales_agent.constants import TASK_CHANNELS
from reckon_sales_agent.discovery.normalize import normalize_phone

SMS_MAX_CHARS = 459  # three concatenated GSM segments


@dataclass
class SendResult:
    provider_message_id: str | None = None
    detail: str | None = None


class ChannelUnavailable(Exception):
    pass


def html_to_text(value: str) -> str:
    text = re.sub(r"<br\s*/?>|</p>", "\n", value or "", flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(text)).strip()


def reachability(channel: str, prospect, settings) -> tuple[bool, str, str | None]:
    """(reachable, reason, recipient) for one channel."""
    if channel == "Email":
        return (True, "Public business email.", prospect.email) if prospect.email else (False, "No email.", None)
    if channel in ("SMS", "WhatsApp"):
        phone = normalize_phone(prospect.phone)
        if not phone:
            return False, "No phone number.", None
        if channel == "SMS":
            if not settings.sms_enabled:
                return False, "SMS is off in settings.", None
            if not prospect.sms_consent:
                return False, "No recorded SMS consent.", None
        else:
            if not settings.whatsapp_enabled:
                return False, "WhatsApp is off in settings.", None
            if not prospect.whatsapp_consent:
                return False, "No recorded WhatsApp opt-in.", None
        return True, f"{channel} consent recorded.", phone
    if channel in TASK_CHANNELS:
        if not prospect.crm_lead:
            return False, "Not in the CRM yet.", None
        return True, "CRM task for the lead owner.", prospect.crm_lead
    return False, f"Unknown channel {channel}.", None


def send(channel: str, message, settings) -> SendResult:
    if channel == "Email":
        return _email(message, settings)
    if channel == "SMS":
        return _sms(message)
    if channel == "WhatsApp":
        return _whatsapp(message)
    if channel in TASK_CHANNELS:
        return create_task(message.prospect, f"{channel.replace(' Task', '')}: {message.subject}",
                           html_to_text(message.body), settings)
    raise ChannelUnavailable(channel)


def _email(message, settings) -> SendResult:
    from frappe.core.doctype.communication.email import make

    result = make(
        doctype="Sales Outreach Message",
        name=message.name,
        content=message.body,
        subject=message.subject,
        recipients=message.recipient,
        sender_full_name=settings.sender_name or message.company,
        send_email=True,
        communication_medium="Email",
    )
    return SendResult(frappe.db.get_value("Communication", result.get("name"), "message_id"))


def _sms(message) -> SendResult:
    try:
        from reckon_saas_platform.sms import is_sms_configured, send_sms
    except ImportError as exc:
        raise ChannelUnavailable("SMS gateway is not installed.") from exc
    if not is_sms_configured():
        raise ChannelUnavailable("SMS gateway is not configured.")
    text = html_to_text(message.body)[:SMS_MAX_CHARS]
    reference = send_sms(message.recipient.lstrip("+"), text)
    return SendResult(str(reference) if reference else None)


def _whatsapp(message) -> SendResult:
    if "frappe_whatsapp" not in frappe.get_installed_apps():
        raise ChannelUnavailable("Install the frappe_whatsapp app to send WhatsApp messages.")
    doc = frappe.get_doc({
        "doctype": "WhatsApp Message",
        "type": "Outgoing",
        "to": message.recipient.lstrip("+"),
        "message": html_to_text(message.body)[:4000],
        "content_type": "text",
        "reference_doctype": "Sales Outreach Message",
        "reference_name": message.name,
    }).insert(ignore_permissions=True)
    return SendResult(doc.get("message_id") or doc.name)


def create_task(prospect_name: str, title: str, description: str, settings, priority: str = "Medium") -> SendResult:
    """A CRM Task on the prospect's lead, assigned to the lead owner."""
    lead = frappe.db.get_value("Sales Prospect", prospect_name, "crm_lead")
    if not lead:
        raise ChannelUnavailable("The prospect has no CRM lead.")
    owner = frappe.db.get_value("CRM Lead", lead, "lead_owner")
    task = frappe.get_doc({
        "doctype": "CRM Task",
        "title": title[:140],
        "description": html.escape(description or "").replace("\n", "<br>"),
        "status": "Todo",
        "priority": priority,
        "due_date": add_days(nowdate(), int(settings.task_due_days or 1)),
        "assigned_to": owner,
        "reference_doctype": "CRM Lead",
        "reference_docname": lead,
    }).insert(ignore_permissions=True)
    return SendResult(task.name, "task")
