"""Fixtures for the Playwright end-to-end tests (test and staging sites only).

    bench --site sales-agent-test.localhost execute reckon_sales_agent.e2e.setup_fixtures \
        --kwargs "{'password': '<a test password>'}"

Creates (get-or-create) two tenant Companies subscribed to the Sales Agent
module on a trial plan, each with a Company Admin user, and runs the module
seed. Refuses to run on sites that do not look like test sites.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, nowdate

PLAN = "Sales Agent E2E Trial"
TENANTS = {
    "alpha": ("SA E2E Alpha", "sa-e2e-alpha@example.com"),
    "beta": ("SA E2E Beta", "sa-e2e-beta@example.com"),
}
TEST_SITE_MARKERS = ("test", "staging", ".localhost", "e2e")


def _assert_test_site() -> None:
    site = (frappe.local.site or "").lower()
    if not any(marker in site for marker in TEST_SITE_MARKERS):
        frappe.throw(f"Refusing to create E2E fixtures on {site}: use a test or staging site.")


def setup_fixtures(password: str) -> dict:
    _assert_test_site()
    if not password or len(password) < 10:
        frappe.throw("Pass a test password of at least 10 characters.")
    from reckon_saas_platform import saas

    from reckon_sales_agent.constants import MODULE_KEY
    from reckon_sales_agent.seed import run_sales_agent_seed

    frappe.set_user("Administrator")
    if not frappe.db.exists("SaaS Plan", PLAN):
        frappe.get_doc({
            "doctype": "SaaS Plan", "plan_name": PLAN, "plan_version": "1", "saas_module": MODULE_KEY,
            "enabled": 1, "currency": "BDT", "price": 0, "billing_cycle": "Monthly", "trial_days": 365,
        }).insert(ignore_permissions=True)
    plan = frappe.get_doc("SaaS Plan", PLAN)

    result = {}
    for key, (company_name, email) in TENANTS.items():
        company = frappe.db.get_value("Company", {"company_name": company_name}) \
            or saas._create_tenant_company(company_name).name
        if not frappe.db.exists("User", email):
            saas._create_tenant_admin_user(email, f"E2E {key.title()}", saas_module=MODULE_KEY, password=password)
        else:
            from frappe.utils.password import update_password

            update_password(email, password)
        # Subscription first: role sync on the assignment only acts for subscribed Companies.
        if not frappe.db.exists("SaaS Subscription", {"company": company, "saas_module": MODULE_KEY}):
            frappe.get_doc({
                "doctype": "SaaS Subscription", "company": company, "company_admin": email, "plan": plan.name,
                "saas_module": MODULE_KEY, "plan_version": plan.plan_version, "billing_cycle": "Monthly",
                "status": "Trial", "trial_end_date": add_days(nowdate(), 364), "price": 0, "currency": "BDT",
                "start_date": nowdate(),
            }).insert(ignore_permissions=True)
        saas._assign_company_admin(email, company)
        from reckon_sales_agent.access import sync_user

        sync_user(email)
        run_sales_agent_seed(company, "e2e")
        result[key] = {"company": company, "user": email}
    frappe.db.commit()
    return result
