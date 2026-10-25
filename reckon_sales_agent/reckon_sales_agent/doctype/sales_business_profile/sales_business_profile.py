import frappe
from frappe import _
from frappe.model.document import Document


class SalesBusinessProfile(Document):
    def validate(self):
        # One profile per Company: the market research agent reasons from it.
        other = frappe.db.get_value("Sales Business Profile", {"company": self.company, "name": ["!=", self.name]})
        if other:
            frappe.throw(_("{0} already has a business profile.").format(self.company), frappe.DuplicateEntryError)
