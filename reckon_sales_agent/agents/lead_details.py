"""Ask a new contact for their details in the first reply, and read them from what they send back.

Works on every chat channel. ``extract`` is pure; ``after_inbound`` is called by the chat path for each inbound message.
A reply is never sent by this module: the question is a draft that a person approves, like every other reply.
"""

from __future__ import annotations

import re

ASK = ("Ask them, in one short friendly message, for their name, their phone number, their WhatsApp number "
       "(if different) and their email address. Say they can send them in any order, as 'Name: ...', 'Phone: ...', "
       "'WhatsApp: ...', 'Email: ...'.")
PLACEHOLDER = " contact …"  # the lead's name before we know it: "Messenger contact …9685"
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<![\w+])(\+?\d[\d\s().-]{7,}\d)(?!\w)")
LABEL = re.compile(r"^\s*(full name|name|phone|mobile|whatsapp|whats app|email|e-mail)\s*[:=\-]\s*(.+)$", re.I | re.M)


def extract(text: str) -> dict:
    """The details a person typed: labelled lines ("Name: Rahim") first, then a bare email or phone number."""
    found: dict = {}
    for label, value in LABEL.findall(text or ""):
        key, value = label.lower(), value.strip()
        if key in ("name", "full name"):
            found.setdefault("name", value[:140])
        elif key in ("whatsapp", "whats app"):
            found["whatsapp"] = value
        elif key in ("phone", "mobile"):
            found["phone"] = value
        elif key in ("email", "e-mail"):
            found["email"] = value
    if "email" not in found:
        match = EMAIL.search(text or "")
        if match:
            found["email"] = match.group(0)
    if "phone" not in found and "whatsapp" not in found:
        match = PHONE.search(EMAIL.sub(" ", text or ""))
        if match:
            found["phone"] = match.group(1)
    return found


def missing(prospect) -> list[str]:
    """What is still unknown about this lead, of name, email and phone."""
    out = []
    if not prospect.business_name or PLACEHOLDER in prospect.business_name:
        out.append("name")
    if not prospect.email:
        out.append("email")
    if not prospect.phone:
        out.append("phone")
    return out


def capture(prospect_name: str, text: str) -> dict:
    """Save what the person typed onto the lead. Never replaces a value already on the lead: a different number
    is kept as a note for a person to check. Returns the fields that were filled in."""
    import frappe

    from reckon_sales_agent.discovery.normalize import normalize_phone

    found = extract(text)
    if not found:
        return {}
    doc = frappe.get_doc("Sales Prospect", prospect_name)
    updates, notes = {}, []
    if found.get("name") and "name" in missing(doc):
        updates["business_name"] = found["name"]
    if found.get("email"):
        if not doc.email:
            updates["email"] = found["email"]
        elif found["email"].lower() != doc.email.lower():
            notes.append(f"Email given in chat: {found['email']}")
    number = normalize_phone(found.get("whatsapp") or found.get("phone") or "")
    if number:
        # WhatsApp and calls use the lead's phone, so a WhatsApp number becomes the phone when there is none yet.
        if not doc.phone:
            updates["phone"] = number
        elif normalize_phone(doc.phone) != number:
            notes.append(f"Phone given in chat: {number}")
    if updates:
        doc.db_set(updates)
    if notes or updates:
        doc.add_comment("Comment", "Details from chat: " + "; ".join(
            [f"{k} {v}" for k, v in updates.items()] + notes))
    return updates


def ask(prospect_name: str) -> str | None:
    """Queue the question as an AI draft for approval. Returns the draft's name, or None when no AI is set up."""
    import frappe

    from reckon_sales_agent.agents.omni import draft_reply

    if frappe.db.exists("Sales Outreach Message", {"prospect": prospect_name, "status": "Draft", "is_reply": 1}):
        return None  # a reply is already waiting for approval
    try:
        return draft_reply(prospect_name, reason="a new contact: ask for their details", instruction=ASK, allow_auto=False)
    except frappe.ValidationError:
        frappe.clear_messages()
        return None


def after_inbound(prospect_name: str, text: str, first: bool) -> None:
    """Called for every inbound chat message. Never raises: a lead-detail problem must not lose the message."""
    import frappe

    try:
        capture(prospect_name, text)
        if first and missing(frappe.get_doc("Sales Prospect", prospect_name)):
            ask(prospect_name)
    except Exception:
        frappe.log_error(title="Lead details step failed", message=f"Prospect {prospect_name}")
