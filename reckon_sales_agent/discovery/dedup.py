"""Staged, explainable duplicate detection within one Company.

1. Same source and source reference.
2. Same normalised website domain.
3. Same normalised phone number.
4. Same normalised name in the same city.
5. Fuzzy name match in the same city: flagged for human review, never merged.
"""

from __future__ import annotations

import frappe

from reckon_sales_agent.discovery.normalize import (
    normalize_domain,
    normalize_name,
    normalize_phone,
    similarity,
)

FUZZY_THRESHOLD = 0.9


def find_duplicate(company: str, source_connector: str | None, external_id: str | None, fields: dict):
    """(prospect name, reason) of an existing match, or (None, None)."""
    base = {"company": company, "review_status": ["!=", "Merged"]}
    if source_connector and external_id:
        name = frappe.db.get_value("Sales Prospect", {**base, "source_connector": source_connector,
                                                      "external_id": external_id})
        if name:
            return name, "source reference"
    domain = normalize_domain(fields.get("website"))
    if domain:
        name = frappe.db.get_value("Sales Prospect", {**base, "domain": domain})
        if name:
            return name, "website domain"
    phone = normalize_phone(fields.get("phone"))
    if phone:
        name = frappe.db.get_value("Sales Prospect", {**base, "normalized_phone": phone})
        if name:
            return name, "phone number"
    normalized = normalize_name(fields.get("business_name"))
    if normalized:
        filters = {**base, "normalized_name": normalized}
        if fields.get("city"):
            filters["city"] = fields["city"]
        name = frappe.db.get_value("Sales Prospect", filters)
        if name:
            return name, "name and city"
    return None, None


def find_possible_duplicate(company: str, fields: dict) -> str | None:
    """Closest fuzzy name match in the same city, for the review queue."""
    city = fields.get("city")
    if not city or not fields.get("business_name"):
        return None
    candidates = frappe.get_all(
        "Sales Prospect",
        filters={"company": company, "city": city, "review_status": ["!=", "Merged"]},
        fields=["name", "business_name"],
        limit=500,
    )
    best, best_score = None, 0.0
    for row in candidates:
        score = similarity(fields["business_name"], row.business_name)
        if score > best_score:
            best, best_score = row.name, score
    return best if best_score >= FUZZY_THRESHOLD else None
