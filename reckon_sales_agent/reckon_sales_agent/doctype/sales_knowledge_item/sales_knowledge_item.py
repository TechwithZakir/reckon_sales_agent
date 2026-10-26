import frappe
from frappe import _
from frappe.model.document import Document

from reckon_sales_agent.tenant import protect_fields

BOUND = ("title", "category", "content", "language", "valid_until")


class SalesKnowledgeItem(Document):
    def validate(self):
        if self.flags.ignore_permissions:
            return  # the system's own writes
        protect_fields(self, ("status", "approved_by", "approved_on"), {"status": "Draft"})
        if not self.is_new() and self.get_db_value("status") == "Approved" and any(self.has_value_changed(f) for f in BOUND):
            # Approval covered this exact wording: a change needs a new approval.
            self.status = "Draft"
            self.approved_by = None
            self.approved_on = None
            frappe.msgprint(_("Changed after approval: agents will not use it until it is approved again."),
                            indicator="orange", alert=True)
