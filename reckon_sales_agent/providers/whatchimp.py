"""WhatChimp WhatsApp messages for outreach (https://help.whatchimp.com/docs).

Scope: free-text messages inside the customer's 24-hour window. WhatChimp template sending is not connected yet:
outside the window, use the frappe_whatsapp provider with an approved template.

Unverified: the public docs do not give the exact base URL or body fields. The URL and field names below follow the
developer console's example (``POST /whatsapp/send`` under ``/api/v1/whatsapp``, with the account token and the
phone number ID in the body). Confirm them with one real send before relying on it; the first failure reports the
WhatChimp response.
"""

from __future__ import annotations

WHATCHIMP_SEND_URL = "https://whatchimp.com/api/v1/whatsapp/send"


def text_payload(token: str, phone_number_id: str, phone: str, text: str) -> dict:
    """The JSON body for a text message."""
    return {"apiToken": token, "phone_number_id": phone_number_id, "phone": phone, "message": text}


def send_text(message, settings) -> str | None:
    """Send one WhatsApp text message through WhatChimp; returns the message id when WhatChimp gives one."""
    import requests

    from reckon_sales_agent.providers.channels import ChannelUnavailable, html_to_text
    from reckon_sales_agent.providers.llm import http_reason

    if message.get("whatsapp_template"):
        raise ChannelUnavailable("WhatChimp template messages are not connected yet. Send a text inside the 24-hour window, "
                                 "or use the frappe_whatsapp provider for templates.")
    token = settings.get_password("whatchimp_api_token", raise_exception=False) if settings.get("whatchimp_api_token") else ""
    phone_number_id = settings.get("whatchimp_phone_number_id") or ""
    if not token or not phone_number_id:
        raise ChannelUnavailable("Enter the WhatChimp API token and phone number ID in Sales Agent Settings.")
    payload = text_payload(token, phone_number_id, message.recipient.lstrip("+"), html_to_text(message.body)[:4000])
    try:
        response = requests.post(WHATCHIMP_SEND_URL, json=payload, timeout=30, headers={"accept": "application/json"})
    except requests.RequestException as exc:
        raise ChannelUnavailable("WhatChimp unreachable.") from exc
    if response.status_code >= 400:
        raise ChannelUnavailable(f"WhatChimp refused the message: {http_reason(response)}")
    data = response.json() if response.content else {}
    return str(data.get("id") or data.get("message_id") or "") or None
