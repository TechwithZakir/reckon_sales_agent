import frappe
from frappe import _
from frappe.model.document import Document

from reckon_sales_agent.tenant import is_system_actor, protect_fields

PROTECTED = ("status", "approved_by", "sent_on", "recipient", "idempotency_key", "ai_generated", "error")


class SalesOutreachMessage(Document):
    def validate(self):
        if is_system_actor() or self.flags.ignore_permissions:
            return  # drafted and updated by the campaign engine
        if self.is_new():
            frappe.throw(_("Messages are drafted by the campaign."))
        if self.get_db_value("status") != "Draft":
            frappe.throw(_("Only draft messages can be edited."))
        protect_fields(self, PROTECTED)
