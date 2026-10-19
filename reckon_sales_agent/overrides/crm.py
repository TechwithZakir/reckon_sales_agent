"""Tenant-aware subclasses of Frappe CRM controllers.

Only the two behaviours that cross Company boundaries are changed; everything
else is inherited from upstream CRM.
"""

from __future__ import annotations

import frappe
from crm.fcrm.doctype.crm_lead.crm_lead import CRMLead
from crm.fcrm.doctype.crm_organization.crm_organization import CRMOrganization
from frappe import _

from reckon_sales_agent.crm_tenancy import (
    COMPANY_FIELD,
    find_organization,
    is_scoping_active,
    unique_organization_name,
)


class TenantCRMLead(CRMLead):
    def create_organization(self, existing_organization=None):
        """Never link a converted lead to another tenant's organization.

        Upstream looks the organization up by name across the whole site and
        copies its details into the lead.
        """
        if not is_scoping_active():
            return super().create_organization(existing_organization)

        company = self.get(COMPANY_FIELD)
        if existing_organization:
            owner = frappe.db.get_value("CRM Organization", existing_organization, COMPANY_FIELD)
            if owner != company:
                frappe.throw(
                    _("Organization {0} belongs to a different Company.").format(existing_organization),
                    frappe.PermissionError,
                )
            return super().create_organization(existing_organization)

        if not self.organization:
            return None

        existing_organization = find_organization(self.organization, company)
        if not existing_organization:
            organization = frappe.new_doc("CRM Organization")
            organization.update(
                {
                    "organization_name": self.organization,
                    "website": self.website,
                    "territory": self.territory,
                    "industry": self.industry,
                    "annual_revenue": self.annual_revenue,
                    COMPANY_FIELD: company,
                }
            )
            if organization.meta.has_field("no_of_employees"):
                organization.no_of_employees = self.get("no_of_employees")
            organization.insert(ignore_permissions=True)
            existing_organization = organization.name
        return super().create_organization(existing_organization)


class TenantCRMOrganization(CRMOrganization):
    def autoname(self):
        if is_scoping_active():
            self.name = unique_organization_name(self.organization_name, self.get(COMPANY_FIELD))
