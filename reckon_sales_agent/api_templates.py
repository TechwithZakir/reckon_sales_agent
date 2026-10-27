"""Backend for the Message Templates page: AI-written templates, approval, and broadcasts."""

from __future__ import annotations

import frappe

from reckon_sales_agent.api_studio import _can_manage
from reckon_sales_agent.tenant import current_company, get_tenant_doc
from reckon_sales_agent.usage import assert_entitled


def _require_manager() -> None:
    if not _can_manage():
        frappe.throw(frappe._("Ask a Sales Agent admin or manager to do this."), frappe.PermissionError)


@frappe.whitelist()
def library() -> dict:
    company = current_company()
    return {
        "templates": frappe.get_list("Sales Message Template", filters={"company": company, "status": ["!=", "Retired"]},
                                     fields=["name", "template_name", "channel", "language", "status", "subject", "body",
                                             "purpose", "content_status", "content_issues", "whatsapp_template",
                                             "email_template", "whatsapp_params", "ai_generated"],
                                     order_by="modified desc", page_length=100),
        "segments": frappe.get_list("Sales Discovery Campaign", filters={"company": company},
                                    fields=["name", "campaign_name"], order_by="modified desc", page_length=50),
        "whatsapp_app": "frappe_whatsapp" in frappe.get_installed_apps(),
        "can_manage": _can_manage(),
    }


@frappe.whitelist()
def write(channel: str, purpose: str, language: str = "English") -> str:
    from reckon_sales_agent.agents.templates import write_template

    _require_manager()
    company = current_company()
    assert_entitled(company)
    return write_template(company, channel, purpose, language if language in ("English", "Bangla") else "English")


@frappe.whitelist()
def approve(template: str, acknowledge_issues: int = 0) -> str:
    from reckon_sales_agent import api
    from reckon_sales_agent.agents.templates import approve as do_approve

    api._require_approver()
    get_tenant_doc("Sales Message Template", template, "write")
    return do_approve(template, bool(int(acknowledge_issues or 0)))


@frappe.whitelist()
def retire(template: str) -> None:
    _require_manager()
    get_tenant_doc("Sales Message Template", template, "write").db_set("status", "Retired")


@frappe.whitelist()
def broadcast(template: str, segment: str | None = None) -> str:
    from reckon_sales_agent.agents.templates import start_broadcast

    _require_manager()
    company = current_company()
    get_tenant_doc("Sales Message Template", template, "read")
    if segment:
        get_tenant_doc("Sales Discovery Campaign", segment, "read")
    return start_broadcast(company, template, segment or None)
