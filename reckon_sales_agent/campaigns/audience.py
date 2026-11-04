"""Audiences: who a campaign goes to (pure: no Frappe imports, so the rules are unit-tested directly).

An audience is one of five kinds. Four are rule-based and re-read the records each time they are used; one is a hand-
picked list:

* Prospects: Sales Prospects the team approved (filter by fit score, city, industry and where they came from).
* CRM Leads: leads in Frappe CRM (filter by status, source and owner).
* CRM Contacts: contacts in Frappe CRM.
* Customers: CRM contacts with a won deal.
* Specific people: a list of named people, each a record from any of the above or just an email and a phone.

Every kind is resolved to the same recipient shape, de-duplicated by email and phone, and then turned into Sales
Prospects so the campaign engine, consent rules and suppression list apply to all of them in the same way.
"""

from __future__ import annotations

from reckon_sales_agent.discovery.normalize import normalize_email, normalize_phone

PROSPECTS = "Prospects"
LEADS = "CRM Leads"
CONTACTS = "CRM Contacts"
CUSTOMERS = "Customers"
SPECIFIC = "Specific people"
AUDIENCE_TYPES = (PROSPECTS, LEADS, CONTACTS, CUSTOMERS, SPECIFIC)

# The records a specific person can point at. "CRM Deal" stands for the customer behind a won deal.
REFERENCE_DOCTYPES = ("Sales Prospect", "CRM Lead", "Contact", "CRM Deal")
KIND_OF = {"Sales Prospect": "Prospect", "CRM Lead": "Lead", "Contact": "Contact", "CRM Deal": "Customer"}
EMAIL_CHANNELS = frozenset({"Email"})
PHONE_CHANNELS = frozenset({"SMS", "WhatsApp", "Call Task"})


def split_list(text) -> list[str]:
    """Comma or line separated values, trimmed, without blanks or repeats (order kept)."""
    seen: list[str] = []
    for part in str(text or "").replace("\n", ",").split(","):
        value = part.strip()
        if value and value not in seen:
            seen.append(value)
    return seen


def recipient(kind: str, ref_doctype: str, ref_name: str, name: str = "", email: str = "", phone: str = "") -> dict | None:
    """One normalised recipient, or None when there is nothing to reach them on."""
    email = normalize_email(email)
    phone = normalize_phone(phone)
    if not email and not phone:
        return None
    return {"kind": kind, "ref_doctype": ref_doctype or "", "ref_name": ref_name or "",
            "name": " ".join(str(name or "").split())[:140], "email": email, "phone": phone}


def dedupe(recipients: list[dict]) -> list[dict]:
    """One row per person: rows sharing an email or a phone are merged, the first one wins and gaps are filled in."""
    out: list[dict] = []
    index: dict[tuple[str, str], int] = {}
    for item in recipients:
        keys = [("e", item["email"])] if item.get("email") else []
        if item.get("phone"):
            keys.append(("p", item["phone"]))
        found = next((index[key] for key in keys if key in index), None)
        if found is None:
            out.append(dict(item))
            found = len(out) - 1
        else:
            base = out[found]
            for field in ("name", "email", "phone"):
                if not base.get(field) and item.get(field):
                    base[field] = item[field]
        for key in keys:
            index.setdefault(key, found)
        base = out[found]
        # A merged row can learn a second address, which may link it to later rows.
        if base.get("email"):
            index.setdefault(("e", base["email"]), found)
        if base.get("phone"):
            index.setdefault(("p", base["phone"]), found)
    return out


def reachable_by(item: dict, channels) -> bool:
    """True when the recipient has an address for at least one of the channels (no channels: any address)."""
    wanted = set(channels or [])
    if not wanted:
        return bool(item.get("email") or item.get("phone"))
    return bool((wanted & EMAIL_CHANNELS and item.get("email")) or (wanted & PHONE_CHANNELS and item.get("phone")))


def summary(recipients: list[dict], channels=None) -> dict:
    """Counts a person reads before using an audience."""
    by_kind: dict[str, int] = {}
    for item in recipients:
        by_kind[item.get("kind") or "?"] = by_kind.get(item.get("kind") or "?", 0) + 1
    return {"total": len(recipients), "with_email": sum(1 for r in recipients if r.get("email")),
            "with_phone": sum(1 for r in recipients if r.get("phone")),
            "reachable": sum(1 for r in recipients if reachable_by(r, channels)), "by_kind": by_kind}


def person_name(*parts: str) -> str:
    """A display name from whatever the record has: first and last name, or a company, or nothing."""
    return " ".join(" ".join(str(p or "").split()) for p in parts if str(p or "").strip()).strip()
