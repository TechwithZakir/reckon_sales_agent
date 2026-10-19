"""Frappe app registration for Reckon Sales Agent.

Milestone 0: Company (tenant) ownership for native Frappe CRM records. Lead
discovery, research, qualification and campaigns build on this in later
milestones.
"""

# Keep in step with crm_tenancy.SCOPED_DOCTYPES (hooks.py must not import app code).
SCOPED_DOCTYPES = (
    "CRM Lead",
    "CRM Deal",
    "CRM Organization",
    "Contact",
    "CRM Task",
    "FCRM Note",
    "CRM Call Log",
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
    "CRM Organization": "reckon_sales_agent.overrides.crm.TenantCRMOrganization",
}

# Composed with CRM's own org-hierarchy hooks: Frappe requires every hook to allow.
permission_query_conditions = {
    doctype: "reckon_sales_agent.crm_tenancy.get_query_conditions" for doctype in SCOPED_DOCTYPES
}
has_permission = {doctype: "reckon_sales_agent.crm_tenancy.has_permission" for doctype in SCOPED_DOCTYPES}

doc_events = {
    doctype: {
        "before_insert": "reckon_sales_agent.crm_tenancy.bind_company",
        "validate": "reckon_sales_agent.crm_tenancy.validate_company",
    }
    for doctype in SCOPED_DOCTYPES
}
