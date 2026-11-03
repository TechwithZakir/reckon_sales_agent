"""Rename the sending option "Frappe email account" to "System Email" on existing Sales Agent Settings."""

import frappe


def execute():
    frappe.db.sql(
        "update `tabSales Agent Settings` set email_provider = %s where email_provider = %s",
        ("System Email", "Frappe email account"),
    )
