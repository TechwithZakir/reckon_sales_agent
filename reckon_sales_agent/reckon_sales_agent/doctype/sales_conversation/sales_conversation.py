from frappe.model.document import Document

from reckon_sales_agent.tenant import protect_fields

SYSTEM = ("company", "prospect", "title", "last_channel", "last_inbound_at", "handoff_reason", "resolved_on")


class SalesConversation(Document):
    """One lead's conversation across channels: who answers it, its status, tags and how much the AI may do."""

    def validate(self):
        if not self.flags.ignore_permissions:
            protect_fields(self, SYSTEM)
