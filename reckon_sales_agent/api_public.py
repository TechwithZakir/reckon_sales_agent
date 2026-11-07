"""The public API: for your own systems (a website, an app, a CRM, a script).

Authenticate with a Sales Agent manager's API key and secret (User → API Access → Generate Keys) in the header
``Authorization: token <api_key>:<api_secret>``. Every call is limited to that user's Company, needs an active subscription,
and can read, tag, add or unsubscribe people and read results. Nothing here sends a message or approves one: sending stays
with the campaigns and automations a person has approved.

    GET  /api/method/reckon_sales_agent.api_public.ping
    POST /api/method/reckon_sales_agent.api_public.person_upsert      email | phone, name, tags, consent_statement (required)
    GET  /api/method/reckon_sales_agent.api_public.person             email | phone
    POST /api/method/reckon_sales_agent.api_public.person_tags        email, add, remove
    POST /api/method/reckon_sales_agent.api_public.person_unsubscribe email
    GET  /api/method/reckon_sales_agent.api_public.segments
    GET  /api/method/reckon_sales_agent.api_public.segment_people     segment, limit
    GET  /api/method/reckon_sales_agent.api_public.forms
    GET  /api/method/reckon_sales_agent.api_public.automations
    GET  /api/method/reckon_sales_agent.api_public.events             since, type, limit
    POST /api/method/reckon_sales_agent.api_public.check_email        email
    POST /api/method/reckon_sales_agent.api_automation.trigger        automation, email | phone, name, consent_statement
"""

from __future__ import annotations

import frappe
from frappe import _

from reckon_sales_agent.api_studio import _can_manage
from reckon_sales_agent.campaigns import people, person_store, segment_service
from reckon_sales_agent.campaigns import tags as tag_rules
from reckon_sales_agent.campaigns.suppression import suppress
from reckon_sales_agent.campaigns.tag_service import add_tags, remove_tags
from reckon_sales_agent.discovery.normalize import normalize_email, normalize_phone
from reckon_sales_agent.tenant import current_company
from reckon_sales_agent.usage import assert_entitled, get_settings

MAX_LIST = 1000


def _company() -> str:
    if not _can_manage():
        frappe.throw(_("The API needs a Sales Agent admin or manager."), frappe.PermissionError)
    company = current_company()
    assert_entitled(company)
    return company


def _find(company: str, email: str, phone: str) -> str:
    found = person_store.find(company, normalize_email(email), normalize_phone(phone) if phone else "")
    if not found:
        frappe.throw(_("No one with that email or phone is on your list."), frappe.DoesNotExistError)
    return found


def _person(company: str, name: str) -> dict:
    views = segment_service.person_views(company, [name])
    view = views[0] if views else {}
    row = frappe.db.get_value("Sales Prospect", name, ["email", "phone", "contact_name", "business_name", "tags", "optin_status",
                                                      "email_status", "do_not_contact", "consent_source", "creation"], as_dict=True) or {}
    return {"id": name, "email": row.get("email") or "", "phone": row.get("phone") or "", "name": row.get("contact_name") or "",
            "business": row.get("business_name") or "", "tags": tag_rules.normalize(row.get("tags")),
            "email_confirmed": row.get("optin_status") != "Unconfirmed", "email_check": row.get("email_status") or "Unchecked",
            "opted_out": bool(row.get("do_not_contact")), "agreed": row.get("consent_source") or "", "joined": str(row.get("creation") or ""),
            "engagement": view.get("temperature", ""), "last_opened_days": view.get("last_opened_days"),
            "last_clicked_days": view.get("last_clicked_days"), "last_replied_days": view.get("last_replied_days")}


@frappe.whitelist(methods=["GET", "POST"])
def ping() -> dict:
    company = _company()
    return {"ok": True, "company": company, "user": frappe.session.user}


@frappe.whitelist(methods=["POST"])
def person_upsert(email: str = "", phone: str = "", name: str = "", business: str = "", city: str = "", industry: str = "",
                  tags: str = "", consent_statement: str = "") -> dict:
    """Add a person or fill in what is missing. ``consent_statement`` says how they agreed to hear from you; it is stored on them."""
    company = _company()
    statement = " ".join((consent_statement or "").split())
    if len(statement) < 10:
        frappe.throw(_("Say how this person agreed to hear from you (consent_statement)."))
    person = {"email": normalize_email(email), "phone": normalize_phone(phone) if phone else "", "contact_name": " ".join((name or "").split())[:140],
              "business_name": " ".join((business or "").split())[:140], "city": " ".join((city or "").split())[:80],
              "industry": " ".join((industry or "").split())[:80]}
    if not person["email"] and not person["phone"]:
        frappe.throw(_("Send a valid email or phone number."))
    prospect, outcome = person_store.upsert(company, person, source_type="api", consent_source=f"API: {statement} (by {frappe.session.user})")
    if not prospect:
        return {"saved": False, "reason": outcome}
    if outcome != "do_not_contact":
        add_tags(company, prospect, tags, "api")
        from reckon_sales_agent.campaigns.verify_service import check_later

        check_later(prospect)
    return {"saved": outcome != "do_not_contact", "outcome": outcome, "person": _person(company, prospect)}


@frappe.whitelist(methods=["GET", "POST"])
def person(email: str = "", phone: str = "") -> dict:
    company = _company()
    return _person(company, _find(company, email, phone))


@frappe.whitelist(methods=["POST"])
def person_tags(email: str = "", phone: str = "", add: str = "", remove: str = "") -> dict:
    company = _company()
    name = _find(company, email, phone)
    if add:
        add_tags(company, name, add, "api")
    if remove:
        remove_tags(name, remove)
    return _person(company, name)


@frappe.whitelist(methods=["POST"])
def person_unsubscribe(email: str) -> dict:
    """Stop all campaign email to this address, for good (the same as the person using the unsubscribe link)."""
    company = _company()
    address = normalize_email(email)
    if not address:
        frappe.throw(_("Send a valid email address."))
    suppress(company, "Email", address, "Unsubscribed", "api")
    for name in frappe.get_all("Sales Prospect", filters={"company": company, "email": address}, pluck="name"):
        frappe.db.set_value("Sales Prospect", name, "do_not_contact", 1, update_modified=False)
    return {"unsubscribed": True, "email": address}


@frappe.whitelist(methods=["GET", "POST"])
def segments() -> list[dict]:
    company = _company()
    return [{"id": r.name, "name": r.segment_name, "people": r.size or 0, "counted": str(r.last_refreshed or "")}
            for r in frappe.get_all("Sales Segment", filters={"company": company}, fields=["name", "segment_name", "size", "last_refreshed"], limit=200)]


@frappe.whitelist(methods=["GET", "POST"])
def segment_people(segment: str, limit: int = 100) -> dict:
    company = _company()
    doc = frappe.get_doc("Sales Segment", segment)
    if doc.company != company:
        frappe.throw(_("That segment belongs to another Company."), frappe.PermissionError)
    found = segment_service.resolve(doc)
    return {"total": len(found), "people": [{"id": p["name"], "email": p["email"], "phone": p["phone"], "name": p["contact_name"] or p["business_name"],
                                             "tags": p["tags"]} for p in found[:max(1, min(int(limit or 100), MAX_LIST))]]}


@frappe.whitelist(methods=["GET", "POST"])
def forms() -> list[dict]:
    company = _company()
    return [{"id": r.name, "key": r.slug, "name": r.form_name, "status": r.status, "signups": r.submissions or 0, "confirmed": r.confirmed_count or 0}
            for r in frappe.get_all("Sales Capture Form", filters={"company": company},
                                    fields=["name", "slug", "form_name", "status", "submissions", "confirmed_count"], limit=200)]


@frappe.whitelist(methods=["GET", "POST"])
def automations() -> list[dict]:
    company = _company()
    return [{"id": r.name, "name": r.automation_name, "status": r.status, "starts_when": r.trigger_event}
            for r in frappe.get_all("Sales Automation", filters={"company": company},
                                    fields=["name", "automation_name", "status", "trigger_event"], limit=200)]


@frappe.whitelist(methods=["GET", "POST"])
def events(since: str = "", type: str = "", limit: int = 200) -> list[dict]:  # noqa: A002 - "type" is the public parameter name
    """What happened to messages (sent, opened, clicked, replied, bounced, unsubscribed ...), oldest first."""
    company = _company()
    rows = people.events(company, since=since or None, limit=max(1, min(int(limit or 200), MAX_LIST)))
    if type:
        rows = [r for r in rows if r["event_type"] == type]
    return [{"event": r["event_type"], "at": r["event_time"], "person": r.get("prospect"), "campaign": r.get("campaign"),
             "message": r.get("message"), "channel": r.get("channel")} for r in rows]


@frappe.whitelist(methods=["POST"])
def check_email(email: str) -> dict:
    company = _company()
    from reckon_sales_agent.campaigns.verify_service import check_email as run

    return run(email, get_settings(company))
