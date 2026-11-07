"""Adding and removing tags on people, and telling the automations about it."""

from __future__ import annotations

import frappe

from reckon_sales_agent.campaigns import tags as tag_rules


def add_tags(company: str, prospect: str, new_tags, source: str = "") -> list[str]:
    """Add tags to one person; returns the ones that were new. An automation that starts on a tag hears about each one."""
    wanted = tag_rules.normalize(new_tags)
    if not wanted:
        return []
    current = frappe.db.get_value("Sales Prospect", prospect, "tags")
    added = [t for t in wanted if t not in tag_rules.normalize(current)]
    if not added:
        return []
    frappe.db.set_value("Sales Prospect", prospect, "tags", tag_rules.to_text(tag_rules.add(current, added)))
    for tag in added:
        _fire(company, prospect, tag, source)
    return added


def remove_tags(prospect: str, gone) -> list[str]:
    current = frappe.db.get_value("Sales Prospect", prospect, "tags")
    left = tag_rules.remove(current, gone)
    if left != tag_rules.normalize(current):
        frappe.db.set_value("Sales Prospect", prospect, "tags", tag_rules.to_text(left) or None)
    return left


def _fire(company: str, prospect: str, tag: str, source: str) -> None:
    try:
        from reckon_sales_agent.automation.engine import fire

        fire(company, "tag_added", prospect, tag=tag, source=source or "tag")
    except Exception:
        frappe.log_error(title="Sales Agent automation trigger failed", message=f"tag_added {tag} for {prospect}")
