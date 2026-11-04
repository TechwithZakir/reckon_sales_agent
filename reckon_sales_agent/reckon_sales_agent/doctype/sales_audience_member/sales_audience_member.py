from frappe.model.document import Document


class SalesAudienceMember(Document):
    """One person in a hand-picked audience. The rows are checked by Sales Audience, because Frappe does not run a
    child table's own validate when the parent is saved."""
