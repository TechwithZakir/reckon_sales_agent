"""Data-quality agent: keeps the lead data the other agents rely on clean, without ever deleting anything.

Each run (inside the autopilot, or "Run agents now"):

- normalises Bangladeshi phone numbers to +880… so duplicates and calls match;
- marks likely duplicates (same phone, email or website domain) with ``possible_duplicate_of`` so they
  are never auto-approved twice and a person can merge them in Prospect Review;
- drops an email the provider reported as a hard bounce, so campaigns stop trying it.

Only leads the agents own are touched (Sales Prospects); fields a person typed into the CRM are never changed.
``plan_fixes`` is pure.
"""

from __future__ import annotations

from reckon_sales_agent.discovery.normalize import (
    normalize_domain,
    normalize_email,
    normalize_phone,
)

BATCH = 2000


def plan_fixes(rows: list[dict], bounced: set[str] = frozenset()) -> dict:
    """``rows``: prospects oldest first ({name, phone, email, website, possible_duplicate_of, review_status}).

    Returns {"phones": [(name, new)], "duplicates": [(name, original, reason)], "bounced": [name]}.
    """
    phones, duplicates, dropped = [], [], []
    first_by: dict[tuple[str, str], str] = {}
    for row in rows:
        if row.get("review_status") in ("Merged", "Rejected"):
            continue
        phone = normalize_phone(row.get("phone"))
        if row.get("phone") and phone and phone != row["phone"]:
            phones.append((row["name"], phone))
        email = normalize_email(row.get("email")) if row.get("email") else ""
        if email and email in bounced:
            dropped.append(row["name"])
            email = ""
        keys = [("phone", phone), ("email", email), ("domain", normalize_domain(row.get("website")))]
        original = None
        for kind, value in keys:
            if not value:
                continue
            seen = first_by.get((kind, value))
            if seen and seen != row["name"] and not original:
                original = (seen, kind)
            first_by.setdefault((kind, value), row["name"])
        if original and not row.get("possible_duplicate_of"):
            duplicates.append((row["name"], original[0], f"same {original[1]}"))
    return {"phones": phones, "duplicates": duplicates, "bounced": dropped}


# --------------------------------------------------------------------------- Frappe side


def scan(company: str) -> dict:
    import frappe

    rows = frappe.get_all("Sales Prospect", filters={"company": company},
                          fields=["name", "phone", "email", "website", "possible_duplicate_of", "review_status"],
                          order_by="creation asc", limit=BATCH * 10)
    bounced = {normalize_email(v) for v in frappe.get_all("Sales Suppression Entry", filters={
        "company": company, "active": 1, "reason": "Bounced", "entry_type": "Email"}, pluck="value", limit=50000) if v}
    return plan_fixes(rows, bounced)


def pending_count(company: str) -> int:
    found = scan(company)
    return len(found["phones"]) + len(found["duplicates"]) + len(found["bounced"])


def clean(company: str) -> str:
    import frappe

    from reckon_sales_agent.usage import log_activity

    found = scan(company)
    for name, phone in found["phones"][:BATCH]:
        frappe.db.set_value("Sales Prospect", name, "phone", phone, update_modified=False)
    for name, original, _reason in found["duplicates"][:BATCH]:
        frappe.db.set_value("Sales Prospect", name, "possible_duplicate_of", original, update_modified=False)
    for name in found["bounced"][:BATCH]:
        frappe.db.set_value("Sales Prospect", name, "email", None, update_modified=False)
    summary = (f"{len(found['phones'])} phone(s) normalised, {len(found['duplicates'])} duplicate(s) marked, "
               f"{len(found['bounced'])} bounced email(s) removed")
    log_activity(company, "data_quality_cleaned", None, summary, actor_type="agent", agent="Research",
                 policy_outcome="automatic (reversible)")
    return summary
