import frappe
from frappe import _
from frappe.model.document import Document

from reckon_sales_agent.discovery.normalize import (
    mask,
    normalize_domain,
    normalize_email,
    normalize_phone,
    value_hash,
)


class SalesSuppressionEntry(Document):
    def validate(self):
        normal = {"Email": normalize_email, "Phone": normalize_phone, "Domain": normalize_domain}[self.entry_type](self.value)
        if not normal:
            frappe.throw(_("{0} is not a valid {1}.").format(self.value, _(self.entry_type).lower()))
        self.value = normal
        self.value_hash = value_hash(self.entry_type, normal)
        self.display_value = mask(normal) if self.entry_type != "Domain" else normal
        duplicate = frappe.db.get_value("Sales Suppression Entry", {"company": self.company,
                                        "value_hash": self.value_hash, "name": ["!=", self.name]})
        if duplicate:
            frappe.throw(_("This value is already on the suppression list ({0}).").format(duplicate))
