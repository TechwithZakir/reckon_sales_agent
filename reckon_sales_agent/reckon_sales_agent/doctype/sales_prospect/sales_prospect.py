import frappe
from frappe import _
from frappe.model.document import Document

from reckon_sales_agent.discovery.normalize import (
    normalize_domain,
    normalize_email,
    normalize_name,
    normalize_phone,
)
from reckon_sales_agent.tenant import protect_fields

PROTECTED = (
    "review_status", "qualification_status", "fit_score", "buying_signal_score", "evidence_confidence",
    "contactability", "research_status", "latest_research", "latest_qualification", "crm_organization",
    "crm_lead", "merged_into", "possible_duplicate_of", "source_connector", "source_type", "external_id",
    "source_url", "provenance_json", "retention_until", "first_seen", "last_seen",
)


class SalesProspect(Document):
    def validate(self):
        protect_fields(self, PROTECTED, {"review_status": "Pending", "source_type": "manual",
                                         "provenance_json": '{"manual": {"source": "user"}}'})
        if self.website:
            website = self.website.strip()
            if "://" not in website:
                website = "https://" + website
            if not website.lower().startswith(("http://", "https://")):
                frappe.throw(_("Website must be an http or https address."))
            self.website = website
        if self.email:
            self.email = normalize_email(self.email) or None
        self.domain = normalize_domain(self.website) or None
        self.normalized_name = normalize_name(self.business_name)
        self.normalized_phone = normalize_phone(self.phone) or None
