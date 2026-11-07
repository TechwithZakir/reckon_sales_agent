"""Segments, tags and CSV import: the endpoints of Capture Studio.

Everything is limited to the session's Company. Reading needs no special role; changing a segment, tagging people or
importing needs a Sales Agent manager, because they decide who campaigns reach.
"""

from __future__ import annotations

import json

import frappe
from frappe import _

from reckon_sales_agent.api_studio import _can_manage
from reckon_sales_agent.campaigns import import_service, segment_service, segments
from reckon_sales_agent.campaigns import tags as tag_rules
from reckon_sales_agent.campaigns.tag_service import add_tags, remove_tags
from reckon_sales_agent.tenant import current_company, get_tenant_doc
from reckon_sales_agent.usage import assert_entitled

BULK_TAG_LIMIT = 5000


def _require_manager() -> None:
    if not _can_manage():
        frappe.throw(_("Ask a Sales Agent admin or manager to do this."), frappe.PermissionError)


def _json(value):
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value or "{}")
    except ValueError:
        frappe.throw(_("That request is not valid."))


@frappe.whitelist()
def catalog() -> dict:
    """What the segment builder offers, and the tags already in use."""
    company = current_company()
    counts: dict[str, int] = {}
    for row in frappe.get_all("Sales Prospect", filters={"company": company, "tags": ["is", "set"]}, pluck="tags", limit=20000):
        for tag in tag_rules.normalize(row):
            counts[tag] = counts.get(tag, 0) + 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:100]
    return {"conditions": segments.catalog(), "modes": list(segments.MATCH_MODES), "tags": [{"tag": t, "people": n} for t, n in top]}


@frappe.whitelist()
def segment_list() -> list[dict]:
    company = current_company()
    assert_entitled(company)
    rows = frappe.get_all("Sales Segment", filters={"company": company},
                          fields=["name", "segment_name", "description", "match_mode", "rules", "size", "last_refreshed"],
                          order_by="modified desc", limit=200)
    for row in rows:
        conditions, _problems = segments.clean_conditions(_json(row.rules or "[]"))
        row["summary"] = segments.summary(conditions, row.match_mode)
        row["rule_count"] = len(conditions)
        row["last_refreshed"] = str(row.last_refreshed or "")
        row["audiences"] = frappe.db.count("Sales Audience", {"segment": row.name})
    return rows


@frappe.whitelist()
def segment(name: str) -> dict:
    doc = get_tenant_doc("Sales Segment", name, "read")
    return {"name": doc.name, "segment_name": doc.segment_name, "description": doc.description, "match_mode": doc.match_mode,
            "rules": _json(doc.rules or "[]"), "size": doc.size or 0}


@frappe.whitelist(methods=["POST"])
def preview(rules, match_mode: str = "All") -> dict:
    """Who a set of rules matches right now, without saving."""
    company = current_company()
    assert_entitled(company)
    return segment_service.preview(company, _json(rules), match_mode)


@frappe.whitelist(methods=["POST"])
def save_segment(data) -> dict:
    _require_manager()
    company = current_company()
    assert_entitled(company)
    values = _json(data)
    doc = get_tenant_doc("Sales Segment", values["name"], "write") if values.get("name") else frappe.new_doc("Sales Segment")
    if doc.is_new():
        doc.company = company
    doc.segment_name = values.get("segment_name")
    doc.description = values.get("description")
    doc.match_mode = values.get("match_mode") if values.get("match_mode") in segments.MATCH_MODES else segments.ALL
    doc.rules = json.dumps(values.get("rules") or [])
    doc.save()
    return {"name": doc.name, "size": segment_service.refresh(doc.name)}


@frappe.whitelist(methods=["POST"])
def refresh_segment(name: str) -> int:
    get_tenant_doc("Sales Segment", name, "read")
    return segment_service.refresh(name)


@frappe.whitelist(methods=["POST"])
def delete_segment(name: str) -> None:
    _require_manager()
    doc = get_tenant_doc("Sales Segment", name, "delete")
    if frappe.db.exists("Sales Audience", {"segment": doc.name}):
        frappe.throw(_("An audience uses this segment. Remove the audience first."))
    for auto in frappe.get_all("Sales Automation", filters={"company": doc.company}, pluck="flow"):
        if doc.name in (auto or "") or doc.segment_name in (auto or ""):
            frappe.throw(_("An automation uses this segment. Change the automation first."))
    frappe.delete_doc("Sales Segment", doc.name)


@frappe.whitelist(methods=["POST"])
def tag_segment(name: str, tags: str, remove: int = 0) -> dict:
    """Add (or remove) tags for everyone in a segment."""
    _require_manager()
    doc = get_tenant_doc("Sales Segment", name, "read")
    wanted = tag_rules.normalize(tags)
    if not wanted:
        frappe.throw(_("Enter at least one tag."))
    people = segment_service.resolve(doc)[:BULK_TAG_LIMIT]
    changed = 0
    for person in people:
        if int(remove or 0):
            before = tag_rules.normalize(person["tags"])
            if remove_tags(person["name"], wanted) != before:
                changed += 1
        elif add_tags(doc.company, person["name"], wanted, f"segment {doc.segment_name}"):
            changed += 1
    return {"people": len(people), "changed": changed}


@frappe.whitelist(methods=["POST"])
def tag_person(prospect: str, tags: str, remove: int = 0) -> list[str]:
    _require_manager()
    company = current_company()
    if frappe.db.get_value("Sales Prospect", prospect, "company") != company:
        frappe.throw(_("That person belongs to another Company."), frappe.PermissionError)
    if int(remove or 0):
        return remove_tags(prospect, tags)
    add_tags(company, prospect, tags, "by hand")
    return tag_rules.normalize(frappe.db.get_value("Sales Prospect", prospect, "tags"))


# Import --------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def import_preview(csv_text: str) -> dict:
    company = current_company()
    assert_entitled(company)
    return import_service.preview(csv_text)


@frappe.whitelist(methods=["POST"])
def import_start(csv_text: str, mapping, label: str = "", tags: str = "", source_label: str = "", consent_statement: str = "",
                 file_name: str = "") -> str:
    _require_manager()
    company = current_company()
    assert_entitled(company)
    return import_service.start(company, frappe.session.user, csv_text, _json(mapping) if not isinstance(mapping, list) else mapping,
                                label, tags, source_label, consent_statement, file_name)


@frappe.whitelist()
def import_status(job: str) -> dict:
    get_tenant_doc("Sales Import Job", job, "read")
    return import_service.status(job)


@frappe.whitelist()
def imports() -> list[dict]:
    company = current_company()
    return frappe.get_all("Sales Import Job", filters={"company": company},
                          fields=["name", "label", "status", "total", "created", "updated", "skipped", "suppressed", "started_on"],
                          order_by="creation desc", limit=30)
