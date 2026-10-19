"""Frappe app registration for Reckon Sales Agent.

Milestone 0: Company (tenant) ownership for Frappe CRM records. Lead
discovery, research, qualification and campaigns build on this in later
milestones.
"""

# Keep in step with crm_tenancy (hooks.py must not import app code); a unit
# test checks that the two lists match.
SCOPED_DOCTYPES = (
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
VENDOR_CONFIG_DOCTYPES = (
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
NAMED_BY_FIELD = (
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
app_description = "AI-assisted lead discovery and sales follow-up for Frappe CRM"
app_email = "support@reckon.tech"
app_license = "MIT"

# reckon_saas_platform is optional: without it CRM tenancy scoping stays off.
required_apps = ["crm"]

after_install = "reckon_sales_agent.install.after_install"
after_migrate = "reckon_sales_agent.install.after_migrate"

override_doctype_class = {
    "CRM Lead": "reckon_sales_agent.overrides.crm.TenantCRMLead",
}

# Composed with CRM's and Frappe's own hooks: Frappe requires every hook to allow.
permission_query_conditions = {
    doctype: "reckon_sales_agent.crm_tenancy.get_query_conditions" for doctype in SCOPED_DOCTYPES
}
has_permission = {
    **{doctype: "reckon_sales_agent.crm_tenancy.has_permission" for doctype in SCOPED_DOCTYPES},
    **{
        doctype: "reckon_sales_agent.crm_tenancy.has_config_permission"
        for doctype in VENDOR_CONFIG_DOCTYPES
    },
}

doc_events = {
    doctype: {
        "before_insert": "reckon_sales_agent.crm_tenancy.bind_company",
        "validate": "reckon_sales_agent.crm_tenancy.validate_company",
    }
    for doctype in SCOPED_DOCTYPES
}
for _doctype in NAMED_BY_FIELD:
    doc_events[_doctype]["autoname"] = "reckon_sales_agent.crm_tenancy.set_tenant_name"
