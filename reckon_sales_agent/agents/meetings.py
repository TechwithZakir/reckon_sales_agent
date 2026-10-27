"""Meeting agent: from "interested" to a booked demo, with reminders and a follow-up when nobody shows up.

When a lead is interested (a call outcome, or a reply asking for a meeting) the agent:

1. proposes three slots from the salesperson's calendar (Frappe Events), inside the Company's meeting days and
   hours (Bangladesh: Sunday to Thursday) and at least two hours ahead;
2. drafts the invitation on the lead's channel (email, or a call task with the slots when there is no email);
   the invitation reaches the customer only after a person approves it, like any outbound message;
3. books the meeting when the salesperson picks the slot the lead chose: a calendar Event with the lead as a
   participant and a CRM task;
4. reminds the salesperson the day before and an hour before (Desk notifications), and after the meeting asks
   what happened: held, no-show (a follow-up with new slots is drafted), or cancelled.

``propose_slots`` and ``parse_hours`` are pure.
"""

from __future__ import annotations

from datetime import datetime, timedelta

DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def parse_days(value: str | None) -> set[int]:
    """'Sun,Mon,Tue' -> weekday numbers (Monday is 0)."""
    days = {DAY_NAMES.index(d.strip()[:3].title()) for d in (value or "").split(",")
            if d.strip()[:3].title() in DAY_NAMES}
    return days or {6, 0, 1, 2, 3}  # Bangladesh working week: Sunday to Thursday


def parse_hours(value: str | None) -> tuple[int, int]:
    """'10:00-17:00' -> (600, 1020) minutes from midnight."""
    try:
        start, end = (value or "10:00-17:00").split("-")
        to_min = lambda t: int(t.split(":")[0]) * 60 + int((t.split(":") + ["0"])[1])  # noqa: E731
        first, last = to_min(start.strip()), to_min(end.strip())
        return (first, last) if 0 <= first < last <= 24 * 60 else (600, 1020)
    except (ValueError, IndexError):
        return 600, 1020


def propose_slots(now: datetime, busy: list[tuple[datetime, datetime]], days: set[int], hours: tuple[int, int],
                  minutes: int = 30, count: int = 3, lead: timedelta = timedelta(hours=2),
                  horizon_days: int = 10) -> list[datetime]:
    """Free starts, spread over different days where possible, on the half hour."""
    earliest = now + lead
    slots: list[datetime] = []
    used_days: set = set()
    for spread in (True, False):  # first one slot per day, then fill from the earliest days
        day = earliest.replace(hour=0, minute=0, second=0, microsecond=0)
        for _ in range(horizon_days):
            if day.weekday() in days and not (spread and day.date() in used_days):
                start = day + timedelta(minutes=hours[0])
                while start + timedelta(minutes=minutes) <= day + timedelta(minutes=hours[1]):
                    end = start + timedelta(minutes=minutes)
                    clash = any(s < end and start < e for s, e in busy)
                    if start >= earliest and not clash and start not in slots:
                        slots.append(start)
                        used_days.add(day.date())
                        if len(slots) >= count:
                            return sorted(slots)
                        if spread:
                            break
                    start += timedelta(minutes=30)
            day += timedelta(days=1)
    return sorted(slots)


def slot_label(slot: datetime) -> str:
    return slot.strftime("%A %d %B, %I:%M %p").replace(" 0", " ")


# --------------------------------------------------------------------------- Frappe side


def start_meeting(prospect_name: str, source: str, member: str | None = None) -> str | None:
    """Propose slots and draft the invitation for an interested lead; returns the meeting, or None if one is open."""
    import json

    import frappe
    from frappe.utils import add_to_date, get_datetime, now_datetime

    from reckon_sales_agent.usage import get_settings, log_activity

    prospect = frappe.get_doc("Sales Prospect", prospect_name)
    if frappe.db.exists("Sales Meeting", {"prospect": prospect.name, "status": ["in", ["Proposed", "Booked"]]}):
        return None
    settings = get_settings(prospect.company)
    owner = settings.get("task_assignee") or prospect.owner
    minutes = int(settings.get("meeting_minutes") or 30)
    now = now_datetime()
    busy = [(get_datetime(e.starts_on), get_datetime(e.ends_on or add_to_date(e.starts_on, minutes=minutes)))
            for e in frappe.get_all("Event", filters=[["owner", "=", owner], ["status", "=", "Open"],
                                                     ["starts_on", ">=", add_to_date(now, days=-1)],
                                                     ["starts_on", "<=", add_to_date(now, days=14)]],
                                    fields=["starts_on", "ends_on"], limit=500)]
    slots = propose_slots(now, busy, parse_days(settings.get("meeting_days")), parse_hours(settings.get("meeting_hours")),
                          minutes)
    meeting = frappe.get_doc({
        "doctype": "Sales Meeting", "company": prospect.company, "title": f"Demo: {prospect.business_name}"[:140],
        "status": "Proposed", "prospect": prospect.name, "crm_lead": prospect.crm_lead, "assigned_to": owner,
        "mode": "Video call" if settings.get("meeting_link") else "Phone", "location": settings.get("meeting_link"),
        "duration_minutes": minutes, "source": source[:140],
        "slot_options": json.dumps([str(s) for s in slots]),
    }).insert(ignore_permissions=True)
    message = _draft_invitation(meeting, prospect, slots, settings)
    if message:
        meeting.db_set("invite_message", message)
    log_activity(prospect.company, "meeting_proposed", meeting,
                 f"{len(slots)} slot(s): " + "; ".join(slot_label(s) for s in slots), actor_type="agent",
                 agent="Engagement", policy_outcome="invitation drafted: a person approves")
    return meeting.name


def _draft_invitation(meeting, prospect, slots, settings) -> str | None:
    """The invitation on the lead's channel, as a Draft (email) or a call task listing the slots."""
    import frappe
    from frappe.utils import get_url

    from reckon_sales_agent.agents.omni import conversations_campaign, member_for
    from reckon_sales_agent.campaigns.engine import record_event
    from reckon_sales_agent.campaigns.templates import footer, text_to_html
    from reckon_sales_agent.providers.channels import create_task

    times = "\n".join(f"- {slot_label(s)}" for s in slots) or "- a time that suits you"
    sender = settings.sender_name or prospect.company
    where = f"\nWe will meet on {meeting.location}." if meeting.location else ""
    if not prospect.email:
        if prospect.phone:
            create_task(prospect.name, f"Agree a demo time: {prospect.business_name}",
                        f"They are interested. Offer one of these times:\n{times}\nThen book it in Meetings.",
                        settings, priority="High")
        return None
    campaign = conversations_campaign(prospect.company)
    member = member_for(prospect.company, campaign, prospect)
    token = frappe.db.get_value("Sales Campaign Member", member, "unsubscribe_token")
    text = (f"Thank you for your interest. Could we show you a short {meeting.duration_minutes}-minute demo? "
            f"Any of these times works for us:\n{times}{where}\n\nJust reply with the time that suits you.\n\n{sender}")
    body = text_to_html(frappe.utils.escape_html(text)) + footer(
        sender, settings.physical_address, get_url(f"/api/method/reckon_sales_agent.api.unsubscribe?token={token}"))
    message = frappe.get_doc({
        "doctype": "Sales Outreach Message", "company": prospect.company, "campaign": campaign, "member": member,
        "prospect": prospect.name, "step_no": 0, "channel": "Email", "recipient": prospect.email,
        "subject": f"A short demo for {prospect.business_name}"[:140], "body": body, "is_reply": 1,
        "status": "Draft", "idempotency_key": f"meeting:{meeting.name}",
    }).insert(ignore_permissions=True)
    record_event(message, "drafted", f"draft:{message.name}", detail="Meeting invitation")
    return message.name


def book(meeting_name: str, starts_on: str) -> str:
    """Book the meeting at the time the lead chose: a calendar Event and a CRM task."""
    import frappe
    from frappe import _
    from frappe.utils import add_to_date, get_datetime, now_datetime

    from reckon_sales_agent.providers.channels import create_task
    from reckon_sales_agent.usage import get_settings, log_activity

    meeting = frappe.get_doc("Sales Meeting", meeting_name)
    if meeting.status not in ("Proposed", "Booked", "No-show"):
        frappe.throw(_("This meeting is {0}.").format(meeting.status))
    start = get_datetime(starts_on)
    if start < now_datetime():
        frappe.throw(_("Choose a time in the future."))
    end = add_to_date(start, minutes=int(meeting.duration_minutes or 30))
    prospect = frappe.get_doc("Sales Prospect", meeting.prospect)
    event = frappe.get_doc({
        "doctype": "Event", "subject": meeting.title, "event_category": "Meeting", "event_type": "Private",
        "starts_on": start, "ends_on": end, "status": "Open", "owner": meeting.assigned_to,
        "description": f"{meeting.mode}{': ' + meeting.location if meeting.location else ''}<br>"
                       f"{frappe.utils.escape_html(prospect.business_name)} · {prospect.phone or ''} {prospect.email or ''}",
        "event_participants": [{"reference_doctype": "CRM Lead", "reference_docname": prospect.crm_lead}]
        if prospect.crm_lead else [],
    }).insert(ignore_permissions=True)
    if meeting.event and frappe.db.exists("Event", meeting.event):
        frappe.db.set_value("Event", meeting.event, "status", "Cancelled")  # rescheduled
    meeting.db_set({"status": "Booked", "starts_on": start, "ends_on": end, "event": event.name,
                    "reminder_day_sent": 0, "reminder_hour_sent": 0})
    settings = get_settings(meeting.company)
    days = max(0, (start.date() - now_datetime().date()).days)
    create_task(prospect.name, f"Demo at {start:%d %b %H:%M}: {prospect.business_name}",
                f"{meeting.mode} {meeting.location or ''}".strip(),
                frappe._dict({**settings.as_dict(), "task_due_days": days, "task_assignee": meeting.assigned_to}),
                priority="High")
    log_activity(meeting.company, "meeting_booked", meeting, f"{start:%Y-%m-%d %H:%M}", agent="Engagement")
    return event.name


def record_outcome(meeting_name: str, outcome: str, notes: str = "") -> None:
    import frappe
    from frappe import _

    from reckon_sales_agent.usage import log_activity

    if outcome not in ("Held", "No-show", "Cancelled"):
        frappe.throw(_("Unknown outcome."))
    meeting = frappe.get_doc("Sales Meeting", meeting_name)
    meeting.db_set({"status": outcome, "outcome_notes": (notes or "")[:2000]})
    if meeting.event and frappe.db.exists("Event", meeting.event):
        frappe.db.set_value("Event", meeting.event, "status", "Completed" if outcome == "Held" else "Cancelled")
    log_activity(meeting.company, f"meeting_{outcome.lower().replace('-', '_')}", meeting, notes or outcome,
                 agent="Engagement")
    if outcome == "Held":
        from reckon_sales_agent.qualification.service import qualify_prospect

        qualify_prospect(meeting.prospect)
    elif outcome == "No-show":
        # Offer new times: a fresh proposal (drafted, approved by a person before it goes out).
        start_meeting(meeting.prospect, f"no-show follow-up for {meeting.name}")


def send_reminders() -> int:
    """Hourly: remind the salesperson a day before and an hour before; ask for the outcome afterwards."""
    import frappe
    from frappe.utils import add_to_date, now_datetime

    now = now_datetime()
    sent = 0
    for m in frappe.get_all("Sales Meeting", filters={"status": "Booked", "starts_on": [">=", add_to_date(now, hours=-3)]},
                            fields=["name", "title", "starts_on", "assigned_to", "reminder_day_sent",
                                    "reminder_hour_sent", "company", "location"], limit=1000):
        delta = m.starts_on - now
        kind = None
        if timedelta(0) < delta <= timedelta(hours=1, minutes=5) and not m.reminder_hour_sent:
            kind, field = "in an hour", "reminder_hour_sent"
        elif timedelta(hours=1) < delta <= timedelta(hours=24) and not m.reminder_day_sent:
            kind, field = "tomorrow" if m.starts_on.date() != now.date() else "today", "reminder_day_sent"
        if not kind or not m.assigned_to:
            continue
        frappe.get_doc({"doctype": "Notification Log", "for_user": m.assigned_to, "type": "Alert",
                        "subject": f"{m.title} {kind} at {m.starts_on:%H:%M}" + (f" · {m.location}" if m.location else ""),
                        "document_type": "Sales Meeting", "document_name": m.name}).insert(ignore_permissions=True)
        frappe.db.set_value("Sales Meeting", m.name, field, 1, update_modified=False)
        sent += 1
    frappe.db.commit()
    return sent
