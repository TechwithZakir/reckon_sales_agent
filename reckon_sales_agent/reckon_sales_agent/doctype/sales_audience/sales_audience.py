import frappe
from frappe import _
from frappe.model.document import Document

from reckon_sales_agent.campaigns.audience import SPECIFIC, split_list
from reckon_sales_agent.tenant import protect_fields

PROTECTED = ("size", "size_email", "size_phone", "last_refreshed")


class SalesAudience(Document):
    def validate(self):
        protect_fields(self, PROTECTED)
        self.audience_name = " ".join((self.audience_name or "").split())
        if (self.sms_opt_in or self.whatsapp_opt_in) and not (self.opt_in_source or "").strip():
            # Consent is the user's statement about their own people, so it must say where it came from.
            frappe.throw(_("Say how these people agreed to receive SMS or WhatsApp messages."))
        if not (self.sms_opt_in or self.whatsapp_opt_in):
            self.opt_in_source = None
        self.status_filter = ", ".join(split_list(self.status_filter)) or None
        score = float(self.minimum_fit_score or 0)
        if not 0 <= score <= 100:
            frappe.throw(_("The minimum fit score must be between 0 and 100."))
        if self.audience_type == SPECIFIC and not self.members:
            frappe.msgprint(_("Add the people for this audience."), indicator="orange", alert=True)
