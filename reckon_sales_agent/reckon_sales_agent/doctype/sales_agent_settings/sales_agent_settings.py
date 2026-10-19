import frappe
from frappe import _
from frappe.model.document import Document

from reckon_sales_agent.tenant import is_system_actor

PLAN_FIELDS = ("monthly_discovery_limit", "monthly_research_limit", "monthly_ai_limit", "monthly_message_limit")
BOUNDS = {"daily_message_limit": (0, 1000), "max_results_per_job": (1, 1000), "max_concurrent_jobs": (1, 5),
          "retention_days": (30, 3650)}


class SalesAgentSettings(Document):
    def validate(self):
        if not is_system_actor():
            # Plan limits are set by the vendor, never by the tenant.
            for field in PLAN_FIELDS:
                self.set(field, None if self.is_new() else self.get_db_value(field))
        for field, (low, high) in BOUNDS.items():
            value = self.get(field)
            if value is not None and not low <= int(value) <= high:
                frappe.throw(_("{0} must be between {1} and {2}.").format(self.meta.get_label(field), low, high))
