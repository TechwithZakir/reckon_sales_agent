import frappe
from frappe import _
from frappe.model.document import Document


class SalesAgentActivity(Document):
    """Append-only audit trail."""

    def validate(self):
        if not self.is_new():
            frappe.throw(_("Audit records cannot be changed."))

    def on_trash(self):
        if frappe.session.user != "Administrator":
            frappe.throw(_("Audit records cannot be deleted."))
