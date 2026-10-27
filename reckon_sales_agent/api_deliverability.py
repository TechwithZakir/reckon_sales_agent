"""Email health for the Message Templates page: DNS checks of the sending domain, warm-up and safe mode."""

from __future__ import annotations

import frappe

from reckon_sales_agent.tenant import current_company
from reckon_sales_agent.usage import get_settings


@frappe.whitelist()
def email_health(domain: str | None = None, selector: str | None = None) -> dict:
    from reckon_sales_agent.agents.deliverability import check_domain, today_email_limit

    company = current_company()
    settings = get_settings(company)
    if not domain:
        account = frappe.db.get_value("Email Account", {"enable_outgoing": 1, "default_outgoing": 1}, "email_id") \
            or frappe.db.get_value("Email Account", {"enable_outgoing": 1}, "email_id")
        domain = account.split("@")[-1] if account else ""
    result = check_domain(domain, selector) if domain else {"domain": "", "checks": [],
                                                           "error": "No outgoing email account yet."}
    return {**result, "warmup": {"enabled": bool(settings.get("warmup_enabled")),
                                 "first_send_on": settings.get("first_send_on"),
                                 "today_limit": today_email_limit(settings)},
            "safe_mode": {"enabled": bool(settings.get("allowlist_only")),
                          "count": len([x for x in (settings.get("outbound_allowlist") or "").splitlines() if x.strip()])},
            "outbound_enabled": bool(settings.outbound_enabled)}
