import frappe
from frappe import _
from frappe.model.document import Document

from reckon_sales_agent.agents.approvals import approval_current
from reckon_sales_agent.agents.social import post_payload
from reckon_sales_agent.tenant import is_system_actor, protect_fields

PROTECTED = ("status", "approved_by", "approved_on", "approval_fingerprint", "published_on", "content_status",
             "content_issues")


class SalesSocialPost(Document):
    def validate(self):
        protect_fields(self, PROTECTED, {"status": "Draft"})
        if not is_system_actor() and self.status in ("Published", "Partly Published"):
            frappe.throw(_("A published post cannot be edited; create a new post."))
        if (self.status in ("Approved", "Scheduled") and not is_system_actor()
                and not approval_current(self.approval_fingerprint, post_payload(self))):
            # Approval covered this exact content, media, accounts and schedule.
            self.status = "Pending Approval"
            self.approved_by = None
            self.approved_on = None
            self.approval_fingerprint = None
            frappe.msgprint(_("The post changed after approval, so it needs approval again before it publishes."),
                            indicator="orange", alert=True)
        from reckon_sales_agent.agents.social_agent import apply_check

        apply_check(self)
