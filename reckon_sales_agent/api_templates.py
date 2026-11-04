"""Backend for the Message Templates page: AI-written templates, approval, and broadcasts."""

from __future__ import annotations

import json

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
                                             "email_template", "whatsapp_params", "ai_generated", "builder_content"],
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


# Template builder: compile and check a draft per channel, then save it as a draft that still needs approval.

def _content(content) -> dict:
    if isinstance(content, dict):
        return content
    try:
        data = json.loads(content or "{}")
    except ValueError:
        frappe.throw(frappe._("The template content is not valid."))
    return data if isinstance(data, dict) else {}


def _compile(channel: str, data: dict) -> dict:
    """The channel's rules applied to one draft: the issues, and what would be sent."""
    from reckon_sales_agent.campaigns import builder

    if channel == "Email":
        blocks = [b for b in data.get("blocks") or [] if isinstance(b, dict)]
        subject = str(data.get("subject") or "").strip()
        return {"issues": builder.check_email(subject, blocks), "subject": subject,
                "body": builder.email_html(blocks), "text": builder.email_text(blocks), "blocks": blocks}
    if channel == "SMS":
        text = builder.sms_text(str(data.get("text") or ""))
        return {"issues": builder.check_sms(text), "body": text, "chars": builder.sms_length(text),
                "parts": builder.sms_parts(text), "encoding": builder.sms_encoding(text)}
    if channel == "WhatsApp":
        header = str(data.get("header") or "").strip()
        body = str(data.get("body") or "").strip()
        footer = str(data.get("footer") or "").strip()
        buttons = [b for b in data.get("buttons") or [] if isinstance(b, dict)]
        compiled = builder.whatsapp_components(header, body, footer, buttons)
        return {"issues": builder.check_whatsapp(header, body, footer, buttons), "header": header, "body": body,
                "footer": footer, "buttons": buttons, "params": compiled["params"], "components": compiled["components"]}
    frappe.throw(frappe._("Choose Email, SMS or WhatsApp."))


@frappe.whitelist(methods=["POST"])
def check(channel: str, content: str | dict = "{}") -> dict:
    """Preview and checks for a draft. Nothing is saved."""
    _require_manager()
    return _compile(channel, _content(content))


@frappe.whitelist(methods=["POST"])
def save(template: str, content: str | dict = "{}") -> dict:
    """Save the builder's output to a template. It stays a draft until a manager approves it."""
    _require_manager()
    doc = get_tenant_doc("Sales Message Template", template, "write")
    data = _content(content)
    result = _compile(doc.channel, data)
    if doc.channel == "Email":
        doc.subject, doc.body = result["subject"], result["body"]
    elif doc.channel == "SMS":
        doc.body = result["body"]
    else:
        doc.body = result["body"]
        doc.whatsapp_params = ",".join(result["params"])
    doc.builder_content = json.dumps(data, ensure_ascii=False)
    if doc.status == "Approved":
        doc.status = "Draft"  # changed content needs approval again
    doc.content_status = "Needs review" if result["issues"] else "Passed"
    doc.content_issues = "\n".join(result["issues"])[:5000]
    doc.save(ignore_permissions=False)
    return {"issues": result["issues"], "status": doc.content_status}


@frappe.whitelist(methods=["POST"])
def start(channel: str, template_name: str) -> str:
    """A new draft template in the builder, for the chosen channel. Its content is written with the builder."""
    _require_manager()
    company = current_company()
    assert_entitled(company)
    if channel not in ("Email", "SMS", "WhatsApp"):
        frappe.throw(frappe._("Choose Email, SMS or WhatsApp."))
    name = (template_name or "").strip()[:140]
    if not name:
        frappe.throw(frappe._("Give the template a name."))
    doc = frappe.get_doc({"doctype": "Sales Message Template", "company": company, "template_name": name,
                          "channel": channel, "language": "English", "status": "Draft", "body": "-"}).insert()
    return doc.name
