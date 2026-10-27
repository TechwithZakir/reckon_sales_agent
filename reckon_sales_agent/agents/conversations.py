"""Conversation desk: each lead's conversation has a status, an owner, tags and an AI mode.

- **Status**: Open while the lead is talking; a person resolves it; a new message from the lead re-opens it.
- **Owner**: new conversations go to whichever of the Company's chat agents has the fewest open ones (when
  automatic assignment is on); a person can reassign. The owner is notified when a conversation lands on them.
- **AI mode** (per conversation, else the Company's default):
  - *Autopilot*: the AI answers routine questions at once (fast-answer policy); anything it may not answer goes
    to the owner with the reason and the "needs-human" tag.
  - *Suggest only*: the AI drafts, a person sends.
  - *Human only*: no AI. When a person writes a reply themselves, the conversation switches to Human only until
    they hand it back.
- **Tags**: Frappe's own document tags, so they work in list views and filters too.

``effective_mode``, ``pick_agent`` and ``parse_agents`` are pure.
"""

from __future__ import annotations

import re

MODES = ("Company default", "Autopilot", "Suggest only", "Human only")
NEEDS_HUMAN = "needs-human"
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def effective_mode(mode: str | None, company_autopilot: bool) -> str:
    if mode in ("Autopilot", "Suggest only", "Human only"):
        return mode
    return "Autopilot" if company_autopilot else "Suggest only"


def parse_agents(text: str | None) -> list[str]:
    return [line.strip().lower() for line in (text or "").splitlines() if EMAIL.match(line.strip())]


def pick_agent(agents: list[str], open_counts: dict[str, int]) -> str | None:
    """The agent with the fewest open conversations (the list order breaks ties)."""
    if not agents:
        return None
    return min(agents, key=lambda a: (open_counts.get(a, 0), agents.index(a)))


def parse_tags(value: str | None) -> list[str]:
    return [t for t in (value or "").split(",") if t.strip()]


def clean_tag(tag: str) -> str:
    return re.sub(r"[^\w\- ঀ-৿]", "", (tag or "").strip().lower())[:40]


# --------------------------------------------------------------------------- Frappe side


def get(company: str, prospect: str, create: bool = True):
    import frappe

    name = frappe.db.get_value("Sales Conversation", {"company": company, "prospect": prospect})
    if name:
        return frappe.get_doc("Sales Conversation", name)
    if not create:
        return None
    title = frappe.db.get_value("Sales Prospect", prospect, "business_name") or prospect
    doc = frappe.get_doc({"doctype": "Sales Conversation", "company": company, "prospect": prospect,
                          "title": title[:140], "status": "Open"})
    doc.flags.ignore_permissions = True
    return doc.insert(ignore_permissions=True)


def mode_for(company: str, prospect: str) -> str:
    from reckon_sales_agent.usage import get_settings

    doc = get(company, prospect, create=False)
    return effective_mode(doc.ai_mode if doc else None, bool(get_settings(company).get("chat_auto_answer")))


def touch_inbound(company: str, prospect: str, channel: str, at=None) -> str:
    """The lead wrote: open (or re-open) the conversation and make sure someone owns it."""
    from frappe.utils import now_datetime

    from reckon_sales_agent.usage import get_settings

    doc = get(company, prospect)
    updates = {"status": "Open", "last_channel": channel, "last_inbound_at": at or now_datetime()}
    if doc.status == "Resolved":
        updates["resolved_on"] = None
    settings = get_settings(company)
    if not doc.assigned_to and settings.get("auto_assign", 1):
        agents = parse_agents(settings.get("chat_agents"))
        if agents:
            updates["assigned_to"] = pick_agent(agents, _open_counts(company, agents))
    doc.db_set(updates)
    if updates.get("assigned_to"):
        notify(doc, updates["assigned_to"], f"New conversation on {channel}: {doc.title}")
    return doc.name


def _open_counts(company: str, agents: list[str]) -> dict[str, int]:
    import frappe

    counts: dict[str, int] = {}
    for user in frappe.get_all("Sales Conversation", filters={"company": company, "status": "Open",
                                                              "assigned_to": ["in", agents]},
                               pluck="assigned_to", limit=100000):
        counts[user] = counts.get(user, 0) + 1
    return counts


def notify(doc, user: str, subject: str) -> None:
    import frappe

    frappe.get_doc({"doctype": "Notification Log", "for_user": user, "type": "Assignment", "from_user": "Administrator",
                    "document_type": "Sales Conversation", "document_name": doc.name,
                    "subject": subject[:140]}).insert(ignore_permissions=True)


def handoff(company: str, prospect: str, reason: str) -> None:
    """The AI may not answer this one: tag it, make sure someone owns it, and tell them why."""
    from reckon_sales_agent.usage import get_settings

    doc = get(company, prospect)
    owner = doc.assigned_to
    if not owner:
        settings = get_settings(company)
        agents = parse_agents(settings.get("chat_agents"))
        owner = pick_agent(agents, _open_counts(company, agents)) if agents else settings.get("task_assignee")
    doc.db_set({"handoff_reason": reason[:500], "assigned_to": owner, "status": "Open"})
    add_tag(doc.name, NEEDS_HUMAN)
    if owner:
        notify(doc, owner, f"Needs you: {doc.title} — {reason}")


def add_tag(name: str, tag: str) -> None:
    from frappe.desk.doctype.tag.tag import add_tag as frappe_add_tag

    tag = clean_tag(tag)
    if tag:
        frappe_add_tag(tag, "Sales Conversation", name)


def remove_tag(name: str, tag: str) -> None:
    from frappe.desk.doctype.tag.tag import remove_tag as frappe_remove_tag

    frappe_remove_tag(clean_tag(tag), "Sales Conversation", name)


def by_prospect(company: str) -> dict[str, dict]:
    """Conversation fields for the inbox list, by lead."""
    import frappe

    fields = ["name", "prospect", "status", "assigned_to", "ai_mode", "handoff_reason", "_user_tags"]
    return {r.prospect: {**r, "tags": parse_tags(r.pop("_user_tags", ""))}
            for r in frappe.get_all("Sales Conversation", filters={"company": company}, fields=fields, limit=100000)}


def agents_for(company: str) -> list[dict]:
    """Who a conversation can be assigned to: the Company's chat agents and its users."""
    import frappe

    from reckon_sales_agent.usage import get_settings

    users = parse_agents(get_settings(company).get("chat_agents"))
    if frappe.db.exists("DocType", "Tenant User Assignment"):
        users += [u for u in frappe.get_all("Tenant User Assignment", filters={"company": company, "active": 1},
                                            pluck="user", limit=500) if u not in users]
    names = dict(frappe.get_all("User", filters={"name": ["in", users or [""]], "enabled": 1},
                                fields=["name", "full_name"], as_list=True))
    return [{"user": u, "name": names[u] or u} for u in users if u in names]
