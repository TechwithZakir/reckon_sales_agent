import frappe
from frappe import _
from frappe.model.document import Document

from reckon_sales_agent.tenant import protect_fields

BOUND = ("channel", "language", "subject", "body", "whatsapp_category", "whatsapp_params")
SYSTEM = ("status", "approved_by", "approved_on", "content_status", "content_issues", "email_template",
          "whatsapp_template", "ai_generated")


class SalesMessageTemplate(Document):
    def validate(self):
        if self.flags.ignore_permissions:
            return  # the Content agent's own writes
        protect_fields(self, SYSTEM, {"status": "Draft", "content_status": "Not checked"})
        if self.channel == "Email" and not (self.subject or "").strip():
            frappe.throw(_("An email template needs a subject."))
        from reckon_sales_agent.agents.templates import check_template

        result = check_template(self)
        self.content_status, self.content_issues = result["status"], "\n".join(result["issues"])[:5000]
        if not self.is_new() and self.get_db_value("status") == "Approved" and any(self.has_value_changed(f) for f in BOUND):
            # The approval covered this exact wording.
            self.status, self.approved_by, self.approved_on = "Draft", None, None
            frappe.msgprint(_("Changed after approval: approve it again before it is used."), indicator="orange",
                            alert=True)
