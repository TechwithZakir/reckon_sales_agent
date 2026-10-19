"""Reckon Sales AI Agent: lead discovery, research, qualification and follow-up on Frappe CRM.

A Reckon SaaS Platform module. Every tenant is a Company on the shared site;
crm_tenancy separates Frappe CRM by Company, and the Sales Agent's own
DocTypes use the platform's tenant hooks.
"""

# Private aliases: Frappe reads every public name in hooks.py as a hook.
from reckon_sales_agent import constants as _c

# Keep in step with crm_tenancy (a unit test checks that the lists match).
_CRM_SCOPED = (
    # Data: strictly per Company.
    "CRM Lead",
    "CRM Deal",
    "CRM Organization",
    "Contact",
    "Address",
    "CRM Task",
    "FCRM Note",
    "CRM Call Log",
    "CRM Notification",
    "CRM Product",
    "CRM Sales Hierarchy",
    "CRM Telephony Agent",
    "CRM Invitation",
    "Communication",
    "Comment",
    "ToDo",
    "File",
    # Master lists: per Company plus shared read-only defaults.
    "CRM Territory",
    "CRM Industry",
    "CRM Lead Source",
    "CRM Lost Reason",
    "CRM Holiday List",
    "CRM Service Level Agreement",
    "CRM Dashboard",
    "CRM View Settings",
)
_CRM_CONFIG = (
    "FCRM Settings",
    "CRM Twilio Settings",
    "CRM Exotel Settings",
    "ERPNext CRM Settings",
    "CRM Global Settings",
    "CRM Fields Layout",
    "CRM Form Script",
    "CRM Lead Status",
    "CRM Deal Status",
    "CRM Communication Status",
)
_NAMED_BY_FIELD = (
    "CRM Organization",
    "CRM Product",
    "CRM Territory",
    "CRM Industry",
    "CRM Lead Source",
    "CRM Lost Reason",
    "CRM Holiday List",
    "CRM Service Level Agreement",
    "CRM Dashboard",
)

app_name = "reckon_sales_agent"
app_title = "Reckon Sales Agent"
app_publisher = "Reckon Technologies Ltd."
app_description = "AI-assisted B2B lead discovery, research and follow-up on Frappe CRM"
app_email = "hello@reckon.tech"
app_license = "MIT"
app_logo_url = "/assets/reckon_sales_agent/images/sales-agent-icon.svg"
app_icon_url = app_logo_url
app_icon_title = "Sales Agent"
app_icon_route = _c.HOME_ROUTE

required_apps = ["frappe", "erpnext", "crm", "reckon_saas_platform"]

add_to_apps_screen = [
    {
        "name": app_name,
        "logo": app_logo_url,
        "title": "Sales Agent",
        "route": app_icon_route,
        "desk_route": app_icon_route,
        "has_permission": "reckon_sales_agent.api.check_app_permission",
        "sequence_id": 30,
    }
]

after_install = "reckon_sales_agent.install.after_install"
after_migrate = "reckon_sales_agent.install.after_migrate"

reckon_saas_modules = ["reckon_sales_agent.saas_module.get_module_definition"]

before_request = ["reckon_sales_agent.desk_guard.restrict_sales_agent_desk_request"]
after_request = ["reckon_sales_agent.desk_guard.redirect_sales_agent_desk_response"]
get_website_user_home_page = "reckon_sales_agent.desk_guard.get_user_home_page"

override_doctype_class = {
    "CRM Lead": "reckon_sales_agent.overrides.crm.TenantCRMLead",
}

_TENANT = "reckon_saas_platform.tenant_security"
_CRM = "reckon_sales_agent.crm_tenancy"

# Composed with CRM's and Frappe's own hooks: Frappe requires every hook to allow.
permission_query_conditions = {
    **{doctype: f"{_CRM}.get_query_conditions" for doctype in _CRM_SCOPED},
    **{doctype: f"{_TENANT}.get_tenant_owned_query" for doctype in _c.COMPANY_DOCTYPES},
}
has_permission = {
    **{doctype: f"{_CRM}.has_permission" for doctype in _CRM_SCOPED},
    **{doctype: f"{_CRM}.has_config_permission" for doctype in _CRM_CONFIG},
    **{doctype: f"{_TENANT}.has_tenant_owned_permission" for doctype in _c.COMPANY_DOCTYPES},
    _c.PLATFORM_SETTINGS: f"{_CRM}.has_config_permission",
}

doc_events = {
    **{
        doctype: {"before_insert": f"{_CRM}.bind_company", "validate": f"{_CRM}.validate_company"}
        for doctype in _CRM_SCOPED
    },
    **{doctype: {"validate": "reckon_sales_agent.tenant.validate_company_document"}
       for doctype in _c.COMPANY_DOCTYPES},
    "Tenant User Assignment": {"on_update": "reckon_sales_agent.access.sync_tenant_user_access"},
}
for _doctype in _NAMED_BY_FIELD:
    doc_events[_doctype]["autoname"] = f"{_CRM}.set_tenant_name"
doc_events["Communication"]["after_insert"] = "reckon_sales_agent.campaigns.engine.handle_communication"
doc_events["CRM Deal"]["after_insert"] = "reckon_sales_agent.campaigns.engine.handle_deal"
# Inbound WhatsApp replies (only fires when the frappe_whatsapp app is installed).
doc_events["WhatsApp Message"] = {"after_insert": "reckon_sales_agent.campaigns.engine.handle_whatsapp"}

scheduler_events = {
    "hourly": [
        "reckon_sales_agent.campaigns.engine.run_campaign_tick",
        "reckon_sales_agent.jobs.recover_stuck_jobs",
    ],
    "daily": [
        "reckon_sales_agent.jobs.run_scheduled_discovery",
        "reckon_sales_agent.jobs.purge_expired_source_data",
    ],
    "weekly": [
        "reckon_sales_agent.qualification.service.recalibrate_all",
        "reckon_sales_agent.campaigns.analytics.analyze_active_campaigns",
    ],
}

fixtures = [{"dt": "Role", "filters": [["name", "in", list(_c.SAAS_ROLES)]]}]
