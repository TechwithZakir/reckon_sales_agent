from frappe.model.document import Document


class SalesImportJob(Document):
    """One CSV import, run in the background. The file is removed from the record when it is done."""
