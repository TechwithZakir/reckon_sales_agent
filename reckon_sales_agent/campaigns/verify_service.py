"""Email address checking on the Frappe side: look the domain up, ask a provider when one is set, store the answer on the person.

The answer is kept on the Sales Prospect (email_status, email_check_note, email_checked_at). An Invalid address is not emailed by
campaigns (providers.channels.reachability); Risky and Valid are. Everything is limited to the Company being checked.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, now_datetime

from reckon_sales_agent.campaigns import verify

DOH = "https://cloudflare-dns.com/dns-query"
MX_CACHE_SECONDS = 24 * 3600
JOB_LIMIT = 3000
RECHECK_DAYS = 90
COMMIT_EVERY = 100


def mx_exists(domain: str) -> bool | None:
    """True when the domain has a mail server (or at least an address to deliver to), False when it does not exist or has
    none, None when the lookup failed. Answers are kept a day."""
    domain = (domain or "").strip().lower()
    if not domain:
        return False
    key = f"rsa_mx:{domain}"
    cached = frappe.cache.get_value(key)
    if cached in ("1", "0"):
        return cached == "1"
    import requests

    result: bool | None = None
    try:
        for kind in ("MX", "A"):
            response = requests.get(DOH, params={"name": domain, "type": kind}, headers={"accept": "application/dns-json"}, timeout=6)
            data = response.json()
            answers = [a for a in data.get("Answer") or [] if a.get("type") in (15, 1, 28)]
            if answers:
                result = True
                break
            if data.get("Status") == 3:  # NXDOMAIN: the domain does not exist
                result = False
                break
            result = False  # exists but has neither: nothing to deliver to
    except (requests.RequestException, ValueError):
        return None
    frappe.cache.set_value(key, "1" if result else "0", expires_in_sec=MX_CACHE_SECONDS)
    return result


def _provider_answer(settings, email: str) -> dict | None:
    if (settings.get("verify_provider") or "") != "ZeroBounce":
        return None
    key = settings.get_password("zerobounce_api_key", raise_exception=False) if settings.get("zerobounce_api_key") else ""
    if not key:
        return None
    import requests

    try:
        response = requests.get("https://api.zerobounce.net/v2/validate", params={"api_key": key, "email": email}, timeout=15)
        return verify.zerobounce(response.json())
    except (requests.RequestException, ValueError):
        return None


def check_email(email: str, settings=None) -> dict:
    """The full answer for one address: the built-in check, then the provider when the built-in one did not already say Invalid."""
    answer = verify.check(email, mx_exists(verify.domain_of(email)))
    if settings is not None and answer["status"] in (verify.VALID, verify.RISKY):
        answer = verify.merge(answer, _provider_answer(settings, email))
    return answer


def check_prospect(name: str, settings=None) -> str:
    """Check one person and store the answer. Returns the status ('' when it could not be decided)."""
    row = frappe.db.get_value("Sales Prospect", name, ["email", "company"], as_dict=True)
    if not row or not row.email:
        return ""
    answer = check_email(row.email, settings or _settings(row.company))
    if answer["status"]:
        frappe.db.set_value("Sales Prospect", name, {"email_status": answer["status"], "email_check_note": answer["reason"][:140] or None,
                                                     "email_checked_at": now_datetime()}, update_modified=False)
    return answer["status"]


def _settings(company: str):
    from reckon_sales_agent.usage import get_settings

    return get_settings(company)


def check_later(prospect: str) -> None:
    """A new signup or import: check them in the background."""
    frappe.enqueue("reckon_sales_agent.campaigns.verify_service.check_one", queue="short", enqueue_after_commit=True, prospect=prospect)


def check_one(prospect: str) -> None:
    try:
        check_prospect(prospect)
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        frappe.log_error(title="Sales Agent address check failed", reference_doctype="Sales Prospect", reference_name=prospect)


def pending_filters(company: str, scope: str) -> dict:
    filters: dict = {"company": company, "email": ["is", "set"], "merged_into": ["is", "not set"]}
    if scope == "all":
        return filters
    filters["email_status"] = ["is", "not set"]
    return filters


def start(company: str, scope: str = "unchecked") -> int:
    """Queue a background check for the Company. Returns how many addresses are waiting."""
    scope = "all" if scope == "all" else "unchecked"
    waiting = frappe.db.count("Sales Prospect", pending_filters(company, scope))
    if waiting:
        frappe.enqueue("reckon_sales_agent.campaigns.verify_service.run_job", queue="long", timeout=1800, company=company, scope=scope,
                       job_id=f"rsa_verify_{company}_{scope}", deduplicate=True)
    return waiting


def run_job(company: str, scope: str = "unchecked") -> dict:
    settings = _settings(company)
    names = frappe.get_all("Sales Prospect", filters=pending_filters(company, scope), pluck="name", order_by="modified asc", limit=JOB_LIMIT)
    counts = {verify.VALID: 0, verify.RISKY: 0, verify.INVALID: 0, "undecided": 0}
    for number, name in enumerate(names, start=1):
        try:
            status = check_prospect(name, settings)
            counts[status or "undecided"] += 1
        except Exception:
            frappe.db.rollback()
            frappe.log_error(title="Sales Agent address check failed", reference_doctype="Sales Prospect", reference_name=name)
        if number % COMMIT_EVERY == 0:
            frappe.db.commit()
    frappe.db.commit()
    return counts


def daily() -> None:
    """Every day: check the addresses that have no answer yet, and the ones last checked long ago."""
    for company in frappe.get_all("Sales Agent Settings", pluck="name"):
        try:
            start(company, "unchecked")
            old = frappe.get_all("Sales Prospect", filters={"company": company, "email": ["is", "set"],
                                                            "email_checked_at": ["<", add_days(now_datetime(), -RECHECK_DAYS)]},
                                 pluck="name", limit=200)
            for name in old:
                check_prospect(name)
            frappe.db.commit()
        except Exception:
            frappe.db.rollback()
            frappe.log_error(title="Sales Agent daily address check failed")


def summary(company: str) -> dict:
    base = {"company": company, "email": ["is", "set"], "merged_into": ["is", "not set"]}
    counts = {status: frappe.db.count("Sales Prospect", {**base, "email_status": status}) for status in verify.STATUSES}
    counts["Unchecked"] = frappe.db.count("Sales Prospect", {**base, "email_status": ["is", "not set"]})
    return {"counts": counts, **verify.breakdown(counts)}


def examples(company: str, status: str, limit: int = 30) -> list[dict]:
    if status not in (verify.RISKY, verify.INVALID):
        return []
    rows = frappe.get_all("Sales Prospect", filters={"company": company, "email_status": status, "merged_into": ["is", "not set"]},
                          fields=["name", "email", "contact_name", "business_name", "email_check_note"], order_by="email_checked_at desc",
                          limit=limit)
    return [{"name": r.name, "email": r.email, "person": r.contact_name or r.business_name, "note": r.email_check_note or ""} for r in rows]
