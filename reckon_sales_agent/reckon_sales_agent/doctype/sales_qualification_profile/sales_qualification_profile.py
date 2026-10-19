import frappe
from frappe import _
from frappe.model.document import Document

SCORING_FIELDS = ("qualify_threshold", "review_threshold", "target_industries", "fit_keywords", "need_keywords",
                  "negative_keywords", "weight_industry", "weight_complexity", "weight_need", "weight_scale",
                  "weight_evidence")


class SalesQualificationProfile(Document):
    def validate(self):
        weights = [self.get(f) or 0 for f in SCORING_FIELDS if f.startswith("weight_")]
        if any(w < 0 for w in weights) or sum(weights) <= 0:
            frappe.throw(_("Weights must be positive and add up to more than zero."))
        if not 0 <= (self.review_threshold or 0) <= (self.qualify_threshold or 0) <= 100:
            frappe.throw(_("Thresholds must satisfy 0 <= review <= qualify <= 100."))
        if self.is_new():
            self.version = 1
        elif any(self.has_value_changed(f) for f in SCORING_FIELDS):
            self.version = (self.get_db_value("version") or 1) + 1
