"""Email in Conversations: mail between a lead and the Company's sending account lands on the lead's thread, so the
Agent can handle it like any other chat.

Covers mail sent from Reckon and from Frappe CRM. Replies to Reckon's own outreach keep their sequence path
(campaigns.engine.handle_communication); this module takes everything else. An incoming email gets an AI draft,
which a person approves before it is sent, the same as a chat message.
"""

from __future__ import annotations

CHANNEL = "Email"


def company_address(company: str) -> str:
    """The address the Company sends email from: the chosen account if it can send, else the default outgoing one."""
    import frappe

    from reckon_sales_agent.usage import get_settings

    chosen = get_settings(company).get("email_account")
    if chosen:
        address = frappe.db.get_value("Email Account", {"name": chosen, "enable_outgoing": 1}, "email_id")
        if address:
            return address.lower()
    return (frappe.db.get_value("Email Account", {"enable_outgoing": 1, "default_outgoing": 1}, "email_id") or "").lower()


def _lead(doc) -> str | None:
    """The Sales Prospect for this email: the CRM Lead it is on, or the lead whose email it is."""
    import frappe

    if doc.get("reference_doctype") == "CRM Lead" and doc.get("reference_name"):
        return frappe.db.get_value("Sales Prospect", {"crm_lead": doc.reference_name}, "name")
    return None


def _external_id(doc) -> str:
    key = (doc.get("message_id") or "").strip().strip("<>") or doc.name
    return f"email:{key}"[:140]


def file_email(doc) -> None:
    """``Communication.after_insert`` for mail that is not a reply to outreach. Never raises into the mail itself."""
    import frappe

    try:
        _file(doc)
    except Exception:
        frappe.log_error(title="Email conversation step failed", message=f"Communication {doc.name}")


def _file(doc) -> None:
    import frappe

    from reckon_sales_agent.agents.chat import receive_chat
    from reckon_sales_agent.providers.channels import html_to_text

    prospect = _lead(doc)
    if not prospect:
        return
    company = frappe.db.get_value("Sales Prospect", prospect, "company")
    address = company_address(company)
    if not address:
        return  # the Company does not send email, so there is no mailbox to file it under
    text = html_to_text(doc.content or "") or (doc.subject or "")
    external = _external_id(doc)
    if frappe.db.exists("Sales Chat Message", {"external_id": external}):
        return
    if doc.sent_or_received == "Received" and address in (doc.get("recipients") or "").lower():
        contact = (doc.get("sender") or "").lower().strip()
        name = receive_chat(company, CHANNEL, address, contact or prospect, text, external,
                            at=doc.communication_date or doc.creation, email=contact or None)
        if name:
            frappe.enqueue("reckon_sales_agent.agents.chat.auto_draft", queue="short", prospect=prospect,
                           job_id=f"chat-draft:{prospect}", deduplicate=True)
    elif doc.sent_or_received == "Sent" and (doc.get("sender") or "").lower().strip() == address:
        frappe.get_doc({
            "doctype": "Sales Chat Message", "company": company, "prospect": prospect, "channel": CHANNEL,
            "direction": "Out", "sent_at": doc.communication_date or doc.creation,
            "contact_id": (doc.get("recipients") or "").lower().strip(), "account_id": address,
            "external_id": external, "contact_name": None, "text": text, "kind": "Message",
        }).insert(ignore_permissions=True)
