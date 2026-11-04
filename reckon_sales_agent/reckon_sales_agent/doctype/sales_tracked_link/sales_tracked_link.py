from frappe.model.document import Document


class SalesTrackedLink(Document):
    """One link in one message: a click or an open that can be traced back to the recipient. Written by the system."""
