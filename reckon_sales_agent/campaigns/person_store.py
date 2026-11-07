"""Finding or creating the Sales Prospect behind a person who signed up or was imported.

Every route in (forms, imports) ends here, so the same rules apply: a person is matched by email and then by phone, an
existing record is only ever filled in (never overwritten), a person marked do-not-contact is never touched, and a new
person is approved because they chose to be there (or a person chose them).
"""

from __future__ import annotations

import frappe
from frappe.utils import now_datetime, nowdate

from reckon_sales_agent.campaigns import tags as tag_rules
from reckon_sales_agent.campaigns.suppression import is_suppressed

FILL = ("contact_name", "email", "phone", "city", "industry")


def find(company: str, email: str = "", phone: str = "") -> str | None:
    base = {"company": company, "merged_into": ["is", "not set"]}
    if email:
        found = frappe.db.get_value("Sales Prospect", {**base, "email": email}, "name")
        if found:
            return found
    if phone:
        return frappe.db.get_value("Sales Prospect", {**base, "normalized_phone": phone}, "name")
    return None


def upsert(company: str, person: dict, *, source_type: str, consent_source: str = "", tags=(), unconfirmed: bool = False,
           optin_token: str = "", form: str = "", sms_opt_in: bool = False, whatsapp_opt_in: bool = False) -> tuple[str | None, str]:
    """(prospect, outcome) where outcome is created, updated, suppressed or do_not_contact. ``person`` holds email, phone,
    contact_name, business_name, city and industry (any may be empty)."""
    email, phone = person.get("email") or "", person.get("phone") or ""
    if is_suppressed(company, email=email or None, phone=phone or None):
        return None, "suppressed"
    meta = frappe.get_meta("Sales Prospect")
    name = find(company, email, phone)
    now = now_datetime()
    record = {"consent_source": consent_source[:140], "consent_date": nowdate()} if consent_source else {}
    consent = {"sms_consent": 1 if sms_opt_in else 0, "whatsapp_consent": 1 if whatsapp_opt_in else 0}         if (sms_opt_in or whatsapp_opt_in) else {}
    if name:
        row = frappe.db.get_value("Sales Prospect", name, ["do_not_contact", "tags", "optin_status", "consent_source", *FILL], as_dict=True)
        if row.do_not_contact:
            return name, "do_not_contact"
        changes = {field: person[field] for field in FILL if person.get(field) and not row.get(field)}
        if tags:
            merged = tag_rules.add(row.tags, tags)
            if merged != tag_rules.normalize(row.tags):
                changes["tags"] = tag_rules.to_text(merged)
        for key in ("sms_consent", "whatsapp_consent"):
            if consent.get(key):
                changes[key] = 1
        if record and (consent or not row.consent_source):
            changes.update(record)  # a new opt-in is recorded; an earlier record is not replaced by a plain signup
        if unconfirmed and row.optin_status != "Confirmed" and optin_token:
            changes.update(optin_status="Unconfirmed", optin_token=optin_token)
        if changes:
            frappe.db.set_value("Sales Prospect", name, changes, update_modified=True)
        return name, "updated"
    values = {
        "doctype": "Sales Prospect", "company": company,
        "business_name": person.get("business_name") or person.get("contact_name") or email or phone,
        "contact_name": person.get("contact_name") or None, "email": email or None, "phone": phone or None,
        "city": person.get("city") or None, "industry": person.get("industry") or None, "source_type": source_type[:140],
        "review_status": "Approved", "first_seen": now, "last_seen": now, "tags": tag_rules.to_text(tags) or None,
        "review_notes": f"Added through {source_type}.", "signup_form": form or None,
        "signup_at": now if form else None, "optin_status": "Unconfirmed" if unconfirmed else None,
        "optin_token": optin_token or None, **record, **consent,
    }
    doc = frappe.get_doc({k: v for k, v in values.items() if k == "doctype" or meta.has_field(k)})
    doc.insert(ignore_permissions=True)
    return doc.name, "created"
