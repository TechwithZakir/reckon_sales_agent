import frappe
from frappe import _
from frappe.model.document import Document

from reckon_sales_agent.discovery.normalize import normalize_email, normalize_phone


class SalesAudienceMember(Document):
    def validate(self):
        if self.reference_doctype and not self.reference_name:
            frappe.throw(_("Row {0}: choose the record, or clear the record type.").format(self.idx))
        if self.reference_doctype:
            return  # the email and phone come from the record when the audience is used
        self.email = normalize_email(self.email) or None
        self.phone = normalize_phone(self.phone) or None
        if not (self.email or self.phone):
            frappe.throw(_("Row {0}: add a valid email or phone, or pick a record.").format(self.idx))
