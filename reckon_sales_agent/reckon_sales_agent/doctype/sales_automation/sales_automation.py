import json

import frappe
from frappe import _
from frappe.model.document import Document

from reckon_sales_agent.automation import flow as flow_rules
from reckon_sales_agent.tenant import protect_fields

PROTECTED = ("status", "campaign", "activated_by", "activated_on")


class SalesAutomation(Document):
    """A flow of steps people move through. Switching it on is a person's decision; changing it switches it off again."""

    def validate(self):
        changed = not self.is_new() and self._flow_changed()
        protect_fields(self, PROTECTED, {"status": "Draft"})
        self.automation_name = " ".join((self.automation_name or "").split())
        try:
            raw = json.loads(self.flow or "{}")
        except ValueError:
            frappe.throw(_("The flow is not valid."))
        flow = flow_rules.normalize(raw)
        self.flow = frappe.as_json(flow)
        self.trigger_event = flow_rules.TRIGGERS.get(flow["nodes"][flow["start"]]["config"]["event"], "")
        if changed and self.status == "Active" and not self.flags.ignore_permissions:
            self.status = "Paused"
            frappe.msgprint(_("The flow changed, so the automation is paused. Check it and switch it on again."),
                            indicator="orange", alert=True)

    def _flow_changed(self) -> bool:
        stored = frappe.db.get_value("Sales Automation", self.name, "flow")
        try:
            return json.loads(stored or "{}") != flow_rules.normalize(json.loads(self.flow or "{}"))
        except ValueError:
            return True
