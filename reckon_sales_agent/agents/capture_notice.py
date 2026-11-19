"""Lead capture finished: one email and one Desk notification to the managers, so nobody has to watch the progress page.

A discovery job runs in the background, and the research of the leads it found runs after it. When the job is
Completed and none of its leads is still waiting for research, the Company's managers get one note with the counts and
a link to "Review new leads". Each job is announced once (recorded in the activity log). People who switched the
daily digest off are not emailed.

``compose`` is pure (numbers in, subject and HTML out); ``notify_finished`` gathers the numbers and sends.
"""

from __future__ import annotations

from html import escape

RECENT_DAYS = 3  # older jobs are never announced late


def compose(campaign_name: str, found: int, researched: int, failed: int, qualified: int, url: str) -> tuple[str, str]:
    """(subject, html) for one finished lead capture."""
    name = campaign_name or "Lead capture"
    subject = f"Lead capture finished: {name}, {found} new lead(s)"
    lines = [f"<li><b>{found}</b> new lead(s) found</li>",
             f"<li><b>{researched}</b> website(s) researched</li>"]
    if failed:
        lines.append(f"<li>{failed} website(s) could not be read (those leads stay in review with less detail)</li>")
    if qualified:
        lines.append(f"<li><b>{qualified}</b> lead(s) look like a fit</li>")
    html = (f"<p>The lead capture <b>{escape(name)}</b> has finished.</p><ul>{''.join(lines)}</ul>"
            f"<p><a href=\"{escape(url)}\">Review new leads</a>. Nothing has been sent to anyone: messages always wait "
            f"for a person to approve them.</p>")
    return subject, html


# --------------------------------------------------------------------------- Frappe side


def notify_finished(company: str) -> int:
    """Announce every recently completed discovery job of the Company whose research is done. Returns how many."""
    import frappe
    from frappe.utils import add_to_date, get_url, now_datetime

    from reckon_sales_agent.agents.digest import _email_of, managers
    from reckon_sales_agent.usage import get_settings, log_activity

    settings = get_settings(company)
    if not settings.get("daily_digest"):
        return 0
    since = add_to_date(now_datetime(), days=-RECENT_DAYS)
    sent = 0
    for row in frappe.get_all("Sales Discovery Job", filters={"company": company, "status": "Completed", "finished_at": [">=", since]},
                              fields=["name", "discovery_campaign"], order_by="finished_at asc", limit=20):
        if frappe.db.exists("Sales Agent Activity", {"company": company, "action": "capture_notified",
                                                    "reference_doctype": "Sales Discovery Job", "reference_name": row.name}):
            continue
        scope = {"company": company, "discovery_campaign": row.discovery_campaign}
        if frappe.db.count("Sales Prospect", {**scope, "research_status": "Queued"}):
            continue  # its leads are still being researched
        by_status = dict(frappe.db.sql(
            "select research_status, count(*) from `tabSales Prospect` where company = %s and discovery_campaign = %s "
            "group by research_status", (company, row.discovery_campaign)))
        subject, html = compose(frappe.db.get_value("Sales Discovery Campaign", row.discovery_campaign, "campaign_name") or "",
                                frappe.db.count("Sales Prospect", scope), int(by_status.get("Done", 0)), int(by_status.get("Failed", 0)),
                                frappe.db.count("Sales Prospect", {**scope, "qualification_status": "Qualified"}),
                                get_url("/desk/sales-agent/sales-review"))
        for user in managers(company, settings):
            email = _email_of(user)
            if email:
                frappe.sendmail(recipients=[email], subject=subject, message=html, delayed=True,
                                reference_doctype="Sales Discovery Job", reference_name=row.name)
            if frappe.db.exists("User", user):
                frappe.get_doc({"doctype": "Notification Log", "for_user": user, "type": "Alert", "subject": subject,
                                "email_content": html, "document_type": "Sales Discovery Job", "document_name": row.name,
                                "from_user": "Administrator"}).insert(ignore_permissions=True)
        log_activity(company, "capture_notified", frappe.get_doc("Sales Discovery Job", row.name), subject, actor_type="system",
                     agent="Research")
        sent += 1
    if sent:
        frappe.db.commit()
    return sent


def safely_notify(company: str) -> None:
    """Called from the background jobs: a failure here must never break discovery or research."""
    try:
        notify_finished(company)
    except Exception:
        import frappe

        frappe.log_error(title="Sales Agent capture notice failed")
