import frappe
from frappe import _
from frappe.model.document import Document


class SalesUsageLedger(Document):
    """Append-only usage meter."""

    def validate(self):
        if not self.is_new():
            frappe.throw(_("Usage records cannot be changed."))

    def on_trash(self):
        if frappe.session.user != "Administrator":
            frappe.throw(_("Usage records cannot be deleted."))
