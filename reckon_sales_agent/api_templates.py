"""Backend for the Message Templates page: the library, the builder (check, autosave, AI draft and edit, test send),
sections, approval and broadcasts.

Everything is limited to the session's Company. Anyone who can see the Company's templates can read; changing a template,
drafting with AI and sending a test need a Sales Agent manager. A template is saved as a draft and still needs a person's
approval before a campaign can use it: editing an approved template sends it back to draft.
"""

from __future__ import annotations

import json

import frappe

from reckon_sales_agent.api_studio import _can_manage
from reckon_sales_agent.campaigns import builder, starters, template_content
from reckon_sales_agent.campaigns import templates as t
from reckon_sales_agent.tenant import current_company, get_tenant_doc
from reckon_sales_agent.usage import assert_entitled, get_settings

CHANNELS = ("Email", "SMS", "WhatsApp", "LinkedIn")
LIST_FIELDS = ["name", "template_name", "channel", "language", "status", "subject", "body", "purpose", "content_status",
               "content_issues", "whatsapp_template", "email_template", "whatsapp_params", "ai_generated", "modified"]
# Fields the builder fills from its content: all of these are bound to an approval.
CONTENT_FIELDS = ["subject", "body", "preheader", "subject_variants", "opt_out_keyword", "sms_send_window", "whatsapp_params",
                  "whatsapp_header_type", "whatsapp_header", "whatsapp_footer", "whatsapp_buttons", "whatsapp_samples",
                  "whatsapp_category", "builder_content", "agent_actions", "ai_brief", "ai_goal", "ai_tone"]


def _require_manager() -> None:
    if not _can_manage():
        frappe.throw(frappe._("Ask a Sales Agent admin or manager to do this."), frappe.PermissionError)


def _content(content) -> dict:
    if isinstance(content, dict):
        return content
    try:
        data = json.loads(content or "{}")
    except ValueError:
        frappe.throw(frappe._("The template content is not valid."))
    return data if isinstance(data, dict) else {}


def _channel(channel: str) -> str:
    if channel not in CHANNELS:
        frappe.throw(frappe._("Choose Email, SMS, WhatsApp or LinkedIn."))
    return channel


def _has_address(company: str) -> bool:
    return bool((get_settings(company).get("physical_address") or "").strip())


def _ai_available(company: str) -> bool:
    from reckon_sales_agent.providers.factory import get_llm

    try:
        return bool(get_llm(company))
    except Exception:  # a misconfigured provider must not break the page; the draft call says what is wrong
        return False


# Library -------------------------------------------------------------------


@frappe.whitelist()
def library() -> dict:
    company = current_company()
    sections = [{**s, "builtin": True} for s in starters.BUILTIN_SECTIONS]
    for row in frappe.get_list("Sales Template Section", filters={"company": company},
                               fields=["name", "section_name", "blocks"], order_by="modified desc", page_length=50):
        try:
            blocks = json.loads(row.blocks or "[]")
        except ValueError:
            continue
        sections.append({"id": row.name, "name": row.section_name, "blocks": blocks, "builtin": False})
    return {
        "company": company,
        "templates": frappe.get_list("Sales Message Template", filters={"company": company, "status": ["!=", "Retired"]},
                                     fields=LIST_FIELDS, order_by="modified desc", page_length=200),
        "segments": frappe.get_list("Sales Discovery Campaign", filters={"company": company},
                                    fields=["name", "campaign_name"], order_by="modified desc", page_length=50),
        "whatsapp_app": "frappe_whatsapp" in frappe.get_installed_apps(),
        "can_manage": _can_manage(),
        "ai": _ai_available(company),
        "has_address": _has_address(company),
        "fields": [{"group": g, "key": k, "label": label, "sample": sample, "fallback": fb}
                   for g, k, label, sample, fb, _needs in t.FIELDS],
        "starters": starters.starter_summaries(),
        "sections": sections,
        "palette": list(builder.PALETTE),
        "new_blocks": {kind: builder.new_block(kind) for kind in builder.EMAIL_BLOCKS},
        "limits": {"subject": 60, "sms_parts": builder.SMS_MAX_PARTS, "wa_body": builder.WA_BODY_MAX,
                   "wa_header": builder.WA_HEADER_MAX, "wa_footer": builder.WA_FOOTER_MAX, "wa_buttons": builder.WA_BUTTON_MAX,
                   "wa_label": builder.WA_QUICK_REPLY_MAX, "variants": builder.MAX_VARIANTS},
        "actions_available": list(template_content.ACTIONS_AVAILABLE),
    }


@frappe.whitelist()
def get(template: str) -> dict:
    """One template with its builder content, ready to edit."""
    doc = get_tenant_doc("Sales Message Template", template, "read")
    fields = {f: doc.get(f) for f in CONTENT_FIELDS}
    content = template_content.content_from_fields(doc.channel, fields)
    return {"name": doc.name, "template_name": doc.template_name, "channel": doc.channel, "language": doc.language,
            "status": doc.status, "content_status": doc.content_status, "content_issues": doc.content_issues,
            "whatsapp_template": doc.whatsapp_template, "modified": str(doc.modified), "content": content,
            "result": template_content.compile_content(doc.channel, content, has_address=_has_address(doc.company))}


@frappe.whitelist(methods=["POST"])
def check(channel: str, content: str | dict = "{}") -> dict:
    """Problems and pre-send checks for a draft, and its preview. Nothing is saved."""
    company = current_company()
    return template_content.compile_content(_channel(channel), _content(content), has_address=_has_address(company))


@frappe.whitelist()
def starter(starter_id: str, channel: str) -> dict | None:
    """A starter's content for the channel, ready to load into the builder. Nothing is saved."""
    channel = _channel(channel)
    found = starters.starter_content(starter_id, channel)
    if not found:
        return None
    content = template_content.with_starter(channel, found)
    return {"content": content, "result": template_content.compile_content(channel, content, has_address=_has_address(current_company()))}


@frappe.whitelist(methods=["POST"])
def start(channel: str, template_name: str, starter: str | None = None, language: str = "English") -> str:
    """A new draft template, blank or from a starter."""
    _require_manager()
    company = current_company()
    assert_entitled(company)
    channel = _channel(channel)
    name = " ".join((template_name or "").split())[:140]
    if not name:
        frappe.throw(frappe._("Give the template a name."))
    content = template_content.with_starter(channel, starters.starter_content(starter, channel) if starter else None)
    doc = frappe.get_doc({"doctype": "Sales Message Template", "company": company, "template_name": name, "channel": channel,
                          "language": language if language in ("English", "Bangla") else "English", "status": "Draft",
                          **template_content.fields_to_store(channel, content)})
    doc.insert()
    return doc.name


@frappe.whitelist(methods=["POST"])
def save(template: str, content: str | dict = "{}", template_name: str | None = None, language: str | None = None) -> dict:
    """Save the builder's content as a draft (the screen autosaves). Editing an approved template sends it back to draft."""
    _require_manager()
    doc = get_tenant_doc("Sales Message Template", template, "write")
    channel = doc.channel
    stored = template_content.fields_to_store(channel, _content(content))
    was_approved = doc.status == "Approved"
    for field, value in stored.items():
        doc.set(field, value)
    if template_name and template_name.strip():
        doc.template_name = " ".join(template_name.split())[:140]
    if language in ("English", "Bangla"):
        doc.language = language
    doc.save()  # the controller checks the content and returns an approved template to draft if its wording changed
    return {"name": doc.name, "status": doc.status, "content_status": doc.content_status,
            "content_issues": doc.content_issues, "modified": str(doc.modified),
            "back_to_draft": was_approved and doc.status != "Approved",
            "result": template_content.compile_content(channel, template_content.content_from_fields(
                channel, {f: doc.get(f) for f in CONTENT_FIELDS}), has_address=_has_address(doc.company))}


@frappe.whitelist(methods=["POST"])
def duplicate(template: str) -> str:
    """A copy as a new draft, to change without touching an approved template."""
    _require_manager()
    source = get_tenant_doc("Sales Message Template", template, "read")
    content = template_content.content_from_fields(source.channel, {f: source.get(f) for f in CONTENT_FIELDS})
    doc = frappe.get_doc({"doctype": "Sales Message Template", "company": source.company, "channel": source.channel,
                          "template_name": f"{source.template_name} (copy)"[:140], "language": source.language,
                          "status": "Draft", **template_content.fields_to_store(source.channel, content)})
    doc.insert()
    return doc.name


# AI ------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def ai_draft(channel: str, brief: str = "", goal: str = "", tone: str = "Friendly", language: str = "English",
             keyword: str = "STOP") -> dict:
    """A first draft from a brief, for the person to edit. Nothing is saved."""
    from reckon_sales_agent.agents.template_ai import draft

    _require_manager()
    company = current_company()
    assert_entitled(company)
    content = draft(company, _channel(channel), brief, goal, tone, language, keyword)
    return {"content": content, "result": template_content.compile_content(channel, content, has_address=_has_address(company))}


@frappe.whitelist(methods=["POST"])
def ai_edit(channel: str, text: str, instruction: str, language: str = "English") -> str:
    """One piece of text rewritten as asked: shorter, in Bangla, friendlier. Merge fields are kept."""
    from reckon_sales_agent.agents.template_ai import rewrite

    _require_manager()
    company = current_company()
    assert_entitled(company)
    return rewrite(company, _channel(channel), text, instruction, language)


@frappe.whitelist(methods=["POST"])
def write(channel: str, purpose: str, language: str = "English") -> str:
    """The older one-shot AI template (a whole template from a purpose)."""
    from reckon_sales_agent.agents.templates import write_template

    _require_manager()
    company = current_company()
    assert_entitled(company)
    return write_template(company, channel, purpose, language if language in ("English", "Bangla") else "English")


# Test send ------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def send_test(template: str) -> dict:
    """Email the template to the signed-in person only, with sample values. Nothing is tracked and nobody else is contacted."""
    _require_manager()
    doc = get_tenant_doc("Sales Message Template", template, "read")
    if doc.channel != "Email":
        frappe.throw(frappe._("A test can be sent for email templates. Preview SMS and WhatsApp in the builder."))
    recipient = frappe.db.get_value("User", frappe.session.user, "email") or frappe.session.user
    if "@" not in recipient:
        frappe.throw(frappe._("Your user has no email address to send the test to."))
    samples = t.sample_values()
    body = t.render(t.resolve_dynamic(doc.body, samples), samples)
    if not t.is_builder_html(body):
        body = t.text_to_html(body)
    notice = ('<p style="color:#888;font-size:12px">' + frappe.utils.escape_html(
        f"This is a test of the template “{doc.template_name}”, filled with sample values. Nobody else received it.") + "</p>")
    frappe.sendmail(recipients=[recipient], subject="[Test] " + t.render(doc.subject or doc.template_name, samples, escape=False),
                    message=body + notice, now=True)
    from reckon_sales_agent.usage import log_activity

    log_activity(doc.company, "template_test_sent", doc, "A test email to the person who asked", agent="Content",
                 policy_outcome="sent to the requesting user only")
    return {"sent_to": recipient}


# Sections ------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def save_section(section_name: str, blocks: str | list = "[]") -> str:
    """Keep a group of blocks to reuse in other emails."""
    _require_manager()
    company = current_company()
    name = " ".join((section_name or "").split())[:140]
    if not name:
        frappe.throw(frappe._("Give the section a name."))
    raw = blocks if isinstance(blocks, list) else json.loads(blocks or "[]")
    clean = template_content.normalize("Email", {"blocks": raw})["blocks"]
    if not clean:
        frappe.throw(frappe._("Choose at least one block to save."))
    doc = frappe.get_doc({"doctype": "Sales Template Section", "company": company, "section_name": name, "channel": "Email",
                          "blocks": json.dumps(clean, ensure_ascii=False)})
    doc.insert()
    return doc.name


@frappe.whitelist(methods=["POST"])
def delete_section(section: str) -> None:
    _require_manager()
    doc = get_tenant_doc("Sales Template Section", section, "delete")
    frappe.delete_doc("Sales Template Section", doc.name)


# Approval and use ----------------------------------------------------------


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
