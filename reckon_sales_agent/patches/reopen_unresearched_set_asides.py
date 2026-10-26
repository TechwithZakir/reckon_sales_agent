"""Reopen leads the autopilot set aside for a low score that came from missing evidence, not from their website.

Live test: leads with no website or an unreachable one scored 13-16 for lack of evidence and were set aside as
"weak" (Biorex Healthcare, Islamia Drug House). They go back to Pending, where AI triage judges them.
"""

import frappe

NOTE = "Autopilot: fit score below your review threshold%"


def execute():
    names = frappe.get_all("Sales Prospect", filters={"review_status": "Rejected", "review_notes": ["like", NOTE],
                                                      "research_status": ["!=", "Done"]}, pluck="name")
    for name in names:
        frappe.db.set_value("Sales Prospect", name, {"review_status": "Pending", "review_notes": None},
                            update_modified=False)
