from frappe.model.document import Document

from reckon_sales_agent.tenant import protect_fields

SYSTEM = ("slot_options", "event", "invite_message", "reminder_day_sent", "reminder_hour_sent", "source")


class SalesMeeting(Document):
    def validate(self):
        if self.flags.ignore_permissions:
            return  # the Meeting agent's own writes
        protect_fields(self, SYSTEM)
        if self.starts_on and self.duration_minutes and not self.ends_on:
            from frappe.utils import add_to_date

            self.ends_on = add_to_date(self.starts_on, minutes=int(self.duration_minutes))
