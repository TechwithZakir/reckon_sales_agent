import frappe
from frappe import _
from frappe.model.document import Document

from reckon_sales_agent.tenant import is_system_actor, protect_fields

PROTECTED = ("status", "approved_by", "sent_on", "recipient", "idempotency_key", "ai_generated", "error")


class SalesOutreachMessage(Document):
    def validate(self):
        if self.flags.ignore_permissions:
            return  # drafted and updated by the campaign engine
        if is_system_actor():
            # Administrators may correct a message, but an approved one goes back to Draft when it changes.
            from reckon_sales_agent.agents.approvals import approval_current, message_payload

            if (not self.is_new() and self.status == "Approved" and self.approved_by
                    and not approval_current(self.approval_fingerprint, message_payload(self))):
                self.status, self.approved_by, self.approval_fingerprint = "Draft", None, None
            return
        if self.is_new():
            frappe.throw(_("Messages are drafted by the campaign."))
        if self.get_db_value("status") != "Draft":
            frappe.throw(_("Only draft messages can be edited."))
        protect_fields(self, PROTECTED)
