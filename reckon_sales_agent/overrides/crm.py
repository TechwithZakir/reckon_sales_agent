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
    assert_same_company,
    find_contact_by_email,
    find_organization,
    is_scoping_active,
    unique_organization_name,
)


class TenantCRMLead(CRMLead):
    def contact_exists(self, throw=True):
        """Only an existing Contact of the lead's own Company counts as a match.

        Upstream matches the email across the whole site, which either refuses
        the conversion (revealing another tenant's contact) or links to it.
        """
        if not is_scoping_active():
            return super().contact_exists(throw)
        contact = find_contact_by_email(self.email, self.get(COMPANY_FIELD))
        if contact and throw:
            frappe.throw(
                _("Contact already exists with Email: {0}").format(self.email),
                title=_("Contact Already Exists"),
            )
        return contact or False

    def create_contact(self, existing_contact=None, throw=True):
        if existing_contact and is_scoping_active():
            assert_same_company("Contact", existing_contact, self.get(COMPANY_FIELD))
        return super().create_contact(existing_contact, throw)

    def create_organization(self, existing_organization=None):
        """Never link a converted lead to another tenant's organization.

        Upstream looks the organization up by name across the whole site and
        copies its details into the lead.
        """
        if not is_scoping_active():
            return super().create_organization(existing_organization)

        company = self.get(COMPANY_FIELD)
        if existing_organization:
            assert_same_company("CRM Organization", existing_organization, company)
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
