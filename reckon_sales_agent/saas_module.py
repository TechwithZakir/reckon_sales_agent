from __future__ import annotations

from reckon_sales_agent.constants import (
    ADMIN_ROLE,
    ALLOWED_DOCTYPES,
    ALLOWED_PAGES,
    HOME_PAGE,
    HOME_ROUTE,
    MODULE_KEY,
    SAAS_ROLES,
)


def get_module_definition() -> dict:
    """Registration with Reckon SaaS Platform (``reckon_saas_modules`` hook)."""
    return {
        "key": MODULE_KEY,
        "label": "Sales AI Agent",
        "description": "Find, research and qualify B2B customers in Bangladesh, then follow them up "
        "from Frappe CRM, with human approval before any message is sent.",
        "workspace": f"app/{HOME_PAGE}",
        "home_route": HOME_ROUTE,
        "admin_role": ADMIN_ROLE,
        "roles": list(SAAS_ROLES),
        "seed_handler": "reckon_sales_agent.seed.run_sales_agent_seed",
        "subscription_features": [
            "lead_discovery_campaigns",
            "website_research_with_evidence",
            "deterministic_lead_scoring",
            "frappe_crm_sync",
            "email_sequences_with_approval",
            "claude_ai_research_and_drafting",
        ],
        "desk_pages": sorted(ALLOWED_PAGES),
        "desk_doctypes": sorted(ALLOWED_DOCTYPES),
        "desk_reports": [],
    }
