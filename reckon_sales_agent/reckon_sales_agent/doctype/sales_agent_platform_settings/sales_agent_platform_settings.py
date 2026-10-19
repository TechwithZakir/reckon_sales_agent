import frappe
from frappe import _
from frappe.model.document import Document


class SalesAgentPlatformSettings(Document):
    def validate(self):
        if self.ai_enabled and not self.ai_model:
            frappe.throw(_("Set the AI model."))
        if self.places_enabled and not self.places_terms_reviewed:
            frappe.throw(_("Confirm the Google Maps Platform terms review before enabling Places."))
        for field, low, high in (("fetch_timeout", 2, 60), ("max_page_kb", 64, 5120), ("max_pages_per_site", 1, 10),
                                 ("places_retention_days", 1, 30)):
            if self.get(field) and not low <= int(self.get(field)) <= high:
                frappe.throw(_("{0} must be between {1} and {2}.").format(self.meta.get_label(field), low, high))
