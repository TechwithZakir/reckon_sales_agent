"""Message templates with AI: email and WhatsApp templates written from approved facts, checked, approved, reused.

- ``write_template`` has Claude write a template for a purpose ("first email to pharma distributors") from the
  Company's approved knowledge, in English or Bangla. It is saved as a Draft with the content check's result.
- Approval makes it usable: an approved email template also appears in Frappe CRM's email composer (an Email
  Template owned by the Company); an approved WhatsApp template is submitted to Meta through the
  frappe_whatsapp app when it is installed (business-initiated WhatsApp messages need Meta-approved templates).
- A campaign step can use an approved template; ``start_broadcast`` builds a one-step campaign from a template
  for a whole segment (bulk WhatsApp or email) that still needs a person's launch approval, and reaches only
  leads with consent for that channel.

``meta_body`` and ``template_issues`` are pure.
"""

from __future__ import annotations

import json
import re

from reckon_sales_agent.campaigns.templates import PLACEHOLDER_RE, is_builder_html, strip_html

TEMPLATE_SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"},
                   "notes": {"type": "string"}},
    "required": ["name", "subject", "body", "notes"],
    "additionalProperties": False,
}
TEMPLATE_SYSTEM = (
    "You write one reusable B2B message template for a company selling in Bangladesh. Use ONLY facts in the "
    "approved knowledge: never invent prices, discounts, clients, numbers or guarantees. Use these placeholders "
    "where they fit: {{business_name}}, {{city}}, {{industry}}, {{sender_name}}, {{offer}}, and {{personal_line}} "
    "for an opening the agent writes per lead. Email: subject under 60 characters, body under 120 words, one clear "
    "next step. WhatsApp: under 60 words, friendly, no subject (empty), at most 3 placeholders, and no links "
    "unless the knowledge gives one. Write in the requested language; for Bangla keep product names in English. "
    "name: a short template name. notes: one line on when to use it. Do not add unsubscribe text."
)
NUMBERED = re.compile(r"\{\{\s*(\d+)\s*\}\}")


def meta_body(body: str) -> tuple[str, list[str]]:
    """WhatsApp (Meta) templates number their variables: {{business_name}} … -> {{1}} …, in order of first use."""
    order: list[str] = []

    def number(match):
        name = match.group(1)
        if name not in order:
            order.append(name)
        return "{{" + str(order.index(name) + 1) + "}}"

    return PLACEHOLDER_RE.sub(number, body or ""), order


def template_issues(channel: str, body: str, params: str | None) -> list[str]:
    """Channel rules beyond the content check: WhatsApp variables must be numbered 1..n and all mapped."""
    issues = []
    if channel == "WhatsApp":
        numbers = sorted({int(n) for n in NUMBERED.findall(body or "")})
        mapped = [p.strip() for p in (params or "").split(",") if p.strip()]
        named = list(dict.fromkeys(match.group(1) for match in PLACEHOLDER_RE.finditer(body or "")))
        if numbers:  # Meta's form: {{1}}, {{2}} with the field behind each number in ``params``
            if numbers != list(range(1, len(numbers) + 1)):
                issues.append("WhatsApp variables must be numbered {{1}}, {{2}}… without gaps.")
            if len(mapped) != len(numbers):
                issues.append(f"WhatsApp template has {len(numbers)} variable(s) but {len(mapped)} mapped.")
        elif named != mapped:  # the builder's form: named fields, numbered only when sent to Meta
            issues.append(f"WhatsApp template has {len(named)} variable(s) but {len(mapped)} mapped.")
        if len(body or "") > 1024:
            issues.append("WhatsApp template bodies are limited to 1024 characters.")
    return issues


# --------------------------------------------------------------------------- Frappe side


def check_template(doc) -> dict:
    from reckon_sales_agent.agents.content import check_step
    from reckon_sales_agent.agents.content_agent import approved_knowledge
    from reckon_sales_agent.campaigns.presend import bracket_placeholders

    knowledge = approved_knowledge(doc.company)
    text = "\n".join(f"{k.title}\n{k.content}" for k in knowledge)
    pricing = "\n".join(k.content for k in knowledge if k.category in ("Pricing", "Offer"))
    body = NUMBERED.sub("", doc.body or "") if doc.channel == "WhatsApp" else doc.body
    if doc.channel == "WhatsApp":  # Meta reads the header text and the footer too
        extra = [doc.get("whatsapp_footer")] + ([doc.get("whatsapp_header")] if doc.get("whatsapp_header_type") == "Text" else [])
        body = "\n".join([body or "", *[e for e in extra if e]])
    channel = "Call Task" if doc.channel == "LinkedIn" else doc.channel  # a LinkedIn message is a script we do not send
    issues = check_step({"step_no": 0, "channel": channel, "subject_template": doc.subject or "",
                         "subject_variants": doc.get("subject_variants"), "body_template": body},
                        text, pricing, []) + template_issues(doc.channel, doc.body, doc.whatsapp_params)
    words = strip_html(doc.body) if is_builder_html(doc.body) else (doc.body or "")
    unfilled = bracket_placeholders(doc.subject, words, doc.get("whatsapp_header"), doc.get("whatsapp_footer"),
                                    *_urls(doc.get("builder_content")))
    if unfilled:
        issues.append("Placeholders still to fill: " + ", ".join(unfilled) + ".")
    issues = [i.replace("Step 0 ", "") for i in issues]
    return {"status": "Needs review" if issues else "Passed", "issues": issues}


def _urls(builder_content) -> list[str]:
    """The addresses written in an email builder's blocks, so a link still to fill is not missed."""
    from reckon_sales_agent.campaigns import builder

    try:
        data = json.loads(builder_content or "{}")
    except ValueError:
        return []
    blocks = data.get("blocks") if isinstance(data, dict) else None
    return [str(u) for b in blocks or [] if isinstance(b, dict) for u in builder.block_urls(b) if u]


def write_template(company: str, channel: str, purpose: str, language: str = "English") -> str:
    import frappe
    from frappe import _

    from reckon_sales_agent.agents.content import knowledge_prompt
    from reckon_sales_agent.agents.content_agent import approved_knowledge
    from reckon_sales_agent.constants import USAGE_AI
    from reckon_sales_agent.providers.factory import get_llm
    from reckon_sales_agent.providers.llm import LLMError, untrusted
    from reckon_sales_agent.research.market import business_profile
    from reckon_sales_agent.usage import log_activity, remaining, reserve

    if channel not in ("Email", "WhatsApp", "SMS"):
        frappe.throw(_("Unknown channel."))
    llm = get_llm(company)
    if not llm:
        frappe.throw(_("Turn on AI to write templates."))
    if remaining(company, USAGE_AI) <= 0:
        frappe.throw(_("Monthly AI limit reached."))
    profile = business_profile(company, create=False)
    seller = "\n".join(f"{f}: {profile.get(f)}" for f in ("business_name", "what_we_sell", "products")
                       if profile and profile.get(f))
    reserve(company, USAGE_AI, 1, None)
    frappe.db.commit()
    try:
        data = llm.complete_json(
            TEMPLATE_SYSTEM,
            untrusted("seller", seller or company) + "\n"
            + untrusted("approved knowledge", knowledge_prompt(approved_knowledge(company, language))) + "\n"
            + f"Channel: {channel}\nLanguage: {language}\nPurpose: {(purpose or '')[:500]}",
            TEMPLATE_SCHEMA, max_tokens=2000)
    except LLMError as exc:
        frappe.throw(str(exc))
    body, params = str(data.get("body") or "").strip(), ""
    if channel == "WhatsApp":
        body, order = meta_body(body)
        params = ",".join(order)
    doc = frappe.get_doc({
        "doctype": "Sales Message Template", "company": company, "channel": channel, "language": language,
        "template_name": (" ".join(str(data.get("name") or purpose or "Template").split()))[:140],
        "purpose": (purpose or "")[:1000] + (f"\n\nAI: {data.get('notes')}" if data.get("notes") else ""),
        "subject": " ".join(str(data.get("subject") or "").split())[:140] if channel == "Email" else "",
        "body": body[:3000], "whatsapp_category": "Marketing" if channel == "WhatsApp" else "",
        "whatsapp_params": params, "status": "Draft", "ai_generated": 1,
    })
    result = check_template(doc)
    doc.content_status, doc.content_issues = result["status"], "\n".join(result["issues"])
    doc.flags.ignore_permissions = True
    doc.insert()
    log_activity(company, "content_template_written", doc, f"{channel} template: {doc.template_name}",
                 actor_type="agent", agent="Content", policy_outcome="draft only: a person approves")
    return doc.name


def approve(name: str, acknowledge_issues: bool = False) -> str:
    """Approve a template and publish it where it is used (CRM email composer, Meta via frappe_whatsapp)."""
    import frappe
    from frappe import _
    from frappe.utils import now_datetime

    from reckon_sales_agent.usage import log_activity

    doc = frappe.get_doc("Sales Message Template", name)
    if doc.channel == "Email" and not (doc.subject or "").strip():
        frappe.throw(_("An email template needs a subject before it can be approved."))  # never waved through
    result = check_template(doc)
    if result["issues"] and not acknowledge_issues:
        frappe.throw(_("The content check found issues:") + "<br>" + "<br>".join(
            frappe.utils.escape_html(i) for i in result["issues"][:10]), title=_("Review the template first"))
    updates = {"status": "Approved", "approved_by": frappe.session.user, "approved_on": now_datetime(),
               "content_status": result["status"], "content_issues": "\n".join(result["issues"])[:5000]}
    if doc.channel == "Email":
        updates["email_template"] = _publish_email(doc)
    elif doc.channel == "WhatsApp":
        updates["whatsapp_template"] = _publish_whatsapp(doc)
    doc.db_set(updates)
    log_activity(doc.company, "content_template_approved", doc, doc.template_name, agent="Governance")
    return updates.get("email_template") or updates.get("whatsapp_template") or doc.name


def _publish_email(doc) -> str:
    import frappe

    from reckon_sales_agent.campaigns.templates import text_to_html

    def fallbacks_only(text: str) -> str:
        # The CRM composer renders with Jinja, where {{first_name|there}} would be a filter called "there".
        return PLACEHOLDER_RE.sub(lambda m: frappe.utils.escape_html((m.group(2) or "").strip()), text or "")

    name = f"{doc.template_name} · {doc.company}"[:140]
    body = doc.body if is_builder_html(doc.body) else text_to_html(frappe.utils.escape_html(doc.body))
    values = {"subject": fallbacks_only(doc.subject), "use_html": 1, "response_html": fallbacks_only(body)}
    if frappe.db.exists("Email Template", name):
        frappe.db.set_value("Email Template", name, values)
    else:
        template = frappe.get_doc({"doctype": "Email Template", "name": name, **values})
        if frappe.get_meta("Email Template").has_field("rsa_company"):
            template.rsa_company = doc.company
        template.insert(ignore_permissions=True)
    return name


def _publish_whatsapp(doc) -> str | None:
    """Submit to Meta through frappe_whatsapp (it sends new templates for approval); None when not installed."""
    import frappe

    if "frappe_whatsapp" not in frappe.get_installed_apps() or not frappe.db.exists("DocType", "WhatsApp Templates"):
        frappe.msgprint(frappe._("Approved here. Install the frappe_whatsapp app to submit it to Meta for "
                                 "approval; until then it cannot be sent."), indicator="orange")
        return None
    from reckon_sales_agent.usage import get_settings

    meta = frappe.get_meta("WhatsApp Templates")
    slug = re.sub(r"[^a-z0-9_]", "_", doc.template_name.lower())[:60].strip("_") or "template"
    body, order = meta_body(doc.body)  # Meta wants {{1}}, {{2}}; the template keeps readable names
    order = order or [p.strip() for p in (doc.whatsapp_params or "").split(",") if p.strip()]
    samples = _json(doc.get("whatsapp_samples"), {})
    header_type = {"Text": "TEXT", "Image": "IMAGE", "Document": "DOCUMENT"}.get(doc.get("whatsapp_header_type") or "")
    values = {"template_name": slug, "template": body, "category": (doc.whatsapp_category or "Marketing").upper(),
              "language_code": "bn" if doc.language == "Bangla" else "en",
              "whatsapp_account": get_settings(doc.company).get("whatsapp_account") or None,
              "footer": doc.get("whatsapp_footer") or None, "header_type": header_type,
              "header": doc.get("whatsapp_header") if header_type == "TEXT" else None,
              "sample_values": ",".join(str(samples.get(p) or "") for p in order) or None}
    lang = "bn" if doc.language == "Bangla" else "en"
    if frappe.db.exists("Language", lang):
        values["language"] = lang  # frappe_whatsapp requires a language
    template = frappe.get_doc({"doctype": "WhatsApp Templates", **{k: v for k, v in values.items() if meta.has_field(k)}})
    if meta.has_field("buttons"):
        template.set("buttons", [row for row in (_meta_button(b) for b in _json(doc.get("whatsapp_buttons"), [])) if row])
    template.insert(ignore_permissions=True)
    if header_type in ("IMAGE", "DOCUMENT"):
        frappe.msgprint(frappe._("Attach the sample {0} on the WhatsApp Template {1} before Meta can review it.").format(
            header_type.lower(), template.name), indicator="orange")
    return template.name


def _json(value, default):
    try:
        data = json.loads(value or "")
    except ValueError:
        return default
    return data if isinstance(data, type(default)) else default


def _meta_button(button: dict) -> dict | None:
    """A builder button as a row of frappe_whatsapp's WhatsApp Button table."""
    label = str(button.get("label") or "")[:25]
    if button.get("kind") == "url":
        return {"button_type": "Visit Website", "button_label": label, "website_url": button.get("url"), "url_type": "Static"}
    if button.get("kind") == "phone":
        return {"button_type": "Call Phone", "button_label": label, "phone_number": button.get("phone")}
    return {"button_type": "Quick Reply", "button_label": label} if label else None


def apply_to_step(row, company: str) -> None:
    """A campaign step takes an approved template's exact wording."""
    import frappe
    from frappe import _

    template = frappe.db.get_value("Sales Message Template", row.message_template,
                                   ["company", "status", "channel", "subject", "body", "whatsapp_template",
                                    "whatsapp_params", "subject_variants", "sms_send_window", "agent_actions"], as_dict=True)
    if not template or template.company != company:
        frappe.throw(_("Step {0}: unknown message template.").format(row.step_no))
    if template.status != "Approved":
        frappe.throw(_("Step {0}: the template is not approved yet.").format(row.step_no))
    row.channel = "LinkedIn Task" if template.channel == "LinkedIn" else template.channel  # a person sends it
    row.subject_template = template.subject or ""
    row.subject_variants = template.subject_variants or "" if template.channel == "Email" else ""
    row.send_window = template.sms_send_window or "" if template.channel == "SMS" else (row.get("send_window") or "")
    actions = _json(template.agent_actions, {})
    if "personalize" in actions:
        row.use_ai_personalisation = 1 if actions["personalize"] else 0
    if template.channel == "WhatsApp":
        row.whatsapp_template = template.whatsapp_template
        row.whatsapp_template_params = template.whatsapp_params
        # The body stays readable for the approver; Meta fills the numbered variables.
        names = [p.strip() for p in (template.whatsapp_params or "").split(",") if p.strip()]
        row.body_template = NUMBERED.sub(lambda m: "{{" + names[int(m.group(1)) - 1] + "}}"
                                         if int(m.group(1)) <= len(names) else "", template.body)
    else:
        row.body_template = template.body


def start_broadcast(company: str, template: str, discovery_campaign: str | None = None) -> str:
    """A one-step campaign from an approved template, for a segment or every approved lead; a person launches it."""
    import frappe
    from frappe import _

    from reckon_sales_agent.usage import log_activity

    doc = frappe.get_doc("Sales Message Template", template)
    if doc.company != company or doc.status != "Approved":
        frappe.throw(_("Approve the template first."))
    if doc.channel == "LinkedIn":
        frappe.throw(_("A LinkedIn message is sent by a person: use it as a step in a campaign."))
    if doc.channel == "WhatsApp" and not doc.whatsapp_template:
        frappe.throw(_("This WhatsApp template has not been submitted to Meta yet (install frappe_whatsapp)."))
    campaign = frappe.get_doc({
        "doctype": "Sales Campaign", "company": company, "campaign_name": f"Broadcast · {doc.template_name}"[:140],
        "discovery_campaign": discovery_campaign or None, "minimum_fit_score": 0, "language": doc.language,
        "daily_limit": 200 if doc.channel == "WhatsApp" else 50, "offer": doc.purpose[:500] if doc.purpose else "",
        "steps": [{"step_no": 1, "channel": doc.channel, "delay_days": 0, "message_template": doc.name}],
    })
    campaign.flags.ignore_permissions = True
    campaign.insert()
    campaign.db_set("status", "Pending Approval")
    log_activity(company, "campaign_submitted", campaign,
                 f"{doc.channel} broadcast from template {doc.template_name}; only leads with consent are reached",
                 agent="Content", policy_outcome="needs a person (launch_campaign)")
    return campaign.name
