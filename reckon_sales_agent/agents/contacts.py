"""Contact finding: approved leads without an email get one from the business's own website.

Campaigns need a public business email, and many listings carry only a
phone. The Research agent reads the site's contact, about and team pages
(robots.txt respected, same SSRF-safe fetcher as research) and keeps the best
business address: one on the site's own domain first, then a role address
(info@, sales@...) on a free mail provider. Personal-looking and system
addresses are skipped. Each lead is checked at most once a month.
"""

from __future__ import annotations

from urllib.parse import urlsplit

CONTACT_PATHS = ("/contact", "/contact-us", "/contactus", "/about", "/about-us", "/team")
ROLE_PREFIXES = ("info", "sales", "contact", "hello", "office", "admin", "support", "marketing", "business",
                 "enquiry", "enquiries", "inquiry", "mail", "order", "orders")
SKIP_PARTS = ("noreply", "no-reply", "donotreply", "example.", "sentry", "wixpress", "@domain.", "yourname",
              "email@", "user@", "name@")
FREE_MAIL = ("gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com", "ymail.com")
BATCH = 10  # up to 7 pages each; keeps an hourly run short
RECHECK_DAYS = 30


def site_domain(website: str | None) -> str:
    host = (urlsplit(website if "://" in (website or "") else f"https://{website or ''}").hostname or "").lower()
    return host.removeprefix("www.")


def pick_email(emails: list[str], website: str | None) -> str | None:
    """The best business email from a site's pages, or None."""
    domain = site_domain(website)
    usable = [e.lower() for e in emails if "@" in e and not any(part in e.lower() for part in SKIP_PARTS)]
    own = [e for e in usable if domain and (e.split("@")[1] == domain or e.split("@")[1].endswith("." + domain))]
    if own:
        return sorted(own, key=lambda e: (e.split("@")[0] not in ROLE_PREFIXES, e))[0]
    free_roles = [e for e in usable if e.split("@")[1] in FREE_MAIL and e.split("@")[0] in ROLE_PREFIXES]
    if free_roles:
        return sorted(free_roles)[0]
    free = [e for e in usable if e.split("@")[1] in FREE_MAIL]
    return sorted(free)[0] if len(free) == 1 else None  # one free address on a small business's site is its inbox


def contact_urls(website: str) -> list[str]:
    from urllib.parse import urlunsplit

    parts = urlsplit(website if "://" in website else f"https://{website}")
    root = urlunsplit((parts.scheme or "https", parts.netloc, "", "", ""))
    return [root + "/"] + [root + path for path in CONTACT_PATHS]


# --------------------------------------------------------------------------- Frappe side


def missing_email(company: str, limit: int = 2000) -> list[str]:
    import frappe
    from frappe.utils import add_days, nowdate

    return frappe.get_all("Sales Prospect", filters=[
        ["company", "=", company], ["review_status", "=", "Approved"], ["do_not_contact", "=", 0],
        ["email", "is", "not set"], ["website", "is", "set"],
    ], or_filters=[["contact_checked_on", "is", "not set"], ["contact_checked_on", "<", add_days(nowdate(), -RECHECK_DAYS)]],
        pluck="name", limit=limit)


def find_batch(company: str) -> dict:
    found = checked = 0
    for name in missing_email(company, BATCH):
        checked += 1
        found += 1 if find_contact(name) else 0
    return {"checked": checked, "found": found}


def find_contact(name: str) -> str | None:
    import json

    import frappe
    from frappe.utils import now_datetime

    from reckon_sales_agent.constants import USAGE_RESEARCH
    from reckon_sales_agent.research.parser import parse_html
    from reckon_sales_agent.research.runner import _robots_allow
    from reckon_sales_agent.research.url_safety import (
        FetchError,
        UnsafeURL,
        fetch,
        is_reserved_domain,
    )
    from reckon_sales_agent.usage import log_activity, platform_settings, remaining, reserve

    prospect = frappe.get_doc("Sales Prospect", name)
    prospect.db_set("contact_checked_on", now_datetime())
    frappe.db.commit()
    if not prospect.website or is_reserved_domain(prospect.website):
        return None
    platform = platform_settings()
    limits = dict(user_agent=platform.user_agent or "ReckonSalesAgent/1.0", timeout=platform.fetch_timeout or 10,
                  max_bytes=(platform.max_page_kb or 1024) * 1024)
    urls = contact_urls(prospect.website)
    if not _robots_allow(urls[0], limits["user_agent"], limits):
        return None
    emails, phones = [], []
    for url in urls:
        if remaining(prospect.company, USAGE_RESEARCH) <= 0:
            break
        try:
            result = fetch(url, **limits)
        except (UnsafeURL, FetchError):
            continue
        reserve(prospect.company, USAGE_RESEARCH, 1, prospect)
        page = parse_html(result.text, result.url)
        emails.extend(page.emails)
        phones.extend(page.phones)
        best = pick_email(emails, prospect.website)
        if best and site_domain(prospect.website) and best.endswith(site_domain(prospect.website)):
            break  # an address on the business's own domain: good enough
    frappe.db.commit()
    email = pick_email(emails, prospect.website)
    if not email:
        log_activity(prospect.company, "contact_not_found", prospect, f"{len(urls)} pages checked",
                     actor_type="agent", agent="Research")
        return None
    provenance = json.loads(prospect.provenance_json or "{}")
    provenance["email"] = {"source": "company_website", "retrieved_at": str(now_datetime()), "retention_days": None,
                           "attribution": None}
    updates = {"email": email, "provenance_json": json.dumps(provenance, sort_keys=True)}
    if not prospect.phone and phones:
        updates["phone"] = phones[0]
    prospect.db_set(updates)
    if prospect.crm_lead:
        from reckon_sales_agent.crm_sync import fill_empty_lead_fields

        fill_empty_lead_fields(prospect.crm_lead, {"email": email, "phone": updates.get("phone")})
    log_activity(prospect.company, "contact_found", prospect, "Business email found on its website",
                 actor_type="agent", agent="Research", policy_outcome="automatic (research_company)")
    frappe.db.commit()
    return email
