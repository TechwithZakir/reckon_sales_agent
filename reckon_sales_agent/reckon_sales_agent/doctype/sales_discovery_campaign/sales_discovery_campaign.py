import frappe
from frappe import _
from frappe.model.document import Document

from reckon_sales_agent.tenant import protect_fields

PROTECTED = ("status", "prospects_found", "duplicates_found", "qualified_count", "last_job")


class SalesDiscoveryCampaign(Document):
    def validate(self):
        protect_fields(self, PROTECTED, {"status": "Draft"})
        if not 1 <= int(self.target_count or 0) <= 5000:
            frappe.throw(_("Target count must be between 1 and 5000."))
        if not 1 <= int(self.per_query_limit or 0) <= 60:
            frappe.throw(_("Results per search must be between 1 and 60."))
