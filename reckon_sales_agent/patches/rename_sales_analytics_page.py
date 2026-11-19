"""The Analytics page is now called Sales Analytics: Desk shows the title stored on the Page record, which migrate does not refresh."""

import frappe


def execute():
    if frappe.db.exists("Page", "sales-analytics"):
        frappe.db.set_value("Page", "sales-analytics", "title", "Sales Analytics", update_modified=False)
        frappe.clear_cache()
