import json

import frappe
from frappe import _
from frappe.model.document import Document

from reckon_sales_agent.campaigns import segments
from reckon_sales_agent.tenant import protect_fields

PROTECTED = ("size", "last_refreshed")


class SalesSegment(Document):
    """Saved rules that pick people. They are checked every time the segment is used, so it is always current."""

    def validate(self):
        protect_fields(self, PROTECTED)
        self.segment_name = " ".join((self.segment_name or "").split())
        try:
            rows = json.loads(self.rules or "[]")
        except ValueError:
            frappe.throw(_("The segment's rules are not valid."))
        good, problems = segments.clean_conditions(rows)
        if problems:
            frappe.throw("<br>".join(frappe.utils.escape_html(p) for p in problems))
        if not good:
            frappe.throw(_("Add at least one rule."))
        self.rules = frappe.as_json(good)
