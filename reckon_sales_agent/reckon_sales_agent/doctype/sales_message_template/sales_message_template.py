import frappe
from frappe import _
from frappe.model.document import Document

from reckon_sales_agent.tenant import protect_fields

# What an approval covers: a change to any of these sends the template back to draft.
BOUND = ("channel", "language", "subject", "body", "whatsapp_category", "whatsapp_params", "preheader",
         "subject_variants", "sms_send_window", "opt_out_keyword", "whatsapp_header_type", "whatsapp_header",
         "whatsapp_footer", "whatsapp_buttons")
SYSTEM = ("status", "approved_by", "approved_on", "content_status", "content_issues", "email_template",
          "whatsapp_template", "ai_generated")


class SalesMessageTemplate(Document):
    def validate(self):
        if self.flags.ignore_permissions:
            return  # the Content agent's own writes
        protect_fields(self, SYSTEM, {"status": "Draft", "content_status": "Not checked"})
        # A draft may be unfinished (the builder autosaves from the first keystroke); approval insists on a subject.
        from reckon_sales_agent.agents.templates import check_template

        result = check_template(self)
        self.content_status, self.content_issues = result["status"], "\n".join(result["issues"])[:5000]
        if not self.is_new() and self.get_db_value("status") == "Approved" and any(self.has_value_changed(f) for f in BOUND):
            # The approval covered this exact wording.
            self.status, self.approved_by, self.approved_on = "Draft", None, None
            frappe.msgprint(_("Changed after approval: approve it again before it is used."), indicator="orange",
                            alert=True)
