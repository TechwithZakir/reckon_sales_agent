import frappe
from frappe import _
from frappe.model.document import Document

from reckon_sales_agent.campaigns import webhook_events as events
from reckon_sales_agent.tenant import protect_fields

PROTECTED = ("last_status", "last_error", "last_sent_at", "failures")


class SalesWebhookSubscription(Document):
    """A web address that is told about events (see campaigns.webhook_events). The address must be a public https one."""

    def validate(self):
        protect_fields(self, PROTECTED, {"failures": 0})
        self.description = " ".join((self.description or "").split())
        url = events.safe_url(self.url)
        if not url:
            frappe.throw(_("The address must start with https:// and have no spaces."))
        self.url = url
        self.events = ", ".join(events.clean_events(self.events)) or None
        if self.active and not self.events:
            frappe.throw(_("Choose at least one event."))
        if self.active and (self.failures or 0) >= events.MAX_FAILURES:
            self.failures = 0  # switched on again by a person: a fresh start

    def on_update(self):
        from reckon_sales_agent.campaigns.webhook_service import forget

        forget(self.company)

    def on_trash(self):
        from reckon_sales_agent.campaigns.webhook_service import forget

        forget(self.company)
