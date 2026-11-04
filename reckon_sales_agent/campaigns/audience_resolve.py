"""Audiences on the Frappe side: find the people, and make each one a Sales Prospect (rules: campaigns.audience).

Every query is filtered by Company here, because ``frappe.get_all`` does not apply the tenant permission hooks. A person
who is not yet a Sales Prospect becomes one (approved, because a person chose them for an audience), so the campaign
engine, the consent rules and the suppression list treat everyone the same way. Existing prospects are never
re-approved, and a prospect marked do-not-contact is never changed.
"""

from __future__ import annotations

import frappe
from frappe.utils import now_datetime, nowdate

from reckon_sales_agent.campaigns import audience as rules
from reckon_sales_agent.campaigns.audience import CONTACTS, CUSTOMERS, LEADS, PROSPECTS, SPECIFIC

LIMIT = 5000
LEAD_FIELDS = ("name", "lead_name", "first_name", "last_name", "organization", "email", "mobile_no", "phone")
CONTACT_FIELDS = ("name", "first_name", "last_name", "company_name", "email_id", "mobile_no", "phone")
DEAL_FIELDS = ("name", "lead", "organization", "first_name", "last_name", "email", "mobile_no", "phone")


def _available(doctype: str, wanted) -> list[str]:
    meta = frappe.get_meta(doctype)
    return [field for field in wanted if field == "name" or meta.has_field(field)]


def _lead_recipient(row) -> dict | None:
    name = row.get("lead_name") or rules.person_name(row.get("first_name"), row.get("last_name")) or row.get("organization")
    return rules.recipient("Lead", "CRM Lead", row.get("name"), name, row.get("email"),
                           row.get("mobile_no") or row.get("phone"))


def _prospects(a) -> list[dict | None]:
    filters = {"company": a.company, "review_status": "Approved", "do_not_contact": 0}
    if a.minimum_fit_score:
        filters["fit_score"] = [">=", a.minimum_fit_score]
    if a.source_filter:
        filters["source_type"] = a.source_filter
    if a.city_filter:
        filters["city"] = ["like", f"%{a.city_filter}%"]
    if a.industry_filter:
        filters["industry"] = ["like", f"%{a.industry_filter}%"]
    rows = frappe.get_all("Sales Prospect", filters=filters, fields=["name", "business_name", "email", "phone"],
                          order_by="fit_score desc", limit=LIMIT)
    return [rules.recipient("Prospect", "Sales Prospect", r.name, r.business_name, r.email, r.phone) for r in rows]


def _leads(a) -> list[dict | None]:
    filters = {"rsa_company": a.company}
    statuses = rules.split_list(a.status_filter)
    if statuses:
        filters["status"] = ["in", statuses]
    if a.source_filter:
        filters["source"] = a.source_filter
    if a.owner_filter:
        filters["lead_owner"] = a.owner_filter
    rows = frappe.get_all("CRM Lead", filters=filters, fields=_available("CRM Lead", LEAD_FIELDS), limit=LIMIT)
    return [_lead_recipient(r) for r in rows]


def _contacts(a) -> list[dict | None]:
    rows = frappe.get_all("Contact", filters={"rsa_company": a.company},
                          fields=_available("Contact", CONTACT_FIELDS), limit=LIMIT)
    return [_contact_recipient(r) for r in rows]


def _contact_recipient(row) -> dict | None:
    name = rules.person_name(row.get("first_name"), row.get("last_name")) or row.get("company_name")
    return rules.recipient("Contact", "Contact", row.get("name"), name, row.get("email_id"),
                           row.get("mobile_no") or row.get("phone"))


def _won_statuses() -> list[str]:
    return frappe.get_all("CRM Deal Status", filters={"type": "Won"}, pluck="name") or ["Won"]


def _customers(a) -> list[dict | None]:
    deals = frappe.get_all("CRM Deal", filters={"rsa_company": a.company, "status": ["in", _won_statuses()]},
                           fields=_available("CRM Deal", DEAL_FIELDS), limit=LIMIT)
    leads = _leads_by_name(deals)  # one query for all the leads, not one per deal
    return [_deal_recipient(d, leads) for d in deals]


def _leads_by_name(deals) -> dict:
    names = [d.get("lead") for d in deals if d.get("lead")]
    if not names:
        return {}
    rows = frappe.get_all("CRM Lead", filters={"name": ["in", names]}, fields=_available("CRM Lead", LEAD_FIELDS))
    return {r.name: r for r in rows}


def _deal_recipient(deal, leads: dict) -> dict | None:
    """A customer is the person behind a won deal: the deal's own details, else the lead it came from."""
    lead = leads.get(deal.get("lead")) or {}
    email = deal.get("email") or lead.get("email")
    phone = deal.get("mobile_no") or deal.get("phone") or lead.get("mobile_no") or lead.get("phone")
    name = (rules.person_name(deal.get("first_name"), deal.get("last_name")) or lead.get("lead_name")
            or rules.person_name(lead.get("first_name"), lead.get("last_name")) or deal.get("organization"))
    return rules.recipient("Customer", "CRM Deal", deal.get("name"), name, email, phone)


def _lookup(company: str, doctype: str, name: str) -> dict | None:
    """One record picked by hand. A record of another Company is ignored, never read."""
    if doctype == "Sales Prospect":
        row = frappe.db.get_value(doctype, name, ["company", "business_name", "email", "phone"], as_dict=True)
        if row and row.company == company:
            return rules.recipient("Prospect", doctype, name, row.business_name, row.email, row.phone)
    elif doctype == "CRM Lead":
        row = frappe.db.get_value(doctype, name, list(_available(doctype, LEAD_FIELDS + ("rsa_company",))), as_dict=True)
        if row and row.get("rsa_company") == company:
            return _lead_recipient(row)
    elif doctype == "Contact":
        row = frappe.db.get_value(doctype, name, list(_available(doctype, CONTACT_FIELDS + ("rsa_company",))), as_dict=True)
        if row and row.get("rsa_company") == company:
            return _contact_recipient(row)
    elif doctype == "CRM Deal":
        row = frappe.db.get_value(doctype, name, list(_available(doctype, DEAL_FIELDS + ("rsa_company",))), as_dict=True)
        if row and row.get("rsa_company") == company:
            return _deal_recipient(row, _leads_by_name([row]))
    return None


def _specific(a) -> list[dict | None]:
    out = []
    for row in a.members or []:
        if row.get("reference_doctype") and row.get("reference_name"):
            out.append(_lookup(a.company, row.reference_doctype, row.reference_name))
        else:
            out.append(rules.recipient("Person", "", "", row.get("person_name"), row.get("email"), row.get("phone")))
    return out


def resolve(a) -> list[dict]:
    """The people the audience includes right now: one row per person, with at least one address."""
    builders = {PROSPECTS: _prospects, LEADS: _leads, CONTACTS: _contacts, CUSTOMERS: _customers, SPECIFIC: _specific}
    rows = rules.dedupe([r for r in builders[a.audience_type](a) if r])
    if a.get("require_email"):
        rows = [r for r in rows if r["email"]]
    if a.get("require_phone"):
        rows = [r for r in rows if r["phone"]]
    return rows


def preview(a, channels=None) -> dict:
    """Counts and a few names, for a person to check before using an audience. Nothing is created."""
    rows = resolve(a)
    return {"summary": rules.summary(rows, channels), "sample": rows[:8]}


def refresh(audience_name: str) -> dict:
    """Count the audience again and store the size on it."""
    a = frappe.get_doc("Sales Audience", audience_name)
    summary = rules.summary(resolve(a))
    frappe.db.set_value("Sales Audience", a.name, {"size": summary["total"], "size_email": summary["with_email"],
                                                   "size_phone": summary["with_phone"], "last_refreshed": now_datetime()},
                        update_modified=False)
    return summary


# People to prospects -------------------------------------------------------


def _external_id(item: dict) -> str:
    return f"audience:{item['ref_doctype']}:{item['ref_name']}" if item.get("ref_name") else ""


def _find_prospect(company: str, item: dict) -> str | None:
    if item["ref_doctype"] == "Sales Prospect":
        return item["ref_name"]
    if item["ref_doctype"] == "CRM Lead":
        found = frappe.db.get_value("Sales Prospect", {"company": company, "crm_lead": item["ref_name"]}, "name")
        if found:
            return found
    for filters in ({"external_id": _external_id(item)} if _external_id(item) else None,
                    {"email": item["email"]} if item["email"] else None,
                    {"normalized_phone": item["phone"]} if item["phone"] else None):
        if filters:
            found = frappe.db.get_value("Sales Prospect", {"company": company, "merged_into": ["is", "not set"], **filters}, "name")
            if found:
                return found
    return None


def _opt_in_fields(a) -> dict:
    values = {}
    if a.get("sms_opt_in"):
        values["sms_consent"] = 1
    if a.get("whatsapp_opt_in"):
        values["whatsapp_consent"] = 1
    if values:
        values["consent_source"] = f"audience {a.name}: {a.opt_in_source}"[:140]
        values["consent_date"] = nowdate()
    return values


def _create_prospect(a, item: dict) -> str:
    meta = frappe.get_meta("Sales Prospect")
    values = {
        "doctype": "Sales Prospect", "company": a.company,
        "business_name": item["name"] or item["email"] or item["phone"],
        # A lead, contact or customer is a person: their name is who to greet ({{first_name}}).
        "contact_name": item["name"] if item["kind"] != "Prospect" and item["name"] else None,
        "email": item["email"] or None, "phone": item["phone"] or None, "source_type": "audience",
        "review_status": "Approved", "external_id": _external_id(item) or None, "first_seen": now_datetime(),
        "last_seen": now_datetime(), "review_notes": f"Added from the audience {a.audience_name}.",
        "crm_lead": item["ref_name"] if item["ref_doctype"] == "CRM Lead" else None,
        **_opt_in_fields(a),
    }
    prospect = frappe.get_doc({k: v for k, v in values.items() if k == "doctype" or meta.has_field(k)}).insert(
        ignore_permissions=True)
    if item["ref_doctype"] == "CRM Lead" and frappe.db.has_column("CRM Lead", "rsa_prospect"):
        frappe.db.set_value("CRM Lead", item["ref_name"], "rsa_prospect", prospect.name, update_modified=False)
    return prospect.name


def _apply_opt_in(a, prospect_name: str) -> None:
    """Record the audience's SMS or WhatsApp permission on a prospect that does not have it yet."""
    wanted = _opt_in_fields(a)
    if not wanted:
        return
    row = frappe.db.get_value("Sales Prospect", prospect_name, ["do_not_contact", "sms_consent", "whatsapp_consent"], as_dict=True)
    if not row or row.do_not_contact:
        return
    changes = {k: v for k, v in wanted.items() if k in ("sms_consent", "whatsapp_consent") and not row.get(k)}
    if changes:
        frappe.db.set_value("Sales Prospect", prospect_name, {**changes, "consent_source": wanted["consent_source"],
                                                              "consent_date": wanted["consent_date"]}, update_modified=False)


def materialize(a) -> list[tuple[str, dict]]:
    """(prospect, person) for everyone in the audience, creating prospects for people who are not one yet."""
    pairs = []
    for item in resolve(a):
        name = _find_prospect(a.company, item)
        if name:
            _apply_opt_in(a, name)
        else:
            name = _create_prospect(a, item)
        pairs.append((name, item))
    return pairs
