import frappe
from frappe import _
from frappe.model.document import Document


class SalesSocialAccount(Document):
    def validate(self):
        # One Page or Instagram account serves one Company: Meta events are routed by account ID, so a second
        # enabled copy would silently take the messages and leads from the first.
        if not self.enabled or not self.account_id:
            return
        filters = {"platform": self.platform, "account_id": self.account_id, "enabled": 1}
        if self.name:
            filters["name"] = ["!=", self.name]
        if frappe.db.exists("Sales Social Account", filters):
            frappe.throw(_("This {0} is already connected to another Company. Disconnect it there first.").format(self.platform))
