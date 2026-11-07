import frappe
from frappe import _
from frappe.model.document import Document

from reckon_sales_agent.campaigns import capture
from reckon_sales_agent.campaigns import tags as tag_rules
from reckon_sales_agent.tenant import protect_fields

PROTECTED = ("slug", "submissions", "confirmed_count", "last_submission")


class SalesCaptureForm(Document):
    """A public signup form: embedded, a popup, or a page of its own. Visitors are untrusted; see campaigns.capture."""

    def validate(self):
        protect_fields(self, PROTECTED)  # (this clears the key on a new form: it is made just below, once)
        if not self.slug:
            self.slug = frappe.generate_hash(length=10).lower()
        self.form_name = " ".join((self.form_name or "").split())
        rows = []
        try:
            import json

            rows = json.loads(self.fields_json or "[]")
        except ValueError:
            frappe.throw(_("The form's fields are not valid."))
        self.fields_json = frappe.as_json(capture.clean_fields(rows))
        self.accent_color = capture.accent(self.accent_color)
        redirect = (self.redirect_url or "").strip()
        if redirect and not capture.safe_redirect(redirect):
            frappe.throw(_("The thank-you address must start with https://."))
        self.redirect_url = redirect or None
        self.tags = tag_rules.to_text(self.tags) or None
        self.allowed_origins = "\n".join(o for o in (x.strip().rstrip("/") for x in (self.allowed_origins or "").splitlines())
                                         if o.lower().startswith("https://") and " " not in o) or None
        if self.status == "Published" and not (self.consent_text or "").strip() and self.require_consent:
            frappe.throw(_("Write the agreement text visitors tick, or switch the agreement off."))
