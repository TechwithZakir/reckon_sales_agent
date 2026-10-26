"""Daily digest: the agents report each morning, so nobody has to open the Agent Studio to know what happened.

Two notes per Company, by email and as a Desk notification, at most once a day per person:

- managers (Company Admins and Managers, whoever turned autopilot on, and any extra recipients): what the
  agents did in the last 24 hours, the pilots' state, and every decision waiting for a person;
- each salesperson with call tasks: today's and overdue calls with a tap-to-call number.

The builders are pure (data in, subject and HTML out); ``send_all`` gathers the data and sends.
"""

from __future__ import annotations

from html import escape

# Activity actions summed into the "last 24 hours" lines: (label, actions).
WORK_LINES = (
    ("new leads found", ("discovery_completed",)),
    ("websites researched", ("research_done", "research_partial")),
    ("leads judged by AI", ("prospect_triaged",)),
    ("strong leads approved automatically", ("prospect_auto_approved",)),
    ("emails found", ("contact_found",)),
    ("campaigns written", ("content_sequence_written",)),
    ("replies handled", ("reply_question", "reply_interested", "reply_meeting_request", "reply_objection",
                         "reply_not_interested", "reply_complaint")),
    ("calls logged", ("call_interested", "call_callback", "call_not_interested", "call_wrong_number",
                      "call_no_answer")),
    ("interested on a call", ("call_interested",)),
    ("search lessons learned", ("targeting_learned",)),
)


def _singular(label: str) -> str:
    """'calls logged' -> 'call logged' (live preview read "1 calls logged")."""
    words = {"replies": "reply", "leads": "lead", "websites": "website", "emails": "email", "calls": "call",
             "campaigns": "campaign", "lessons": "lesson"}
    return " ".join(words.get(word, word) for word in label.split())


def work_lines(action_counts: dict[str, int], new_leads: int = 0) -> list[str]:
    lines = []
    for label, actions in WORK_LINES:
        count = new_leads if label == "new leads found" else sum(int(action_counts.get(a) or 0) for a in actions)
        if count:
            lines.append(f"{count} {_singular(label) if count == 1 else label}")
    return lines


def manager_digest(company: str, work: list[str], asks: list[dict], pilots: list[dict], url: str) -> tuple[str, str]:
    """(subject, HTML) for a manager. ``asks``: {"title", "detail"}; ``pilots``: {"name", "summary"}."""
    subject = f"Sales agents: {len(asks)} decision(s) waiting" if asks else "Sales agents: nothing needs you today"
    parts = [f"<p>Good morning. Here is what your sales agents did for {escape(company)} in the last 24 hours.</p>"]
    parts.append("<h3>Done by the agents</h3>" + (
        "<ul>" + "".join(f"<li>{escape(line)}</li>" for line in work) + "</ul>" if work
        else "<p>A quiet day: nothing new.</p>"))
    if asks:
        parts.append("<h3>Waiting for you</h3><ul>" + "".join(
            f"<li><b>{escape(a['title'])}</b>{': ' + escape(a['detail']) if a.get('detail') else ''}</li>"
            for a in asks) + "</ul>")
    if pilots:
        parts.append("<h3>Pilots</h3><ul>" + "".join(
            f"<li><b>{escape(p['name'])}</b>: {escape(p.get('summary') or 'not measured yet')}</li>" for p in pilots)
            + "</ul>")
    parts.append(f'<p><a href="{escape(url)}">Open the Agent Studio</a></p>')
    return subject, "".join(parts)


def caller_digest(name: str, calls: list[dict], url: str, today: str) -> tuple[str, str]:
    """(subject, HTML) for a salesperson. ``calls``: {"business", "phone", "due", "title"}."""
    overdue = [c for c in calls if str(c.get("due") or "")[:10] < today]
    subject = f"Today's calls: {len(calls)}" + (f" ({len(overdue)} overdue)" if overdue else "")
    rows = "".join(
        f"<li><b>{escape(c.get('business') or '')}</b>"
        + (f' · <a href="tel:{escape(c["phone"])}">{escape(c["phone"])}</a>' if c.get("phone") else "")
        + (" · <i>overdue</i>" if c in overdue else "")
        + (f"<br><span style=\"color:#666\">{escape(c['title'])}</span>" if c.get("title") else "") + "</li>"
        for c in calls)
    body = (f"<p>Good morning {escape(name)}. You have {len(calls)} call(s) to make today. Each has a script "
            f"in the Agent Studio; after each call, pick what happened and the agents do the rest.</p>"
            f"<ul>{rows}</ul><p><a href=\"{escape(url)}\">Open your calls</a></p>")
    return subject, body


# --------------------------------------------------------------------------- Frappe side


def managers(company: str, settings) -> list[str]:
    import frappe

    users = set(frappe.get_all("Tenant User Assignment", filters={
        "company": company, "active": 1, "role_profile": ["in", ["Company Admin", "Company Manager"]]},
        pluck="user")) if frappe.db.exists("DocType", "Tenant User Assignment") else set()
    if settings.get("autopilot_consent_by"):
        users.add(settings.autopilot_consent_by)
    for line in (settings.get("digest_recipients") or "").replace(",", "\n").splitlines():
        if line.strip():
            users.add(line.strip())
    return sorted(u for u in users if u != "Guest")


def _email_of(user: str) -> str | None:
    import frappe

    if "@" in user and not frappe.db.exists("User", user):
        return user  # an extra recipient outside the site
    email, enabled = frappe.db.get_value("User", user, ["email", "enabled"]) or (None, 0)
    return email if enabled and email and "@" in email else None


def _already_sent(company: str, user: str, kind: str) -> bool:
    import frappe
    from frappe.utils import nowdate

    return bool(frappe.db.exists("Sales Agent Activity", {
        "company": company, "action": f"digest_{kind}", "summary": f"{user} {nowdate()}"}))


def _deliver(company: str, user: str, kind: str, subject: str, html: str) -> bool:
    import frappe
    from frappe.utils import nowdate

    from reckon_sales_agent.usage import log_activity

    email = _email_of(user)
    if email:
        frappe.sendmail(recipients=[email], subject=subject, message=html, delayed=True,
                        reference_doctype="Company", reference_name=company)
    if frappe.db.exists("User", user):
        frappe.get_doc({"doctype": "Notification Log", "for_user": user, "type": "Alert", "subject": subject,
                        "email_content": html, "document_type": "Company", "document_name": company,
                        "from_user": "Administrator"}).insert(ignore_permissions=True)
    log_activity(company, f"digest_{kind}", None, f"{user} {nowdate()}", actor_type="agent", agent="Analytics")
    return True


def send_company(company: str, only_user: str | None = None, force: bool = False, as_manager: bool = True) -> dict:
    """Send today's digests for one Company; ``only_user`` sends just that person's (a preview from the Studio),
    including the manager digest only ``as_manager``."""
    import frappe
    from frappe.utils import add_to_date, get_url, now_datetime, nowdate

    from reckon_sales_agent.agents.orchestrator import ASK, collect_state, plan
    from reckon_sales_agent.usage import get_settings

    settings = get_settings(company)
    url = get_url("/desk/sales-agent")
    sent = {"manager": 0, "caller": 0}
    since = add_to_date(now_datetime(), hours=-24)
    counts: dict[str, int] = {}
    for action in frappe.get_all("Sales Agent Activity", filters={"company": company, "creation": [">=", since]},
                                 pluck="action", limit=20000):
        counts[action] = counts.get(action, 0) + 1
    new_leads = frappe.db.count("Sales Prospect", {"company": company, "creation": [">=", since]})
    asks = [{"title": s.title, "detail": s.detail} for s in plan(collect_state(company)) if s.kind == ASK]
    pilots = [{"name": p.campaign_name, "summary": p.pilot_summary} for p in frappe.get_all(
        "Sales Campaign", filters={"company": company, "status": "Active", "pilot_mode": 1},
        fields=["campaign_name", "pilot_summary"], limit=10)]
    subject, html = manager_digest(company, work_lines(counts, new_leads), asks, pilots, url)
    for user in (([only_user] if as_manager else []) if only_user else managers(company, settings)):
        if force or not _already_sent(company, user, "manager"):
            sent["manager"] += _deliver(company, user, "manager", subject, html)

    for user, calls in _calls_by_person(company).items():
        if only_user and user != only_user:
            continue
        if force or not _already_sent(company, user, "caller"):
            name = frappe.db.get_value("User", user, "first_name") or user
            subject, html = caller_digest(name, calls, url, nowdate())
            sent["caller"] += _deliver(company, user, "caller", subject, html)
    frappe.db.commit()
    return sent


def _calls_by_person(company: str) -> dict[str, list[dict]]:
    """Open call tasks due today or earlier, by assignee (ToDos on prospects and CRM call tasks)."""
    import frappe
    from frappe.utils import nowdate

    from reckon_sales_agent.campaigns.calls import call_message

    out: dict[str, list[dict]] = {}
    for todo in frappe.get_all("ToDo", filters={"reference_type": "Sales Prospect", "status": "Open",
                                                "rsa_company": company, "date": ["<=", nowdate()]},
                               fields=["name", "allocated_to", "date", "reference_name", "description"], limit=500):
        if not call_message(todo.name):
            continue
        prospect = frappe.db.get_value("Sales Prospect", todo.reference_name, ["business_name", "phone"],
                                       as_dict=True) or {}
        out.setdefault(todo.allocated_to, []).append({
            "business": prospect.get("business_name"), "phone": prospect.get("phone"), "due": str(todo.date),
            "title": frappe.utils.strip_html((todo.description or "").split("<br>")[0])[:140]})
    leads = {r.crm_lead: r for r in frappe.get_all("Sales Prospect", filters={"company": company,
                                                                              "crm_lead": ["is", "set"]},
                                                    fields=["crm_lead", "business_name", "phone"], limit=20000)}
    if leads:
        for task in frappe.get_all("CRM Task", filters={
                "reference_doctype": "CRM Lead", "reference_docname": ["in", list(leads)],
                "status": ["in", ["Backlog", "Todo", "In Progress"]], "due_date": ["<=", f"{nowdate()} 23:59:59"]},
                fields=["name", "assigned_to", "due_date", "reference_docname", "title"], limit=500):
            if not task.assigned_to or not call_message(task.name):
                continue
            lead = leads[task.reference_docname]
            out.setdefault(task.assigned_to, []).append({"business": lead.business_name, "phone": lead.phone,
                                                         "due": str(task.due_date), "title": task.title})
    return out


def send_all() -> None:
    """Daily (08:00 server time): every Company with the digest on."""
    import frappe

    from reckon_sales_agent.usage import NotEntitled, assert_entitled

    for company in frappe.get_all("Sales Agent Settings", filters={"enabled": 1, "daily_digest": 1},
                                  pluck="company"):
        try:
            assert_entitled(company)
            send_company(company)
        except NotEntitled:
            frappe.db.rollback()
        except Exception:
            frappe.db.rollback()
            frappe.log_error(title="Sales Agent daily digest failed", reference_doctype="Company",
                             reference_name=company)
