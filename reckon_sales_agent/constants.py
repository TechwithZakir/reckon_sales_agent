"""Single source of truth for the Sales Agent SaaS module: roles, reach and limits.

Kept free of Frappe imports so pure services and tests can use it.
"""

from __future__ import annotations

MODULE_KEY = "sales_agent"
MODULE_NAME = "Reckon Sales Agent"
HOME_PAGE = "sales-agent"
REVIEW_PAGE = "sales-review"
ANALYTICS_PAGE = "sales-analytics"
HOME_ROUTE = f"/desk/{HOME_PAGE}"
WORKSPACE_SIDEBAR = "Sales Agent"

ADMIN_ROLE = "Reckon Sales Agent Admin"
MANAGER_ROLE = "Reckon Sales Agent Manager"
USER_ROLE = "Reckon Sales Agent User"
SAAS_ROLES = (ADMIN_ROLE, MANAGER_ROLE, USER_ROLE)
VENDOR_ROLES = ("System Manager", "Reckon Vendor Superuser")

# Frappe CRM's own roles carry the CRM document permissions; tenant isolation
# comes from crm_tenancy, not from roles.
# Keys are Tenant User Assignment role profiles; any other profile on a Sales
# Agent Company gets the "Sales User" roles.
PROFILE_ROLES: dict[str, tuple[str, ...]] = {
    "Company Admin": (ADMIN_ROLE, "Sales Manager", "Sales User"),
    "Company Manager": (MANAGER_ROLE, "Sales Manager", "Sales User"),
    "Sales User": (USER_ROLE, "Sales User"),
}
MANAGED_ROLES = frozenset(role for roles in PROFILE_ROLES.values() for role in roles)
APPROVER_ROLES = frozenset({ADMIN_ROLE, MANAGER_ROLE, *VENDOR_ROLES})

# Company-owned Sales Agent DocTypes (all have a ``company`` field).
COMPANY_DOCTYPES = (
    "Sales Agent Settings",
    "Sales Source Connector",
    "Sales Discovery Campaign",
    "Sales Discovery Job",
    "Sales Prospect",
    "Sales Research Report",
    "Sales Qualification Profile",
    "Sales Qualification",
    "Sales Campaign",
    "Sales Campaign Member",
    "Sales Outreach Message",
    "Sales Communication Event",
    "Sales Agent Activity",
    "Sales Suppression Entry",
    "Sales Usage Ledger",
    "Sales Targeting Profile",
    "Sales Campaign Insight",
)
CHILD_DOCTYPES = ("Sales Planned Query", "Sales Research Fact", "Sales Campaign Step", "Sales Target Location")
CHANNELS = ("Email", "SMS", "WhatsApp", "Call Task", "LinkedIn Task")
TASK_CHANNELS = frozenset({"Call Task", "LinkedIn Task"})
PLATFORM_SETTINGS = "Sales Agent Platform Settings"

# Everything the Frappe CRM app (/crm) reads or writes. Tenants on several
# modules get the union of each module's lists, so this must stay complete or
# another module's Desk guard would block the CRM for shared tenants.
CRM_DOCTYPES = (
    "CRM Lead", "CRM Deal", "CRM Organization", "CRM Task", "FCRM Note", "CRM Call Log",
    "CRM Notification", "CRM Product", "CRM Territory", "CRM Industry", "CRM Lead Source",
    "CRM Lost Reason", "CRM Lead Status", "CRM Deal Status", "CRM Communication Status",
    "CRM View Settings", "CRM Dashboard", "CRM Holiday List", "CRM Service Level Agreement",
    "CRM Sales Hierarchy", "CRM Telephony Agent", "CRM Invitation", "CRM Fields Layout",
    "CRM Form Script", "CRM Global Settings", "FCRM Settings", "CRM Twilio Settings",
    "CRM Exotel Settings", "ERPNext CRM Settings",
    # child tables
    "CRM Contacts", "CRM Products", "CRM Status Change Log", "CRM Dropdown Item", "CRM Holiday",
    "CRM Service Day", "CRM Service Level Priority", "CRM Rolling Response Time",
    "CRM Telephony Phone", "CRM Product Sync Issue",
    # Frappe records the CRM uses
    "Contact", "Address", "Dynamic Link", "Contact Email", "Contact Phone", "Email Template",
    "Communication", "Comment", "ToDo", "File", "Gender", "Salutation",
)
GLOBAL_DOCTYPES = ("Company", "User", "Currency", "Country", "DocType", "Report", "List Filter")
ALLOWED_DOCTYPES = frozenset(COMPANY_DOCTYPES + CHILD_DOCTYPES + (PLATFORM_SETTINGS,) + CRM_DOCTYPES + GLOBAL_DOCTYPES)
LOOKUP_ONLY_DOCTYPES = frozenset(
    {"DocType", "Report", "List Filter", "User", "Currency", "Country", PLATFORM_SETTINGS}
    | set(CHILD_DOCTYPES)
    | set(CRM_DOCTYPES)
)
ALLOWED_PAGES = frozenset({HOME_PAGE, REVIEW_PAGE, ANALYTICS_PAGE, "print", "user-profile", "home"})

LEAD_SOURCE = "Sales Agent"

# Usage types metered against plan limits (per Company, per calendar month).
USAGE_DISCOVERY = "Discovery Result"
USAGE_RESEARCH = "Research Page"
USAGE_AI = "AI Call"
USAGE_MESSAGE = "Message Sent"
USAGE_LIMIT_FIELDS = {
    USAGE_DISCOVERY: "monthly_discovery_limit",
    USAGE_RESEARCH: "monthly_research_limit",
    USAGE_AI: "monthly_ai_limit",
    USAGE_MESSAGE: "monthly_message_limit",
}
DEFAULT_LIMITS = {
    "monthly_discovery_limit": 1000,
    "monthly_research_limit": 1500,
    "monthly_ai_limit": 500,
    "monthly_message_limit": 1000,
}

DEFAULT_AI_MODEL = "claude-opus-5-5"
