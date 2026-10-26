import frappe
from frappe import _
from frappe.model.document import Document

from reckon_sales_agent.agents.approvals import approval_current, campaign_payload
from reckon_sales_agent.tenant import is_system_actor, protect_fields

PROTECTED = ("status", "approved_by", "approved_on", "member_count", "sent_count", "reply_count",
             "unsubscribe_count", "bounce_count", "converted_count", "approval_fingerprint", "approved_audience_size",
             "content_status", "content_issues", "content_checked_on")


class SalesCampaign(Document):
    def validate(self):
        steps_changed = not self.is_new() and self._steps_signature() != self._stored_steps_signature()
        protect_fields(self, PROTECTED, {"status": "Draft"})
        numbers = [row.step_no for row in self.steps]
        if len(numbers) != len(set(numbers)):
            frappe.throw(_("Step numbers must be unique."))
        self.steps.sort(key=lambda row: row.step_no)
        for idx, row in enumerate(self.steps, start=1):
            row.idx = idx
            if (row.delay_days or 0) < 0:
                frappe.throw(_("Delays cannot be negative."))
        if self.end_date and self.start_date and self.end_date < self.start_date:
            frappe.throw(_("End date is before start date."))
        changed = (not approval_current(self.approval_fingerprint, campaign_payload(self)) if self.approval_fingerprint
                   else steps_changed)
        if changed and self.status in ("Active", "Approved") and not is_system_actor():
            # Approval covered exact content, channels, audience and schedule: any change needs a new one.
            self.status = "Pending Approval"
            self.approved_by = None
            self.approved_on = None
            self.approval_fingerprint = None
            frappe.msgprint(_("The campaign changed after approval, so it needs approval again before it sends."),
                            indicator="orange", alert=True)
        if self.steps:
            from reckon_sales_agent.agents.content_agent import apply_rule_check

            apply_rule_check(self)  # approvers always see claim, figure and offer issues

    def _steps_signature(self):
        return [(r.step_no, r.delay_days, r.subject_template, r.body_template, r.use_ai_personalisation)
                for r in sorted(self.steps, key=lambda r: r.step_no)]

    def _stored_steps_signature(self):
        rows = frappe.get_all("Sales Campaign Step", filters={"parent": self.name, "parenttype": self.doctype},
                              fields=["step_no", "delay_days", "subject_template", "body_template",
                                      "use_ai_personalisation"], order_by="step_no asc")
        return [(r.step_no, r.delay_days, r.subject_template, r.body_template, r.use_ai_personalisation)
                for r in rows]
