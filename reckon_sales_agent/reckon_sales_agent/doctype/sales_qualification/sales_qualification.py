from frappe.model.document import Document

from reckon_sales_agent.tenant import protect_fields

PROTECTED = ("result", "industry_fit", "operational_complexity", "need_signal", "scale", "evidence_quality",
             "fit_score", "buying_signal_score", "evidence_confidence", "contactability", "explanation",
             "unknowns", "scoring_version", "profile_version", "override_result", "override_reason",
             "overridden_by")


class SalesQualification(Document):
    """Scores are written by the scoring engine; overrides go through the API."""

    def validate(self):
        protect_fields(self, PROTECTED)
