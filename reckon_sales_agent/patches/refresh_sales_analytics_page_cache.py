"""Browsers keep a copy of each page until the page record changes: touch Sales Analytics so everyone fetches the renamed page."""

import frappe


def execute():
    if frappe.db.exists("Page", "sales-analytics"):
        frappe.db.set_value("Page", "sales-analytics", "modified", frappe.utils.now_datetime(), update_modified=False)
        frappe.clear_cache()
