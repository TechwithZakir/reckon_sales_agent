"""Claude proposes search keywords, Bangla variants and B2B segments for a targeting profile."""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from reckon_sales_agent.constants import USAGE_AI
from reckon_sales_agent.discovery.targeting import AI_PLAN_SCHEMA, clean_suggestions
from reckon_sales_agent.providers.factory import get_llm
from reckon_sales_agent.providers.llm import UNTRUSTED_RULES, LLMError, untrusted
from reckon_sales_agent.usage import get_settings, remaining, reserve

SYSTEM = (
    "You plan B2B lead searches for a company selling in Bangladesh. Propose short search "
    "phrases a business directory or maps search would match (2-5 words each), Bangla "
    "equivalents where Bangladeshi businesses commonly use them, buyer segments, related "
    "industries, and words that would rule a business out. Stay within the seller's offer and "
    "the target profile; do not invent facts about specific companies. " + UNTRUSTED_RULES
)


def suggest(profile_doc, *, raise_errors: bool = True) -> dict | None:
    """Ask Claude for suggestions; store them on the profile and return them."""
    llm = get_llm(profile_doc.company)
    if not llm:
        if raise_errors:
            frappe.throw(_("Enable AI in Sales Agent Settings (and ask your provider to enable it) first."))
        return None
    if remaining(profile_doc.company, USAGE_AI) <= 0:
        if raise_errors:
            frappe.throw(_("Monthly AI limit reached."))
        return None
    reserve(profile_doc.company, USAGE_AI, 1, profile_doc)
    frappe.db.commit()  # no open transaction while waiting on the model
    settings = get_settings(profile_doc.company)
    brief = "\n".join(
        f"{label}: {profile_doc.get(field) or '-'}"
        for label, field in (("Market", "market"), ("Company size", "company_size"), ("Industries", "industries"),
                             ("B2B segments", "b2b_segments"), ("Keywords", "keywords"),
                             ("Interests / needs", "interests"), ("Exclude", "exclude_keywords"))
    )
    places = ", ".join(filter(None, (row.city for row in profile_doc.locations))) or "Bangladesh"
    try:
        data = llm.complete_json(
            SYSTEM,
            untrusted("seller profile", f"Seller offers: {settings.company_profile or 'not described'}")
            + "\n" + untrusted("target profile", f"{brief}\nLocations: {places}"),
            AI_PLAN_SCHEMA,
        )
    except LLMError as exc:
        if raise_errors:
            frappe.throw(str(exc))
        return None
    suggestions = clean_suggestions(data)
    profile_doc.db_set({"ai_suggestions": json.dumps(suggestions, ensure_ascii=False, indent=1),
                        "ai_suggested_on": now_datetime()})
    return suggestions
