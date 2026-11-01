"""Lead ownership: one salesperson owns a lead across its calls, follow-ups, conversation and CRM lead.

Who owns a lead, first match wins:

1. its owner already (``Sales Prospect.sales_owner``), once set it sticks;
2. the CRM lead's owner;
3. the person who owns its conversation;
4. with team routing on, the least-busy person on the Company's sales team (open call tasks, CRM tasks and
   conversations counted), so a new lead is shared out like a new chat;
5. the salesperson the Company named for calls;
6. whoever found the lead.

Steps 1 to 4 make the choice stick, so every later task and chat for that lead goes to the same person.
Reassigning a lead (from Conversations) moves its open tasks, its conversation and its CRM lead owner too.
``resolve_owner`` is pure.
"""

from __future__ import annotations

TEAM = "Share across the team"
STICKY = ("owner", "crm", "conversation", "team")


def resolve_owner(sticky: str | None, crm_owner: str | None, conversation_owner: str | None, team: list[str],
                  counts: dict[str, int], routing: str | None, named: str | None) -> tuple[str | None, str]:
    """(user, how) for a lead. ``how`` says which rule chose: owner, crm, conversation, team, named or none."""
    from reckon_sales_agent.agents.conversations import pick_agent

    for user, how in ((sticky, "owner"), (crm_owner, "crm"), (conversation_owner, "conversation")):
        if user:
            return user, how
    if routing == TEAM and team:
        return pick_agent(team, counts), "team"
    if named:
        return named, "named"
    return None, "none"


# --------------------------------------------------------------------------- Frappe side


def _enabled(user: str | None) -> str | None:
    import frappe

    return user if user and user not in ("Guest",) and frappe.db.get_value("User", user, "enabled") else None


def team(settings) -> list[str]:
    from reckon_sales_agent.agents.conversations import parse_agents

    return [u for u in parse_agents(settings.get("chat_agents")) if _enabled(u)]


def workload(company: str, users: list[str]) -> dict[str, int]:
    """Open call tasks, CRM tasks and conversations per person."""
    import frappe

    counts = {u: 0 for u in users}
    if not users:
        return counts
    rows = frappe.get_all("ToDo", filters={"status": "Open", "allocated_to": ["in", users], "rsa_company": company},
                          pluck="allocated_to", limit=100000)
    rows += frappe.get_all("CRM Task", filters={"status": ["in", ["Backlog", "Todo", "In Progress"]],
                                                "assigned_to": ["in", users]}, pluck="assigned_to", limit=100000)
    rows += frappe.get_all("Sales Conversation", filters={"company": company, "status": "Open",
                                                          "assigned_to": ["in", users]}, pluck="assigned_to",
                           limit=100000)
    for user in rows:
        counts[user] = counts.get(user, 0) + 1
    return counts


def owner_for(prospect_name: str, settings=None, fallback: bool = True, sticky_only: bool = False) -> str | None:
    """The lead's owner (choosing and keeping one when the rules allow); see the module docstring.

    ``sticky_only``: only an owner rules 1 to 4 give (a chat with no such owner is shared among the team instead
    of going to the one salesperson named for calls)."""
    import frappe

    from reckon_sales_agent.usage import get_settings

    row = frappe.db.get_value("Sales Prospect", prospect_name, ["company", "sales_owner", "crm_lead", "owner"],
                              as_dict=True)
    if not row:
        return None
    settings = settings or get_settings(row.company)
    crm_owner = _enabled(frappe.db.get_value("CRM Lead", row.crm_lead, "lead_owner")) if row.crm_lead else None
    convo = _enabled(frappe.db.get_value("Sales Conversation", {"company": row.company, "prospect": prospect_name},
                                         "assigned_to"))
    members = team(settings)
    routing = settings.get("call_routing")
    user, how = resolve_owner(_enabled(row.sales_owner), crm_owner, convo, members,
                              workload(row.company, members) if routing == TEAM and members else {},
                              routing, _enabled(settings.get("task_assignee")))
    if user and how in STICKY and how != "owner":
        set_owner(prospect_name, user)
    if sticky_only and how not in STICKY:
        return None
    if user or not fallback:
        return user
    return row.owner if _enabled(row.owner) else "Administrator"


def set_owner(prospect_name: str, user: str) -> None:
    """Record the owner on the lead, and on its CRM lead when that has none yet."""
    import frappe

    frappe.db.set_value("Sales Prospect", prospect_name, "sales_owner", user, update_modified=False)
    lead = frappe.db.get_value("Sales Prospect", prospect_name, "crm_lead")
    if lead and not frappe.db.get_value("CRM Lead", lead, "lead_owner"):
        frappe.db.set_value("CRM Lead", lead, "lead_owner", user, update_modified=False)


def reassign(company: str, prospect_name: str, user: str | None) -> int:
    """Give the whole lead to ``user``: its owner, CRM lead, open call tasks, CRM tasks and conversation.

    Returns how many open tasks moved."""
    import frappe

    if not user:
        frappe.db.set_value("Sales Prospect", prospect_name, "sales_owner", None, update_modified=False)
        return 0
    frappe.db.set_value("Sales Prospect", prospect_name, "sales_owner", user, update_modified=False)
    lead = frappe.db.get_value("Sales Prospect", prospect_name, "crm_lead")
    moved = 0
    for todo in frappe.get_all("ToDo", filters={"reference_type": "Sales Prospect", "reference_name": prospect_name,
                                                "status": "Open"}, pluck="name"):
        frappe.db.set_value("ToDo", todo, "allocated_to", user)
        moved += 1
    if lead:
        frappe.db.set_value("CRM Lead", lead, "lead_owner", user, update_modified=False)
        for task in frappe.get_all("CRM Task", filters={"reference_doctype": "CRM Lead", "reference_docname": lead,
                                                        "status": ["in", ["Backlog", "Todo", "In Progress"]]},
                                   pluck="name"):
            frappe.db.set_value("CRM Task", task, "assigned_to", user)
            moved += 1
    convo = frappe.db.get_value("Sales Conversation", {"company": company, "prospect": prospect_name})
    if convo:
        frappe.db.set_value("Sales Conversation", convo, "assigned_to", user, update_modified=False)
    return moved
